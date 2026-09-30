"""intel 抓取（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

内置 AI 自动抓取（多源新闻 → LLM 打标 → 入库 → bridge_log 台账）、
批次选取（scrape_batch 纯函数）。
防编造靠架构：occurred_on/source_name/source_url 由代码继承，LLM 只输出 idx+打标。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from typing import Any

from ..database import session_scope
from ..models import IntelRawNews
from .common import IntelCompany
from .bridge import bridge_log, pending_tasks
from .events import add_events
from .settings import ensure_settings
from .analysis import _analysis_row, auto_analyze_symbol

log = logging.getLogger("quantdesk.intel")


_BREAKER_THRESHOLD = 5      # 连续失败多少家触发熔断
_BREAKER_COOLDOWN_S = 15 * 60  # 熔断冷却 15 分钟
_BREAKER = {"consec_failures": 0, "open_until": 0.0, "last_trip_at": 0.0}

# Jobs 互斥（09-30 加）：监控 tick 与手动 ai-scrape 不并发 —— 否则两个进度条同时显示
# 用户反馈「监控自动抓 3 家 + 手动 4 家」时，看到 1/3 + 1/4 双条进度条，怀疑数据串了。
# 加锁后：手动在跑时监控 tick 检测到 → live phase='skipped' 并跳过本轮；前端 Hide LiveStatus。
_SCRAPE_LOCK = {"held_by": "", "since": 0.0}


def acquire_scrape_lock(holder: str, ttl_s: int = 600) -> bool:
    """尝试持有 jobs 锁。已被人持有且未过期 → 拒；过期可强抢（防止异常死亡锁死）。"""
    held_by = _SCRAPE_LOCK["held_by"]
    if held_by and held_by != holder and time.time() - _SCRAPE_LOCK["since"] < ttl_s:
        return False
    _SCRAPE_LOCK["held_by"] = holder
    _SCRAPE_LOCK["since"] = time.time()
    return True


def release_scrape_lock(holder: str) -> None:
    if _SCRAPE_LOCK["held_by"] == holder:
        _SCRAPE_LOCK["held_by"] = ""
        _SCRAPE_LOCK["since"] = 0.0


def scrape_lock_state() -> dict[str, Any]:
    held_by = _SCRAPE_LOCK["held_by"]
    since = _SCRAPE_LOCK["since"]
    return {
        "held_by": held_by,
        "since": since,
        "elapsed_s": (time.time() - since) if since else 0,
        "active": bool(held_by),
    }


def _breaker_open() -> bool:
    """熔断器是否开启（冷却期内跳过抓取）——09-30 加。

    触发条件：连续 ≥ `_BREAKER_THRESHOLD` 家抓取失败 → 开启 `_BREAKER_COOLDOWN_S` 秒。
    设计动机：网关/模型过载时监控每轮 23 家全失败 → 几分钟内 bridge_logs 涨几百条，
    既污染台账又烧监控线程。冷却期直接跳过抓取，留 brief 给用户做诊断。
    """
    return time.time() < _BREAKER["open_until"]


def _breaker_trip() -> None:
    """记录一次失败；达到阈值开熔断。"""
    _BREAKER["consec_failures"] += 1
    if _BREAKER["consec_failures"] >= _BREAKER_THRESHOLD and time.time() >= _BREAKER["open_until"]:
        _BREAKER["open_until"] = time.time() + _BREAKER_COOLDOWN_S
        _BREAKER["last_trip_at"] = _BREAKER["open_until"]
        log.warning(
            "AI 抓取熔断器开启：连续 %d 家失败 → 跳过 %d 分钟抓取（%s）",
            _BREAKER["consec_failures"], _BREAKER_COOLDOWN_S // 60, dt.datetime.now().isoformat(timespec="seconds"),
        )
        try:
            bridge_log(
                "builtin-ai", "breaker",
                f"熔断开启：连续 {_BREAKER['consec_failures']} 家失败（LLM 网关/模型过载），跳过 {_BREAKER_COOLDOWN_S // 60} 分钟",
                ok=False,
            )
        except Exception:  # noqa: BLE001
            pass


def _breaker_reset() -> None:
    """记录一次成功；若有失败累计则清零并落台账。"""
    if _BREAKER["consec_failures"] > 0 or _BREAKER["open_until"] > 0:
        prev_failures = _BREAKER["consec_failures"]
        was_open = time.time() < _BREAKER["open_until"]
        _BREAKER["consec_failures"] = 0
        _BREAKER["open_until"] = 0.0
        log.info("AI 抓取熔断器恢复（曾累计 %d 次失败%s）", prev_failures, "，含冷却期跳过" if was_open else "")
        try:
            bridge_log(
                "builtin-ai", "breaker",
                f"熔断恢复：曾累计 {prev_failures} 次失败" + ("（含冷却期跳过）" if was_open else ""),
                ok=True,
            )
        except Exception:  # noqa: BLE001
            pass


def breaker_status() -> dict[str, Any]:
    """给前端看的熔断状态快照。"""
    open_now = _breaker_open()
    return {
        "open": open_now,
        "consec_failures": _BREAKER["consec_failures"],
        "threshold": _BREAKER_THRESHOLD,
        "cooldown_remaining_s": max(0, int(_BREAKER["open_until"] - time.time())),
        "last_trip_at": _BREAKER["last_trip_at"],
    }


def _resolve_chain(model_name: str = "") -> list[str]:
    """解析模型 fallback 链（09-30 加）。

    优先级：
      1. 显式 `model_name` 非空 → 当作单档链（用户从下拉选了某模型时的语义）；
      2. 否则读 `intel_settings.llm_fallback_chain`（逗号分隔，存的是**完整优先级顺序**）；
      3. 仍空 → 返回空列表，调用方会用默认模型。

    设计动机：避免「一个模型挂 = 23 家全挂」。每家按链顺序逐档试，第一档
    返回空 / 抛异常 → 自动切下一档；全失败返回空文本 + errors 列表。
    """
    if model_name:
        return [m.strip() for m in model_name.split(",") if m.strip()] or [model_name]
    try:
        with session_scope() as db:
            st = ensure_settings()
            chain = (st.llm_fallback_chain or "").strip()
        if not chain:
            return []
        out = [m.strip() for m in chain.split(",") if m.strip()]
        return out[:5]   # 硬上限 5 档，防止误配 N 个把请求拖到分钟级
    except Exception:  # noqa: BLE001 —— 读取失败一律退化为空链
        return []


def _upsert_raw_news(db, symbol: str, items: list[dict[str, Any]], status: str) -> int:
    """把刚抓到的新闻条目**实时**写进 `intel_raw_news`（不依赖 LLM）。

    关键约束：UNIQUE(symbol, source_url)，同源同 URL 不重复。已有行更新
    `fetched_at` + `status`/`last_error`，新行 insert。
    返回实际写入/更新条数。
    """
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    n = 0
    for it in items:
        url = str(it.get("url") or "").strip()[:600]
        if not url:
            continue
        row = db.query(IntelRawNews).filter(
            IntelRawNews.symbol == symbol, IntelRawNews.source_url == url
        ).first()
        if row:
            row.fetched_at = now
            row.status = status
            row.last_error = ""
        else:
            db.add(IntelRawNews(
                symbol=symbol,
                published_at=str(it.get("published_at") or "")[:32],
                headline=str(it.get("headline") or "")[:300],
                summary=str(it.get("summary") or "")[:1000],
                source=str(it.get("source") or "")[:64],
                source_url=url,
                fetched_at=now,
                status=status,
            ))
        n += 1
    try:
        db.flush()
    except Exception:  # noqa: BLE001
        pass
    return n


def _mark_raw_news_status(db, symbol: str, from_status: str, to_status: str, err: str = "") -> int:
    """批量把某 symbol 下 status=from_status 的 raw_news 改成 to_status（写 last_error）。
    用于 LLM 失败后升级 pending → failed。"""
    rows = db.query(IntelRawNews).filter(
        IntelRawNews.symbol == symbol, IntelRawNews.status == from_status,
    ).all()
    for r in rows:
        r.status = to_status
        r.last_error = err[:200]
    try:
        db.flush()
    except Exception:  # noqa: BLE001
        pass
    return len(rows)


def _mark_raw_news_used(db, symbol: str, urls: list[str], event_id: int) -> int:
    """回填已入库事件的 raw_news（status=used + used_for_event_id=event_id）。
    urls 可能含空串——直接跳过。"""
    urls = [u for u in urls if u]
    if not urls:
        return 0
    rows = db.query(IntelRawNews).filter(
        IntelRawNews.symbol == symbol, IntelRawNews.source_url.in_(urls),
    ).all()
    for r in rows:
        r.status = "used"
        r.used_for_event_id = event_id
        r.last_error = ""
    try:
        db.flush()
    except Exception:  # noqa: BLE001
        pass
    return len(rows)


_EVENT_HARVEST_PROMPT = """你是买方研究员的信息整备助手。给定美股公司 {name}（{symbol}，关注点：{focus}）的最新新闻条目（带序号 idx），从中挑出对投资决策有意义的「公司关键节点」：

