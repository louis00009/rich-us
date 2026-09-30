"""AI 每日必读（Intel Daily Digest）
==================================
解决三个真实痛点：

  1. **抓得多、看得少**：实测近 3 天入库 587 条事件，其中 5★ 只有 22 条。
     平铺列表把 22 条真正重要的信息埋掉了 —— 这里按**确定性重要度**排序并只留必读。
  2. **「为什么重要」没人说**：每条必读都带规则化理由（影响度/方向/阶段/类别/新鲜度），
     不靠 LLM 也能解释清楚。
  3. **「什么时候买」没人答**：结合量化快照的关键价位，给出关注区间、触发条件、
     失效条件 —— 全部来自平台真实数据（`analyze_local(snap, "swing")` 的支撑/阻力，
     以及 `market_snapshot` 的 atr14 / 现价 / RSI）。

设计铁律（与项目既有约定一致）
--------------------------------
· **确定性优先**：`score_event()` 是纯函数，不联网、不调 LLM，可单测。
  LLM 深度解读是**可选附加**，缺失不影响清单可用（也满足「AI 一律手动触发」）。
· **不编造**：时机区间一律取自真实支撑/压力位；取不到就如实写「数据未覆盖」。
· **可留痕**：每次生成 upsert 到 `intel_digests`，同一天重复生成覆盖而非堆积。
· **不越权**：输出的是「关注/观察」措辞与条件，不是买入信号（平台所有交易动作
  必须走 ai_proposals + 人工批准）。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session

from .database import session_scope
from . import intel_classify as classify
from .models import IntelAnalysis, IntelCompany, IntelDigest, IntelEvent
# 评分纯函数区拆至 intel_digest_scoring.py —— re-export 保持旧路径与打桩兼容：
from .intel_digest_scoring import (  # noqa: F401,E402
    CATEGORY_WEIGHT,
    DIGEST_DAYS,
    SOURCE_WEIGHT_HINT,
    STAGE_WEIGHT,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_MEDIUM,
    _BASE_MAX,
    _COMMENTARY_CAP,
    _FRESH_FLOOR,
    _MOD_MAX,
    _MOD_MIN,
    _freshness,
    _parse_day,
    _source_weight,
    score_event,
)

log = logging.getLogger("quantdesk.intel.digest")


DIGEST_TOP_N = 12      # 必读条数上限
DIGEST_PER_SYMBOL = 2  # 单只标的在必读里最多占几条（防止一家刷屏）
# critical 也限 2 条：曾出现一家标的靠 3 条 critical 免配额占掉 top 的 1/4，
# 用户观感就是「必读永远不变」——重大事件优先，但不允许一家霸屏（2026-09-30）。
DIGEST_PER_SYMBOL_CRITICAL = 2

_HIGH_IMPACT = 4       # 达到该影响度即视为「重大事件」，不设阈值直接进必读




# ------------------------------------------------------------------
# 采集候选事件
# ------------------------------------------------------------------
def _candidate_events(db: Session, days: int, symbol: str | None) -> list[dict[str, Any]]:
    """取窗口内的候选事件（按发生日，日期未知的退回入库时间）。"""
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    q = db.query(IntelEvent).filter(IntelEvent.occurred_on >= cutoff)
    if symbol:
        q = q.filter(IntelEvent.symbol == symbol.strip().upper())
    rows = (
        q.order_by(
            case((IntelEvent.occurred_on != "", 0), else_=1),
            IntelEvent.occurred_on.desc(),
            IntelEvent.impact.desc(),
            IntelEvent.id.desc(),
        ).limit(1200).all()
    )
    return [
        {
            "id": e.id, "symbol": e.symbol, "occurred_on": e.occurred_on,
            "occurred_at": e.occurred_at or "", "category": e.category,
            "title": e.title, "summary": e.summary, "impact": e.impact,
            "sentiment": e.sentiment, "stage": e.stage,
            "source_name": e.source_name, "source_url": e.source_url, "agent": e.agent,
            # 入库时刻（naive UTC）：「今日新增」按本地日历日统计，不用 occurred_on
            # —— 凌晨抓到的新闻 occurred_on 是 UTC 的「昨天」，按发生日算会漏
            "created_at": e.created_at,
            # 评论类不参与重点判定（见 _COMMENTARY_CAP）；这里算一次，供 score_event 使用
            "commentary": classify.is_commentary(e.title or ""),
        }
        for e in rows
    ]


# ------------------------------------------------------------------
# 买入时机（全部来自真实量化数据，取不到就如实说明）
# ------------------------------------------------------------------
def _timing_for(symbol: str, rec: str | None) -> dict[str, Any]:
    """给出关注区间 / 触发条件 / 失效条件。

    价位一律来自平台真实量化数据（`analyze_local` 的支撑/阻力 = 唐奇安/布林/均线/52周
    与 ATR 的合成，见 ai_analyst.py）。取不到时 zone 留空并写明原因，
    绝不用「大概在 xx 附近」这类编造数值糊弄。

    三类「不给价位」的情形都必须留空 + 说明：
      · 行情接口报错；
      · 只有**合成行情**（`source == "synthetic"`，数据源链路的离线兜底）；
      · 能取到行情但没有可用的支撑位。
    """
    out: dict[str, Any] = {"zone_low": None, "zone_high": None, "trigger": "", "invalidation": "",
                           "rsi14": None, "price": None, "note": ""}
    try:
        from .ai_analyst import analyze_local, market_snapshot

        snap = market_snapshot(symbol) or {}
        if snap.get("error"):
            out["note"] = f"行情不可用（{snap.get('error')}），本次未给出价位区间"
            return out
        # ⚠️ 数据源链路在取不到真实行情时会**静默回落合成随机漫步**（source="synthetic"）。
        # 若不拦，未知/退市标的也会「算」出支撑阻力与现价 —— 那就是编造。
        # 项目既有约定：合成行情必须显式标注且不得用于任何决策（见 api/optimize.py、api/trading.py）。
        if str(snap.get("source") or "") == "synthetic":
            out["note"] = "该标的只有合成行情（无真实数据），本次不给出价位区间"
            out["price"] = None
            return out
        local = analyze_local(snap, "swing") or {}
    except Exception as exc:  # noqa: BLE001 —— 取不到行情不影响清单本身
        out["note"] = f"行情不可用（{type(exc).__name__}），本次未给出价位区间"
        return out

    levels = local.get("levels") or {}
    sup = [v for v in (levels.get("支撑") or []) if isinstance(v, (int, float)) and v > 0]
    res = [v for v in (levels.get("阻力") or []) if isinstance(v, (int, float)) and v > 0]
    price = snap.get("price")
    out["price"] = round(float(price), 4) if isinstance(price, (int, float)) else None
    rsi = (snap.get("indicators") or {}).get("rsi14")
    out["rsi14"] = round(float(rsi), 1) if isinstance(rsi, (int, float)) else None
    atr = (snap.get("levels") or {}).get("atr14")
    out["atr14"] = round(float(atr), 4) if isinstance(atr, (int, float)) else None

    # 支撑已按由近到远降序：sup[0] 是最近支撑，sup[-1] 是最远支撑
    if sup:
        near, far = round(sup[0], 4), round(sup[-1], 4)
        out["zone_low"], out["zone_high"] = min(near, far), max(near, far)
        out["trigger"] = (
            f"回踩 {out['zone_high']} ~ {out['zone_low']} 支撑区间企稳（缩量或长下影）后再看；"
            f"放量跌破 {out['zone_low']} 则本次逻辑暂不成立"
        )
    elif out["price"]:
        out["trigger"] = "量化关键支撑位不可用，建议等回踩后重新评估，不要追高"
    if res:
        out["invalidation"] = f"上方最近压力 {round(res[0], 4)}；放量有效突破后需重新评估空间"
    if out["rsi14"] is not None and out["rsi14"] >= 70:
        out["trigger"] = (f"RSI14 已达 {out['rsi14']:.0f}（超买），当前位置追高风险偏高；"
                          + (out["trigger"] or ""))
    if rec in ("reduce", "avoid"):
        out["trigger"] = "当前 AI 判定偏空，时机上以规避为主，不构成介入条件"
    if not out["zone_low"] and not out["note"]:
        out["note"] = "该标的量化关键价位暂不可用"
    return out


# ------------------------------------------------------------------
# 构建必读清单
# ------------------------------------------------------------------
def _pick_top(scored: list[dict[str, Any]], top_n: int, per_symbol: int,
              critical_per_symbol: int = DIGEST_PER_SYMBOL_CRITICAL) -> list[dict[str, Any]]:
    """按重要度取前 N 条，同时限制单标的条数（避免一家公司刷屏）。

    重要度 >= TIER_CRITICAL 的条目配额放宽到 critical_per_symbol（默认 2）——
    重大事件优先，但**不再无上限**：旧版 critical 免配额，SPCX 曾一次占 3 席，
    清单连续几天看起来一模一样（2026-09-30 用户反馈「必读一直是旧的」根因之一）。
    """
    scored.sort(key=lambda x: (-x["importance"], -x["impact"], x["occurred_on"] or "", -x["id"]))
    picked: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for it in scored:
        if len(picked) >= top_n:
            break
        sym = it["symbol"]
        cap = critical_per_symbol if it["importance"] >= TIER_CRITICAL else per_symbol
        if used.get(sym, 0) >= cap:
            continue
        used[sym] = used.get(sym, 0) + 1
        picked.append(it)
    return picked


def _fold_families(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同题折叠：同一标的同一天的多条事件只留重要度最高的一条进必读候选。

    为什么需要：dedupe_key 按标题精确匹配，同一条消息被多家媒体各写一遍
    （「星舰 Flight 14 完成入轨」/「SpaceX Launches Starship Flight 14」…）
    各自成条，一个事件家族就能占掉 top 多席 —— 用户看到的永远是同一天
    几家媒体对同一件事的复述。被折叠掉的事件仍参与 by_symbol / totals 统计，
    只是不再重复占「必读」席位。纯函数，可单测。
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for it in scored:
        key = (it["symbol"], it["occurred_on"] or "")
        cur = best.get(key)
        if cur is None or it["importance"] > cur["importance"]:
            best[key] = it
    return list(best.values())


def build_digest(days: int = DIGEST_DAYS, symbol: str | None = None,
                 top_n: int = DIGEST_TOP_N, per_symbol: int = DIGEST_PER_SYMBOL) -> dict[str, Any]:
    """构建每日必读清单（确定性，无 LLM、无网络以外依赖）。

    返回结构（同时会被写入 intel_digests.payload）：
      {date, scope, days, totals, top[], by_symbol[], watch[], notes[]}
      · top[]      —— 必读清单（含 importance/tier/reasons/timing）
      · by_symbol[]—— 按标的分组的重要事件计数（用于「今天该盯哪几家」）
      · watch[]    —— 时机建议：只给有看多判定或有重大利好事件的标的
    """
    today = dt.date.today()
    with session_scope() as db:
        events = _candidate_events(db, days, symbol)
        syms = sorted({e["symbol"] for e in events})
        comps = {c.symbol: c for c in db.query(IntelCompany).filter(IntelCompany.symbol.in_(syms)).all()} if syms else {}
        latest: dict[str, IntelAnalysis] = {}
        for sym in syms:
            row = (
                db.query(IntelAnalysis).filter(IntelAnalysis.symbol == sym)
                .order_by(IntelAnalysis.created_at.desc()).first()
            )
            if row:
                latest[sym] = row
        latest_rec = {s: (a.recommendation, a.confidence, a.thesis, a.created_at.isoformat()) for s, a in latest.items()}

    scored: list[dict[str, Any]] = []
    for e in events:
        s = score_event(e, today=today)
        scored.append({**e, **s})

    top = _pick_top(_fold_families(list(scored)), top_n, per_symbol)

    # 按标的聚合：条数 + 最高重要度 + 多空净分
    by_symbol: dict[str, dict[str, Any]] = {}
    for it in scored:
        d = by_symbol.setdefault(it["symbol"], {
            "symbol": it["symbol"], "name": (comps.get(it["symbol"]).name if comps.get(it["symbol"]) else "") or "",
            "theme": (comps.get(it["symbol"]).theme if comps.get(it["symbol"]) else "") or "",
            "count": 0, "max_importance": 0.0, "positive": 0, "negative": 0, "high_impact": 0,
            "top_title": "", "top_importance": 0.0,
            # 用户硬要求：每条信息必须能对上具体日期 —— top 事件的发生日 + 精确时间
            "top_date": "", "top_at": "",
        })
        d["count"] += 1
        # 多空净分与「重大事件」计数只统计**公司自身事件**：评论/播报若计入，
        # 「该盯哪几家」会被媒体标题的数量与措辞带偏（评论类已封顶，进不了必读，
        # 但这里若不计入才与必读口径一致）。
        if not it["commentary"]:
            d["positive"] += 1 if it["sentiment"] == "positive" else 0
            d["negative"] += 1 if it["sentiment"] == "negative" else 0
            d["high_impact"] += 1 if it["impact"] >= _HIGH_IMPACT else 0
        if it["importance"] > d["top_importance"]:
            d["top_importance"] = it["importance"]
            d["top_title"] = it["title"]
            d["top_date"] = it.get("occurred_on") or ""
            d["top_at"] = it.get("occurred_at") or ""
        d["max_importance"] = max(d["max_importance"], it["importance"])
    sym_rows = sorted(by_symbol.values(), key=lambda x: (-x["max_importance"], -x["count"]))
    for d in sym_rows:
        rec = latest_rec.get(d["symbol"])
        d["recommendation"] = rec[0] if rec else None
        d["confidence"] = rec[1] if rec else None
        d["analysis_at"] = rec[3] if rec else None

    # 时机清单：有重大利好事件，或 AI 判定看多 —— 两者其一才值得给时机
    # 上限 8 家：每家要读一次量化快照（可能触发网络），必须限流，避免拖垮调度线程。
    watch: list[dict[str, Any]] = []
    for d in sym_rows[:20]:
        if len(watch) >= 8:
            break
        rec = d.get("recommendation")
        bull = rec in ("strong_buy", "buy")
        strong_pos = d["max_importance"] >= TIER_HIGH and d["positive"] > d["negative"]
        if not (bull or strong_pos):
            continue
        t = _timing_for(d["symbol"], rec)
        watch.append({
            "symbol": d["symbol"], "name": d["name"], "theme": d["theme"],
            "reason": ("AI 判定看多（%s）" % rec) if bull else "出现高重要度利好事件",
            "recommendation": rec, "confidence": d.get("confidence"),
            "importance": d["max_importance"],
            # 依据事件的日期与精确时间（top 事件）—— 用户硬要求：所有信息必须带日期
            "event_date": d.get("top_date") or "", "event_at": d.get("top_at") or "",
            **t,
        })

    def _ingested_today(x: dict[str, Any]) -> bool:
        ca = x.get("created_at")
        try:
            d = dt.datetime.fromisoformat(str(ca))
        except (TypeError, ValueError):
            return False
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone().date() == local_today

    local_today = dt.date.today()
    totals = {
        "events": len(scored),
        # 今日新增（按本地日历日的**入库时刻**）：让「系统在动」可见 ——
        # 就算 top 被窗口内高重要度事件占据，这个数字也每天在涨
        "today": sum(1 for x in scored if _ingested_today(x)),
        "critical": sum(1 for x in scored if x["tier"] == "critical"),
        "high": sum(1 for x in scored if x["tier"] == "high"),
        "positive": sum(1 for x in scored if x["sentiment"] == "positive"),
        "negative": sum(1 for x in scored if x["sentiment"] == "negative"),
        "symbols": len(by_symbol),
        "top": len(top),
    }
    notes: list[str] = []
    if not scored:
        notes.append(f"最近 {days} 天没有入库事件，无法生成必读清单。")
    elif not top:
        notes.append(f"最近 {days} 天有 {len(scored)} 条事件，但没有达到「必读」阈值的条目。")
    if any(x["age_days"] is None for x in top):
        notes.append("部分条目来源未提供事件日期，已按中性新鲜度处理（不臆造时间）。")
    if any("合成行情" in (w.get("note") or "") for w in watch):
        notes.append("部分标的只有合成行情（非真实数据），未给出价位区间 —— 不可据此决策。")
    notes.append("重要度由规则计算（影响度×新鲜度×类别×阶段×来源），不是投资建议；"
                 "交易动作仍需走 AI 提案 + 人工批准。")

    return {
        "date": today.isoformat(),
        "scope": symbol.upper() if symbol else "all",
        "days": days,
        "totals": totals,
        "top": top,
        "by_symbol": sym_rows,
        "watch": watch,
        "notes": notes,
    }


# ------------------------------------------------------------------
# 落库 / 读取
# ------------------------------------------------------------------
def save_digest(digest: dict[str, Any], *, llm_text: str = "", llm_engine: str = "",
                generated_by: str = "scheduler") -> int:
    """把清单 upsert 到 intel_digests（同日同 scope 覆盖）。返回行 id。"""
    date = str(digest.get("date") or dt.date.today().isoformat())[:10]
    scope = str(digest.get("scope") or "all")[:16]
    payload = json.dumps(digest, ensure_ascii=False, default=str)
    with session_scope() as db:
        row = (
            db.query(IntelDigest)
            .filter(IntelDigest.digest_date == date, IntelDigest.scope == scope)
            .first()
        )
        if row is None:
            row = IntelDigest(digest_date=date, scope=scope)
            db.add(row)
        row.payload = payload
        row.event_count = int((digest.get("totals") or {}).get("events") or 0)
        row.top_count = int((digest.get("totals") or {}).get("top") or 0)
        row.generated_by = generated_by[:32]
        if llm_text:
            row.llm_text = llm_text[:8000]
        if llm_engine:
            row.llm_engine = llm_engine[:16]
        row.updated_at = dt.datetime.now(dt.timezone.utc)
        db.flush()
        rid = row.id
    return rid


def load_digest(date: str | None = None, scope: str = "all") -> dict[str, Any] | None:
    """读取已落库的清单（默认今天；没有则返回 None，由调用方决定是否现算）。"""
    date = str(date or dt.date.today().isoformat())[:10]
    with session_scope() as db:
        row = (
            db.query(IntelDigest)
            .filter(IntelDigest.digest_date == date, IntelDigest.scope == scope)
            .first()
        )
        if row is None:
            return None
        try:
            payload = json.loads(row.payload or "{}")
        except json.JSONDecodeError:
            payload = {}
        return {
            "id": row.id, "digest_date": row.digest_date, "scope": row.scope,
            "payload": payload, "llm_text": row.llm_text, "llm_engine": row.llm_engine,
            "generated_by": row.generated_by, "event_count": row.event_count,
            "top_count": row.top_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def ensure_digest(date: str | None = None, days: int = DIGEST_DAYS,
                  force: bool = False, generated_by: str = "scheduler") -> dict[str, Any]:
    """取当日清单；不存在（或 force）则现算并落库。返回落库行 + payload。

    监控每轮调用 —— 纯规则计算，不调 LLM，成本可忽略。
    """
    existing = None if force else load_digest(date)
    if existing is not None:
        return existing
    payload = build_digest(days=days)
    save_digest(payload, generated_by=generated_by)
    return load_digest(payload["date"]) or {"payload": payload}


# ------------------------------------------------------------------
# 实时刷新：数据一到就更新每日必读（2026-09-29）
# ------------------------------------------------------------------
# 旧行为的根因：清单只在监控重 tick（interval_minutes 一轮）落库一次；
# 手动「立即抓取」/ Bridge Agent 提交的事件入库后没有任何触发点，
# GET /intel/digest 一直返回当天的旧行 —— 「跑了但没实时数据回来」。
# 现在双保险：
#   · add_events / add_analysis 入库新数据 → refresh_async() 后台立刻重算（并发合并）；
#   · GET /intel/digest → refresh_if_stale()：落库行落后于最新事件时同步重算（30s 节流）。
_refresh_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None
_refresh_pending = threading.Event()
_sync_rebuild_at = 0.0
_SYNC_REBUILD_MIN_GAP = 30.0   # 同步重算节流（秒）：批次进行中不让每次轮询都跑 5~8s 重算


def _aware_utc(x: dt.datetime | str | None) -> dt.datetime | None:
    """统一到 aware UTC（DB 读回的 naive 视为 UTC；isoformat 字符串直接解析）。"""
    if x is None:
        return None
    if isinstance(x, str):
        try:
            x = dt.datetime.fromisoformat(x)
        except ValueError:
            return None
    if x.tzinfo is None:
        return x.replace(tzinfo=dt.timezone.utc)
    return x


def newest_event_at() -> dt.datetime | None:
    """最新一条事件的入库时刻（空表返回 None）。表小，直接 max()。"""
    with session_scope() as db:
        row = (
            db.query(IntelEvent.created_at)
            .order_by(IntelEvent.created_at.desc(), IntelEvent.id.desc())
            .first()
        )
        return row[0] if row else None


def refresh_async(generated_by: str = "auto") -> None:
    """后台重算每日必读（纯规则、不调 LLM）。

    并发触发只合并：已有刷新线程在跑时仅置位 pending，它算完当前轮会再补算
    一次（拿到刚入库的数据），绝不堆积线程。绝不在 HTTP 请求线程里同步跑
    5~8s 的重算 —— 会拖死接口（铁律 9：长活不占请求线程）。
    """

    def _worker() -> None:
        while True:
            _refresh_pending.clear()
            try:
                payload = build_digest()
                save_digest(payload, generated_by=generated_by[:32])
                log.info("Intel 每日必读实时刷新（触发：%s）：必读 %s 条 / 候选 %s 条",
                         generated_by, (payload.get("totals") or {}).get("top"),
                         (payload.get("totals") or {}).get("events"))
            except Exception:  # noqa: BLE001 —— 刷新失败绝不影响数据入库
                log.exception("Intel 每日必读实时刷新失败")
                return
            if not _refresh_pending.is_set():
                return

    global _refresh_thread
    with _refresh_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            _refresh_pending.set()
            return
        _refresh_thread = threading.Thread(target=_worker, name="intel-digest-refresh", daemon=True)
        _refresh_thread.start()


def refresh_if_stale(row: dict[str, Any]) -> dict[str, Any]:
    """GET 兜底：落库清单落后于最新事件 → 同步重算（30s 节流，节流期内转后台）。

    正常路径下 refresh_async 已在数据入库后几秒内更新清单；这里兜住
    「后台刷新还没跑完就打开页面」的场景，保证打开即最新。节流期内不改数据
    只转后台 —— 避免「指定标的抓取批次进行中」每次轮询都触发 5~8s 重算。
    """
    global _sync_rebuild_at
    try:
        newest = _aware_utc(newest_event_at())
        updated = _aware_utc(row.get("updated_at"))
    except Exception:  # noqa: BLE001 —— 判定失败就按原样返回，绝不让 GET 变 500
        return row
    if newest is None or (updated is not None and newest <= updated):
        return row  # 已是最新（或库里还没有事件）
    now = time.time()
    if now - _sync_rebuild_at < _SYNC_REBUILD_MIN_GAP:
        refresh_async(generated_by="stale")
        return row
    _sync_rebuild_at = now
    try:
        days = int((row.get("payload") or {}).get("days") or DIGEST_DAYS)
        payload = build_digest(days=max(1, min(14, days)))
        save_digest(payload, generated_by="api")
        return load_digest(scope=str(row.get("scope") or "all")) or row
    except Exception:  # noqa: BLE001
        log.exception("Intel 每日必读过期重算失败")
        return row


# ------------------------------------------------------------------
# 供 LLM 任务使用的紧凑上下文
# ------------------------------------------------------------------
def digest_llm_context(digest: dict[str, Any], max_events: int = 14) -> dict[str, Any]:
    """把清单裁剪成适合进 prompt 的紧凑结构（省 token，不丢关键字段）。"""
    top = (digest.get("top") or [])[:max_events]
    return {
        "日期": digest.get("date"),
        "窗口天数": digest.get("days"),
        "统计": digest.get("totals"),
        "必读事件": [
            {
                "symbol": t.get("symbol"), "日期": t.get("occurred_on"),
                "类别": t.get("category"), "方向": t.get("sentiment"),
                "影响度": t.get("impact"), "阶段": t.get("stage") or "普通",
                "重要度": t.get("importance"), "标题": t.get("title"),
                "摘要": (t.get("summary") or "")[:200],
                "入选理由": t.get("reasons"),
            }
            for t in top
        ],
        "涉及标的": [
            {"symbol": s.get("symbol"), "主题": s.get("theme"), "事件数": s.get("count"),
             "高影响事件数": s.get("high_impact"), "多": s.get("positive"), "空": s.get("negative"),
             "最高重要度": s.get("max_importance"), "AI判定": s.get("recommendation"),
             "置信度": s.get("confidence")}
            for s in (digest.get("by_symbol") or [])[:10]
        ],
        "时机候选": [
            {"symbol": w.get("symbol"), "理由": w.get("reason"),
             "关注区间": [w.get("zone_low"), w.get("zone_high")],
             "触发条件": w.get("trigger"), "失效参考": w.get("invalidation"),
             "RSI14": w.get("rsi14"), "现价": w.get("price")}
            for w in (digest.get("watch") or [])[:6]
        ],
    }
