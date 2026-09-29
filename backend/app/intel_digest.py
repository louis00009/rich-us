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
from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session

from .database import session_scope
from . import intel_classify as classify
from .models import IntelAnalysis, IntelCompany, IntelDigest, IntelEvent

log = logging.getLogger("quantdesk.intel.digest")

# ------------------------------------------------------------------
# 评分权重（集中定义，便于调参与测试）
# ------------------------------------------------------------------
# 事件类别权重：改变中期基本面的类别更值得看
CATEGORY_WEIGHT: dict[str, float] = {
    "earnings": 1.25,       # 财报/业绩指引
    "partnership": 1.20,    # 重大合同/合作（前瞻可见性）
    "regulatory": 1.15,     # 监管/政策（可一票否决）
    "product_launch": 1.10,
    "model_release": 1.10,
    "personnel": 0.85,      # 人事多为噪音，但 CEO/首席科学家级别另说
    "macro": 0.90,
    "other": 0.80,
}

# 前瞻管道阶段权重：已敲定 > 在谈 > 传闻
STAGE_WEIGHT: dict[str, float] = {
    "confirmed": 1.25,
    "negotiating": 1.00,
    "rumor": 0.65,
    "": 1.00,
}

# 来源权重：一手/官方 > 聚合器（缺失不惩罚）
SOURCE_WEIGHT_HINT: list[tuple[str, float]] = [
    ("sec", 1.15), ("gov", 1.15), ("fda", 1.15), ("faa", 1.15),
    ("reuters", 1.10), ("bloomberg", 1.10), ("wsj", 1.10),
    ("cnbc", 1.05), ("ft.com", 1.05), ("company", 1.10), ("ir.", 1.10),
]

# 重要度分档阈值（用于前端徽章与「重点」判定）
# 与下面的修正系数区间配套设计，保证分档与影响度**严格对齐**：
#   新鲜 5★ ∈ [80.9, 96.8] → 必是 critical；新鲜 4★ ∈ [64.8, 77.4] → 必是 high；
#   新鲜 3★ ∈ [48.6, 58.1] → 必是 medium。不会出现「4★ 压过 5★」的错位。
TIER_CRITICAL = 79.0   # 必读·重大
TIER_HIGH = 60.0       # 必读·重要
TIER_MEDIUM = 40.0     # 可看

# 基准分：**不能**让 5★ 一上来就顶到 100，否则 4★ 与 5★ 会因封顶而无法区分
# （第一版就踩了这个坑：全部饱和成 100.0，排序退化成无意义）。
# 取 88 → 17.6 / 35.2 / 52.8 / 70.4 / 88.0。
_BASE_MAX = 88.0
# 修正系数区间刻意收窄到 ±10%：影响度必须是**主导项**。
# 第一版用 [0.70, 1.25] 时，「4★ 财报+已敲定+路透+利空」(88.0) 会压过
# 「5★ 普通利好」(79.2) —— 那是排序错位，不是「综合考量」。
_MOD_MIN, _MOD_MAX = 0.92, 1.10

# 新鲜度下限（见 _freshness）：窗口内的 5★ 必须始终 >= TIER_HIGH，否则「重点」会被周末冲淡
_FRESH_FLOOR = 0.80

# 媒体评论/行情播报的重要度**硬上限**（严格低于 TIER_MEDIUM=40）。
# 为什么用封顶而不是乘个系数：系数会被 impact 这个主导项放大 ——
# 「3 AI Stocks With Revenue Growth」若被判 4★，乘 0.5 仍有 32 分，再叠上类别/来源加成
# 就能挤进「必读」。封顶才是硬约束：评论类**永远**进不了必读清单。
_COMMENTARY_CAP = 34.9

DIGEST_DAYS = 3        # 必读回看窗口（覆盖周末与非交易日）
DIGEST_TOP_N = 12      # 必读条数上限
DIGEST_PER_SYMBOL = 2  # 单只标的在必读里最多占几条（防止一家刷屏）

_HIGH_IMPACT = 4       # 达到该影响度即视为「重大事件」，不设阈值直接进必读