· 产品/模型发布、重大合同签约或合作、财报与业绩指引、监管/政策、人事变动、产能/供应链重大变化。
· 普通股价波动、每日涨跌评论、维持现有评级、纯行情播报类噪音不要输出。
· 严格基于新闻内容判断，不要编造新闻里没有的信息；不确定就降低 impact 或不输出。

对每条入选新闻输出（不要改写标题）：
- idx: 新闻序号（整数，必须来自给定列表，每条新闻最多用一次）
- summary: 一句话说明该节点的投资含义（60 字以内，必须基于该新闻内容）
- category: model_release|product_launch|partnership|earnings|regulatory|personnel|macro|other
- sentiment: positive|neutral|negative
- impact: 1-5（5 = 足以改变中期基本面判断；4 = 重大合同/指引调整；3 = 显著进展；2 = 有信息量；1 = 轻微）
  · 校准提醒：旗舰级产品/平台发布并已公告商用（尤其直接对标竞对核心业务、媒体广泛报道）、
    大额合同/订单/积压订单重大变化 → impact 4~5；仅小幅版本迭代、区域试点 → 2~3。
    2026-09-30 复盘：Oracle 旗舰 Agent 平台发布被只打 2★，当天股价大涨而情报面滞后 —— 宁可给足。
- stage: confirmed=新闻明确说已公告/签约/落地；negotiating=官方口径在谈/磋商；rumor=传闻未证实；普通事件留空字符串

严格只输出 JSON 数组（不要 markdown 代码块），格式示例：
[{{"idx":0,"summary":"...","category":"product_launch","sentiment":"positive","impact":4,"stage":"confirmed"}}]
没有关键节点就输出 []。"""


def ai_harvest_events(symbol: str, run_id: int | None = None, news_limit: int = 15,
                      model_name: str = "") -> dict[str, Any]:
    """内置 AI 抓取：多源新闻 → raw_news 实时入库 → LLM 链式 fallback 打标 → 事件入库。

    model_name：空 = 用 `intel_settings.llm_fallback_chain`（逗号分隔）；非空 = 该单值。
    「AI 立即抓取」的下拉若用户显式选了某模型 → 当作单档链使用，不读 settings。

    防编造设计（架构保证，不依赖 LLM 自觉）：
      · occurred_on / source_name / source_url 由代码从新闻条目直接继承，LLM 不接触来源字段；
      · title 直接用新闻原标题 —— 与 dedupe_key 归一化口径一致，同一新闻天然去重；
      · LLM 只输出 idx + 打标字段，idx 无法映射回新闻条目时丢弃该条。

    实时入库（09-30 增强）：
      · fetch_news 拿到的条目**立即** upsert 到 `intel_raw_news`（status=pending），
        不依赖 LLM 成败。失败重试端点可复用该缓存直接打标，省一次抓取。
      · LLM 链式 fallback（_llm_call_chain）：监hy4-perview → cn:glm-5.3-flash →
        deepseek4.1-flash。第一档模型空 / 抛错 → 自动切下一档，**一家失败不阻塞其他家**。

    无论本轮是否提取出事件都刷新 last_scrape_at：新闻全是噪音也视为「已抓过」，
    避免下一轮对同一家反复空抓。
    """
    from ..ai_analyst import ai_configured
    from ..ai_analyst_llm import _llm_call_chain  # 链式 fallback 实际函数在 ai_analyst_llm.py
    from ..news import fetch_news

    symbol = symbol.strip().upper()
    out: dict[str, Any] = {"symbol": symbol, "news_n": 0, "extracted": 0,
                           "inserted": 0, "duplicates": 0, "rejected": 0,
                           "llm_used": False, "model_used": ""}
    if not ai_configured():
        out["error"] = "AI 未配置"
        return out

    # 1. 多源新闻（force 绕过内存缓存 —— 「抓取」语义要求拿最新）
    try:
        res = fetch_news(symbol, limit=news_limit, force=True)
        items = res.get("items", [])
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"新闻抓取失败 {type(exc).__name__}: {exc}"[:160]
        items = []
    out["news_n"] = len(items)
    out["news_errors"] = res.get("errors", {}) if isinstance(res, dict) else {}
    if not items:
        _touch_scrape(symbol)
        return out

    # 2. 实时入库 raw_news（09-30 加）—— 不依赖 LLM 成败，新闻先入缓存再说。
    #    status="pending"：成功入库后会回填为 "used"；失败则保持 "pending" / 升级 "failed"。
    with session_scope() as db:
        _upsert_raw_news(db, symbol, items, status="pending")

    # 3. 准备 prompt（来源字段不进，token 省、编造无门）
    with session_scope() as db:
        comp = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()
        name = (comp.name if comp else "") or symbol
        focus = (comp.focus if comp else "") or "公司重大经营节点"
    lines = []
    for i, it in enumerate(items):
        summary = str(it.get("summary") or "")[:200]
        lines.append(
            f"idx={i} | {str(it.get('headline') or '')[:200]}"
            + (f" | 摘要：{summary}" if summary else "")
            + f" | 日期：{(it.get('published_at') or '')[:10]} | 来源：{it.get('source', '')}"
        )
    prompt = _EVENT_HARVEST_PROMPT.format(name=name, symbol=symbol, focus=focus[:200]) + "\n\n" + "\n".join(lines)
    msgs = [{"role": "user", "content": prompt[:14000]}]

    # 4. 解析模型链：显式 model_name 优先；否则读 intel_settings.llm_fallback_chain；再否则默认模型。
    chain = _resolve_chain(model_name)

    # 5. LLM 链式 fallback（每家独立）—— 解决「一个模型挂 = 23 家全挂」
    parsed: list[dict[str, Any]] = []
    res_call = _llm_call_chain(
        msgs, chain=chain, temperature=0.1, max_tokens=6144, timeout=180,
        reasoning_effort="low",
    )
    text = res_call["text"]
    out["model_used"] = res_call["model_used"]
    out["llm_errors"] = res_call["errors"]
    if not text:
        last = res_call["errors"][-1] if res_call["errors"] else "empty response"
        out["error"] = f"LLM 链式调用全失败（chain={chain}）：{last}"[:200]
        # 失败时升级 raw_news 状态为 failed，便于 retry 端点过滤
        with session_scope() as db:
            _mark_raw_news_status(db, symbol, "pending", "failed", last[:200])
    else:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            out["error"] = "LLM 返回内容中未找到 JSON 数组"
            with session_scope() as db:
                _mark_raw_news_status(db, symbol, "pending", "failed", "no json array")
        else:
            try:
                candidate = json.loads(m.group(0))
            except json.JSONDecodeError:
                candidate = None
                out["error"] = "LLM 返回 JSON 解析失败"
                with session_scope() as db:
                    _mark_raw_news_status(db, symbol, "pending", "failed", "json parse fail")
            if isinstance(candidate, list):
                parsed = [p for p in candidate if isinstance(p, dict)]
                out["llm_used"] = True
                out.pop("error", None)

    # 6. idx → 新闻条目回填，组装事件（来源字段全部继承，零编造）
    events: list[dict[str, Any]] = []
    used_idx: set[int] = set()
    for p in parsed:
        if not isinstance(p, dict):
            continue
        try:
            idx = int(p.get("idx"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(items)) or idx in used_idx:
            continue
        used_idx.add(idx)
        it = items[idx]
        summary = str(p.get("summary") or "").strip() or str(it.get("summary") or "")[:300]
        events.append({
            "symbol": symbol,
            "title": str(it.get("headline") or "").strip()[:300],
            "summary": summary[:2000],
            "category": str(p.get("category") or "other"),
            "sentiment": str(p.get("sentiment") or "neutral"),
            "impact": p.get("impact"),
            "stage": str(p.get("stage") or ""),
            "occurred_on": str(it.get("published_at") or "")[:10],
            "source_name": str(it.get("source") or "")[:200],
            "source_url": str(it.get("url") or "")[:600],
        })
    out["extracted"] = len(events)
    if events:
        res_ev = add_events(events, agent="builtin-ai", run_id=run_id)
        out.update({k: res_ev.get(k, 0) for k in ("inserted", "duplicates", "rejected")})
        # 入库成功的 raw_news 回填 used_for_event_id + status="used"
        if res_ev.get("inserted", 0) > 0:
            with session_scope() as db:
                _mark_raw_news_used(db, symbol, [items[i]["url"] for i in used_idx if items[i].get("url")], res_ev.get("inserted", 0))
        elif res_ev.get("duplicates", 0) > 0 or res_ev.get("rejected", 0) > 0:
            # 09-30 修复：LLM 成功但全部 dedupe 命中（无新事件）→ raw_news 也升级到 used，
            # 否则 retry 端点会把这批当作 pending 重试，重复烧 token。
            with session_scope() as db:
                _mark_raw_news_used(db, symbol, [items[i]["url"] for i in used_idx if items[i].get("url")], 0)
        # 09-30 修复：LLM 看过但没提取的那部分（绝大多数）也要标 used，否则一直 pending 触发 retry。
        # 取本次本家所有 fetched_at=now 附近的 pending → 升级 used（不与已升级行冲突，幂等）。
        if res_ev.get("inserted", 0) >= 0:  # 任意已处理分支
            with session_scope() as db:
                _mark_raw_news_status(db, symbol, "pending", "used", "")
                # 复用 _mark_raw_news_status 改 status；但要清 last_error 不留「失败」尾巴
                from datetime import timedelta as _td
                since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - _td(minutes=2)
                rows = db.query(IntelRawNews).filter(
                    IntelRawNews.symbol == symbol, IntelRawNews.status == "used",
                    IntelRawNews.fetched_at >= since,
                ).all()
                for r in rows:
                    r.last_error = ""
                    if r.used_for_event_id is None:
                        r.used_for_event_id = 0   # 0 = LLM 看过但未产出事件（区分真实入库）
    else:
        _touch_scrape(symbol)
    return out


def _touch_scrape(symbol: str) -> None:
    """刷新公司 last_scrape_at（空抓也要记，防止反复重抓）。"""
    try:
        with session_scope() as db:
            comp = db.query(IntelCompany).filter(IntelCompany.symbol == symbol.upper()).first()
            if comp:
                comp.last_scrape_at = dt.datetime.now(dt.timezone.utc)
    except Exception:  # noqa: BLE001
        pass


def scrape_batch(symbols: list[str] | None, pending: list[str], limit: int) -> list[str]:
    """决定本轮**实际抓取**的标的清单（纯函数，便于回归测试）。

    规则（顺序即抓取顺序）：
      · 显式传入 `symbols` → **它就是批次**，不再用 `limit` 截断。
        用户勾了 7 家却只跑 4 家是最容易被当成 bug 的行为（也确实曾是 bug：家数写死 4）。
      · 未传入 → 从 `pending`（到期待抓取清单）取；`limit <= 0` 表示全部。

    统一大写、去空格、保序去重；任一侧为空则结果为空（调用方据此提前返回）。
    """
    if symbols:
        src = symbols
    else:
        src = pending if limit <= 0 else pending[: max(1, limit)]
    out: list[str] = []
    for it in src:
        s = str(it or "").strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def ai_scrape_companies(symbols: list[str] | None = None, limit: int = 3,
                        with_analysis: bool = True, run_id: int | None = None,
                        model: str = "", progress_cb=None, cancel_event=None) -> list[dict[str, Any]]:
    """对一批公司执行 内置AI抓取（→ 可选立即分析）。

    symbols 为空时自动取「到期待抓取」的公司（与外部 Agent 的 poll 同一口径）。
    每家公司：1 次新闻聚合 + 1 次 LLM 结构化（+ 1 次 LLM/本地分析）。

    `symbols`：**显式传入时，这个清单本身就是批次** —— 不再被 `limit` 截断。
    用户勾了 7 家却只跑 4 家是最容易被当成 bug 的行为（也确实曾是 bug：家数写死 4）。
    只想跑一家就传一家（前端「指定标的」走这条路）。

    `limit`：仅在**未显式指定 symbols** 时生效 —— 正数 = 从待抓取清单里最多取几家；
    **<= 0 = 全部**（手动抓取允许一次跑完待抓取清单 —— 后台任务 + 协作式取消，
    前端会给出耗时预估）。调度器固定传 3，保持每轮小批量：单家要 1 次新闻聚合 +
    最多 2 次 LLM 调用，推理型模型每次先烧上千 token 思维链，33 家一轮会跑十几分钟
    并撞网关限流 —— 所以「自动轮转」与「手动一次跑完 / 手动挑几家」是两种场景。

    model：传给 LLM 的模型（空 = 默认）；progress_cb(done, total, note) 供后台任务
    上报进度；cancel_event 置位后当前公司跑完即停（协作式，不杀线程）。
    """
    from ..ai_analyst import ai_configured

    if not ai_configured():
        return []
    pending: list[str] = []
    if not symbols:
        with session_scope() as db:
            st = ensure_settings()
            pending = [t["symbol"] for t in pending_tasks(db, st.interval_minutes)]
    batch = scrape_batch(symbols, pending, limit)
    if not batch:
        return []
    out: list[dict[str, Any]] = []
    # 09-30：jobs 互斥 —— 监控 tick 与手动 ai-scrape 不能并发，否则两条进度条同时显示、
    # 写同一批台账还可能让前端事件重复。手动优先（用户主动操作让位监控）。
    holder = f"ai_scrape:{id(out)}"
    if not acquire_scrape_lock(holder):
        st = scrape_lock_state()
        log.info("AI 抓取跳过：jobs 锁已被 %s 持有（%.0fs）", st["held_by"] or "?", st["elapsed_s"])
        for sym in batch:
            out.append({
                "symbol": sym, "news_n": 0, "extracted": 0,
                "inserted": 0, "duplicates": 0, "rejected": 0,
                "llm_used": False, "model_used": "",
                "error": f"locked: jobs 被 {st['held_by']} 占用（监控让位手动）",
            })
        return out
    # 09-30：熔断器开启时整批跳过 —— 网关过载时不再污染台账（每家一条 fail 记录刷几百行）。
    if _breaker_open():
        st = breaker_status()
        log.warning("AI 抓取熔断中，跳过 %d 家（剩余 %ds）", len(batch), st["cooldown_remaining_s"])
        try:
            bridge_log(
                "builtin-ai", "breaker",
                f"熔断跳过本批：{len(batch)} 家 · 剩余 {st['cooldown_remaining_s'] // 60} 分 {st['cooldown_remaining_s'] % 60} 秒",
                ok=False,
            )
        except Exception:  # noqa: BLE001
            pass
        for sym in batch:
            out.append({
                "symbol": sym, "news_n": 0, "extracted": 0,
                "inserted": 0, "duplicates": 0, "rejected": 0,
                "llm_used": False, "model_used": "",
                "error": f"breaker_open: 熔断冷却中，剩余 {st['cooldown_remaining_s']}s",
            })
        release_scrape_lock(holder)
        return out
    try:
        for i, sym in enumerate(batch):
            if cancel_event is not None and cancel_event.is_set():
                break
            if progress_cb is not None:
                progress_cb(i, len(batch), f"正在抓取 {sym}（新闻 → LLM 提取 → 分析）…")
            if run_id is None:
                from .scheduler import SCHEDULER  # 延迟导入：scheduler 依赖 scrape，模块级会成环

                run = SCHEDULER.current_run()
                run_id_now = run.id if run else None
            else:
                run_id_now = run_id
            r = ai_harvest_events(sym, run_id=run_id_now, model_name=model)
            # 09-30：熔断计数 —— 成功归零 / 失败累加
            if r.get("error"):
                _breaker_trip()
            else:
                _breaker_reset()
            # 入库台账（bridge_log 落 intel_bridge_logs）：每家「进了什么数据」必须可查 ——
            # 「记录好那些数据入库了」的用户要求；事件 0 条 / 失败也要如实记，不许静默。
            # ok 按业务结果判定（09-30 修复）：inserted>0 且 LLM 成功 = true；其余 false。
            # 前端 IngestLog 用 ok 配色，全 True 全绿看不出失败家。
            try:
                bridge_log(
                    "builtin-ai", "scrape",
                    f"{sym} · 事件 +{r.get('inserted', 0)} / 重复 {r.get('duplicates', 0)}"
                    f" / 新闻 {r.get('news_n', 0)} 条 / 提取 {r.get('extracted', 0)} 条"
                    + (f" / 模型 {r.get('model_used', '')[:24]}" if r.get("model_used") else "")
                    + (f" · 失败：{str(r.get('error'))[:200]}" if r.get("error") else ""),
                    ok=(not r.get("error")) and r.get("inserted", 0) > 0,
                )
            except Exception:  # noqa: BLE001
                pass
            if with_analysis:
                try:
                    row = auto_analyze_symbol(sym, run_id_now, model_name=model)
                    r["analysis"] = _analysis_row(row) if row else None
                except Exception as exc:  # noqa: BLE001
                    r["analysis_error"] = f"{type(exc).__name__}: {exc}"[:160]
            out.append(r)
        if progress_cb is not None:
            progress_cb(len(out), len(batch), "抓取完成")
    finally:
        release_scrape_lock(holder)  # 09-30：异常路径也释放，避免死锁
    return out