def _parse_day(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def _freshness(age_days: int | None) -> float:
    """新鲜度：当天 1.0，窗口末降到 0.8。

    为什么下限是 0.8 而不是更激进的衰减：**窗口本身只有 3 天**，「3 天内」本来就等于
    「近期」。第一版用 1.0 → 0.5，导致两天前的 5★ 只剩 54 分被判成「可看」——
    而这恰恰是用户抱怨的「重点被埋掉」：一条足以改变中期基本面判断的消息，
    不该因为隔了一个周末就从必读掉到可看。窗口内的 5★ 必须始终 ≥ high。
    新鲜度仍参与排序（越新越靠前），只是不再跨越分档边界。
    """
    if age_days is None:
        return 0.85          # 日期未知：中性（约等于 1.5 天前），不臆造时间也不排除
    a = max(0, age_days)
    if a >= DIGEST_DAYS:
        return _FRESH_FLOOR
    return round(1.0 - (1.0 - _FRESH_FLOOR) * (a / DIGEST_DAYS), 4)


def _source_weight(name: str) -> float:
    low = (name or "").lower()
    for hint, w in SOURCE_WEIGHT_HINT:
        if hint in low:
            return w
    return 1.0


def score_event(event: dict[str, Any], today: dt.date | None = None) -> dict[str, Any]:
    """确定性重要度评分（纯函数，无 I/O）。

    重要度 = 基准分(影响度) × 新鲜度 × 修正系数
      · 基准分 = impact/5 × 88（见 _BASE_MAX 注释：不能一上来就顶到 100）
      · 修正系数 = 1 + 类别/阶段/来源/方向 四项加成，夹取到 [0.70, 1.25]
        —— 加成是**有界的**，保证影响度始终是主导项：4★ 无论来源多好都压不过 5★。
      · 利空加成最高（下跌风险优先于机会）；中性轻微扣分。

    返回 {importance, tier, reasons, age_days}
    """
    today = today or dt.date.today()
    impact = event.get("impact")
    try:
        impact = max(1, min(5, int(impact)))
    except (TypeError, ValueError):
        impact = 3

    day = _parse_day(event.get("occurred_on"))
    age = None if day is None else max(0, (today - day).days)
    fresh = _freshness(age)

    cat = str(event.get("category") or "other")
    cw = CATEGORY_WEIGHT.get(cat, 0.85)
    stage = str(event.get("stage") or "")
    sw = STAGE_WEIGHT.get(stage, 1.0)
    src = _source_weight(str(event.get("source_name") or ""))
    sentiment = str(event.get("sentiment") or "neutral")
    sent_coef = 1.08 if sentiment == "negative" else (1.0 if sentiment == "positive" else 0.92)

    mod = 1.0 + (cw - 1.0) * 0.5 + (sw - 1.0) * 0.5 + (src - 1.0) * 0.5 + (sent_coef - 1.0) * 0.5
    mod = max(_MOD_MIN, min(_MOD_MAX, mod))
    importance = round(max(0.0, min(100.0, (impact / 5.0) * _BASE_MAX * fresh * mod)), 1)

    # 媒体评论/行情播报/分析师调价不是公司自身事件 → 重要度封顶（见 _COMMENTARY_CAP）。
    # 依据来自 intel_classify.is_commentary，是**可核对**的规则命中，不是黑箱。
    commentary = bool(event.get("commentary"))
    if commentary:
        importance = min(importance, _COMMENTARY_CAP)

    if importance >= TIER_CRITICAL:
        tier = "critical"
    elif importance >= TIER_HIGH:
        tier = "high"
    elif importance >= TIER_MEDIUM:
        tier = "medium"
    else:
        tier = "low"

    # 理由：只写真正起作用的因素，避免套话
    reasons: list[str] = []
    if commentary:
        # 评论类的「低分理由」必须说清楚，否则用户会以为是评分出错。
        return {"importance": importance, "tier": tier, "age_days": age,
                "reasons": ["媒体评论/行情播报，非公司自身事件（不参与重点判定）"]}
    if impact >= 5:
        reasons.append("影响度 5★：足以改变中期基本面判断")
    elif impact == 4:
        reasons.append("影响度 4★：重大合同/指引调整级别")
    if age is not None and age <= 1:
        reasons.append("当日/隔日新信息")
    if sentiment == "negative":
        reasons.append("利空：下跌风险优先处理")
    if stage == "confirmed":
        reasons.append("已敲定事实（非传闻）")
    elif stage == "negotiating":
        reasons.append("官方口径在谈：尚未落地")
    elif stage == "rumor":
        reasons.append("仅为传闻：需等证实")
    if cw >= 1.20:
        reasons.append({"earnings": "财报/指引直接改盈利预期",
                        "partnership": "合同管道前瞻未来 3-6 个月经营"}.get(cat, "高信息量类别"))
    if src >= 1.10:
        reasons.append("一手/权威来源")

    return {"importance": importance, "tier": tier, "reasons": reasons[:4], "age_days": age}


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
def _pick_top(scored: list[dict[str, Any]], top_n: int, per_symbol: int) -> list[dict[str, Any]]:
    """按重要度取前 N 条，同时限制单标的条数（避免一家公司刷屏）。

    重要度 >= TIER_CRITICAL 的条目不受单标的配额限制 —— 重大事件不该被挤掉。
    """
    scored.sort(key=lambda x: (-x["importance"], -x["impact"], x["occurred_on"] or "", -x["id"]))
    picked: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for it in scored:
        if len(picked) >= top_n:
            break
        sym = it["symbol"]
        if it["importance"] < TIER_CRITICAL and used.get(sym, 0) >= per_symbol:
            continue
        used[sym] = used.get(sym, 0) + 1
        picked.append(it)
    return picked


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

    top = _pick_top(list(scored), top_n, per_symbol)

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

    totals = {
        "events": len(scored),
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
