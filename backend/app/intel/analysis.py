"""intel 自动分析（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

建议入库（add_analysis）、研究上下文（company_brief/_agent_track/_earnings_date）、
LLM 分析（_llm_analysis + critic 二段式）、本地兜底（_local_analysis）。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session

from ..database import session_scope
from .common import (
    EVENT_CATEGORIES,
    HORIZONS,
    REC_CN,
    RECOMMENDATIONS,
    IntelAnalysis,
    IntelCompany,
    IntelEvent,
    IntelRun,
    log,
)
from .events import _event_row, _seen_add
from .timeline import (
    _EVENT_FACE_DAYS,
    _EVENT_FACE_WEIGHT,
    _event_face,
    _rec_from_score,
    _vol_position_scale,
)
from .verify import _brier


def add_analysis(item: dict[str, Any], agent: str, engine: str, run_id: int | None,
                 price: float = 0.0) -> IntelAnalysis:
    rec = str(item.get("recommendation", "hold")).strip().lower().replace("-", "_")
    # 外部 agent 常用大写/连字符（BUY / STRONG-BUY）——归一化到集合口径，而不是静默回落 hold
    if rec not in RECOMMENDATIONS:
        rec = "hold"
    horizon = str(item.get("horizon", "swing")).strip()
    if horizon not in HORIZONS:
        horizon = "swing"
    try:
        confidence = max(0.0, min(100.0, float(item.get("confidence") or 50)))
    except (TypeError, ValueError):
        confidence = 50.0
    try:
        position = max(0.0, min(100.0, float(item.get("position_pct") or 0)))
    except (TypeError, ValueError):
        position = 0.0
    symbol = str(item.get("symbol", "")).strip().upper()[:32]
    raw_based = item.get("based_on_events") or []
    try:
        based = json.dumps([int(i) for i in raw_based][:12])
    except (TypeError, ValueError):
        based = "[]"
    try:
        event_score = item.get("event_score")
        event_score = None if event_score is None else round(max(-100.0, min(100.0, float(event_score))), 1)
    except (TypeError, ValueError):
        event_score = None
    with session_scope() as db:
        row = IntelAnalysis(
            symbol=symbol, run_id=run_id, recommendation=rec, confidence=round(confidence, 1),
            thesis=str(item.get("thesis", "")).strip()[:4000],
            catalysts=str(item.get("catalysts", "")).strip()[:2000],
            risks=str(item.get("risks", "")).strip()[:2000],
            position_pct=round(position, 2),
            invalidation=str(item.get("invalidation", "")).strip()[:2000],
            price_at_analysis=round(float(price or 0.0), 4), horizon=horizon,
            based_on_events=based, event_score=event_score,
            agent=agent, engine=engine,
        )
        db.add(row)
        db.flush()
        if run_id:
            run = db.get(IntelRun, run_id)
            if run:
                run.analyses_done = (run.analyses_done or 0) + 1
                _seen_add(run, agent)
        db.expunge(row)
    # 新建议落库（session 已 commit）→ 实时刷新每日必读的「AI 判定」列。
    # 放在 with 块外：后台重算的 session 必须能读到刚提交的这行，避免竞态漏刷。
    try:
        from .. import intel_digest

        intel_digest.refresh_async("analysis")
    except Exception:  # noqa: BLE001
        pass
    return row



_earnings_cache: dict[str, tuple[float, str]] = {}
_EARNINGS_TTL_OK = 7 * 86400
_EARNINGS_TTL_FAIL = 6 * 3600


def _earnings_date(symbol: str) -> str | None:
    """下次财报日（YYYY-MM-DD）。取不到返回 None，绝不抛出、绝不阻塞主流程。"""
    key = (symbol or "").strip().upper()
    if not key:
        return None
    now_ts = time.time()
    hit = _earnings_cache.get(key)
    if hit and now_ts - hit[0] < (_EARNINGS_TTL_OK if hit[1] else _EARNINGS_TTL_FAIL):
        return hit[1] or None
    out = ""
    try:
        import yfinance as yf

        cal = yf.Ticker(key).calendar
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            d0 = ed[0] if isinstance(ed, (list, tuple)) else ed
            out = str(d0)[:10] if d0 else ""
    except Exception:  # noqa: BLE001 —— 财报日历是锦上添花，失败不阻塞
        out = ""
    _earnings_cache[key] = (now_ts, out)
    return out or None


def _agent_track(agent: str) -> dict[str, Any] | None:
    """该 Agent 的历史战绩（喂回 prompt 做自校准）。样本 <5 条不喂，防误导。"""
    with session_scope() as db:
        rows = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.agent == agent)
            .filter(IntelAnalysis.outcome_hit.isnot(None))
            .all()
        )
    if len(rows) < 5:
        return None
    n = len(rows)
    hits = sum(1 for a in rows if a.outcome_hit)
    confs = [a.confidence for a in rows]
    pairs = [(a.confidence, bool(a.outcome_hit)) for a in rows]
    return {
        "n": n,
        "hit_rate": round(hits / n * 100, 1),
        "avg_confidence": round(sum(confs) / n, 1),
        "brier": _brier(pairs),
        "note": "胜率低于 55% 时请下调置信度并在 risks 中说明不确定性",
    }


def company_brief(symbol: str) -> dict[str, Any]:
    """单公司研究简报：公司档案 + 实时量化快照摘要 + 近期事件 + 新闻标题。"""
    from ..ai_analyst import market_snapshot
    from ..data_provider import get_quote

    symbol = symbol.strip().upper()
    with session_scope() as db:
        comp = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()
        events = (
            db.query(IntelEvent).filter(IntelEvent.symbol == symbol)
            # 按事件发生时间倒序：已知日期优先（日期未知排最后），同日按时刻，
            # 完全无时间的退回入库时间——保证时间轴顺序与实际发生顺序一致
            .order_by(
                case((IntelEvent.occurred_on != "", 0), else_=1),
                IntelEvent.occurred_on.desc(),
                IntelEvent.occurred_at.desc(),
                IntelEvent.created_at.desc(),
            ).limit(30).all()
        )
        last_analyses = (
            db.query(IntelAnalysis).filter(IntelAnalysis.symbol == symbol)
            .order_by(IntelAnalysis.created_at.desc()).limit(3).all()
        )
    quote = get_quote(symbol)
    snap: dict[str, Any] = {}
    try:
        full = market_snapshot(symbol)
        snap = {
            "price": full.get("price"), "as_of": full.get("last_date"), "source": full.get("source"),
            "returns": full.get("returns"), "dist": full.get("dist"),
            "regime_hint": {
                "rsi14": (full.get("indicators") or {}).get("rsi14"),
                "adx14": (full.get("indicators") or {}).get("adx14"),
                "rv20": (full.get("indicators") or {}).get("rv20"),
            },
            "levels": full.get("levels"),
        }
    except Exception as exc:  # noqa: BLE001
        snap = {"error": f"{type(exc).__name__}: {exc}"[:120]}
    news: list[dict[str, str]] = []
    try:
        from ..news import fetch_news

        res = fetch_news(symbol, limit=8)
        news = [
            {"headline": it.get("headline", ""), "source": it.get("source", ""),
             "published_at": (it.get("published_at") or "")[:16]}
            for it in res.get("items", [])
        ]
    except Exception:  # noqa: BLE001
        pass
    return {
        "symbol": symbol,
        "company": {
            "name": comp.name if comp else "", "theme": comp.theme if comp else "",
            "focus": comp.focus if comp else "", "enabled": bool(comp.enabled) if comp else False,
        },
        "quote": {"price": quote.get("price"), "change_pct": quote.get("change_pct"),
                  "source": quote.get("source"), "ts": quote.get("ts")},
        "snapshot": snap,
        "recent_events": [_event_row(e) for e in events],
        "last_analysis": _analysis_row(last_analyses[0]) if last_analyses else None,
        # 近 3 条建议及其对账结果：让 LLM 显式「维持/修正」而不是每次独立重判
        "recent_analyses": [_analysis_row(a) for a in last_analyses],
        "earnings_date": _earnings_date(symbol),
        "news_headlines": news,
        "event_categories": EVENT_CATEGORIES,
        "recommendation_options": sorted(RECOMMENDATIONS),
        "submitted_via": "POST /api/intel/bridge/events 与 POST /api/intel/bridge/analysis",
    }



def _analysis_row(a: IntelAnalysis) -> dict[str, Any]:
    try:
        based = json.loads(a.based_on_events or "[]")
    except json.JSONDecodeError:
        based = []
    return {
        "id": a.id, "symbol": a.symbol, "recommendation": a.recommendation,
        "recommendation_cn": REC_CN.get(a.recommendation, a.recommendation),
        "confidence": a.confidence, "thesis": a.thesis, "catalysts": a.catalysts,
        "risks": a.risks, "position_pct": a.position_pct, "invalidation": a.invalidation,
        "price_at_analysis": a.price_at_analysis, "horizon": a.horizon, "agent": a.agent,
        "engine": a.engine, "based_on_events": based, "event_score": a.event_score,
        "outcome_checked_at": a.outcome_checked_at.isoformat() if a.outcome_checked_at else None,
        "outcome_price": a.outcome_price, "outcome_return": a.outcome_return,
        "outcome_benchmark": a.outcome_benchmark,
        "outcome_hit": a.outcome_hit, "outcome_window_days": a.outcome_window_days,
        "created_at": a.created_at.isoformat(),
    }



def _local_analysis(symbol: str) -> dict[str, Any]:
    """零配置兜底：本地量化引擎 + 事件面加权（engine=local）。

    综合 = 0.8 × 量化评分 + 0.2 × 事件面评分 —— 保证建议随最近信息变化，
    而不是只看 K 线。thesis 明确写出依据的事件标题，可溯源。
    """
    from ..ai_analyst import analyze_local, market_snapshot

    snap = market_snapshot(symbol)
    if snap.get("error"):
        return {}
    local = analyze_local(snap, "swing")
    q = local.get("composite_score", 0)
    face = _event_face(symbol)

    if face["score"] is not None:
        composite = (1 - _EVENT_FACE_WEIGHT) * q + _EVENT_FACE_WEIGHT * face["score"]
        face_txt = (f"事件面 {face['score']:+.0f}（近{_EVENT_FACE_DAYS}天 {face['n']} 条："
                    f"利好 {face['pos']} / 利空 {face['neg']} / 中性 {face['neu']}）")
    else:
        composite = q
        face_txt = "近 90 天无有效事件，仅按量化数据判断"
    composite = round(composite, 1)
    rec = _rec_from_score(composite)

    pos_titles = [t["title"] for t in face["top"] if t["sentiment"] == "positive"][:3]
    neg_titles = [t["title"] for t in face["top"] if t["sentiment"] == "negative"][:2]
    thesis = (
        f"量化综合 {q}（{local.get('bias')}，状态：{local.get('regime')}）；{face_txt}；"
        f"加权后综合 {composite} → {REC_CN[rec]}。"
        + (f"关键依据：{'；'.join(pos_titles)}" if pos_titles else "")
    )
    catalysts = "；".join(pos_titles) if pos_titles else \
        "；".join(m.get("name", "") for m in (local.get("strategy_matches") or [])[:3])
    risks = "；".join([*neg_titles, *local.get("warnings", [])[:3]])[:1500]

    sup = min(local["levels"]["支撑"] or [0])
    return {
        "symbol": symbol, "recommendation": rec,
        "confidence": local.get("confidence", 40),
        "thesis": thesis[:3900],
        "catalysts": catalysts[:1900],
        "risks": risks,
        "position_pct": local.get("suggested_position_pct", 0),
        "invalidation": f"综合评分跌破 {composite * 0.5:.0f}、跌破支撑 {sup}，或出现高影响利空事件",
        "horizon": "swing",
        "event_score": face["score"],
        "based_on_events": face["ids"],
    }



_LLM_ANALYSIS_PROMPT = """你是一名严谨的买方研究员。基于给定的公司事件节点与量化快照，输出买入建议。
只基于给定信息推理，不得编造事实；事件不足时降低置信度而不是臆测。
建议必须锚定「近期事件」：thesis 里至少引用 2 条具体事件标题，并给出这些事件如何影响判断的因果链。

校准要求：
· 若给了「该引擎历史战绩」且 hit_rate 低于 55%，置信度应低于其 avg_confidence，并在 risks 里说明历史偏差。
· 若给了「近期建议及结果」：上次方向与本次一致时说明为何维持；上次已证伪时必须解释新证据为何推翻旧结论。
· position_pct 参考 rv20（已实现波动率）：rv20 > 40% 时仓位减半；下次财报日在 horizon 窗口内时，thesis 必须说明是否愿意持有过财报。

严格只输出 JSON（不要 markdown 代码块）：
{"recommendation": "strong_buy|buy|hold|reduce|avoid",
 "confidence": 0-100,
 "thesis": "核心论点，须引用具体事件标题，150 字以内",
 "catalysts": "催化剂（事件/时点），分号分隔",
 "risks": "风险，分号分隔",
 "position_pct": 0-20 的建议仓位数字,
 "invalidation": "失效条件：什么情况下此判断作废",
 "based_on_events": [依据的事件 id 数组],
 "horizon": "swing"}
"""


_CRITIC_PROMPT = """你是苛刻的风控审查员。给定一份买入建议**草稿**和它的全部输入依据，逐项审查后输出修订后的最终建议。
审查清单：
1. 事实纪律：草稿是否把「传闻/在谈」（stage=rumor/negotiating）当成已敲定事实写进论点——是则降级表述或下调 confidence；
2. 置信度校准：若给了「该引擎历史战绩」且胜率不高，confidence 不得超过战绩能支持的水平；
3. 仓位纪律：position_pct 必须与 rv20（已实现波动率）匹配——rv20>40% 应减半，25~40% 应打折；
4. 失效条件：invalidation 必须具体可验证（含价位或事件条件），空泛套话一律重写；
5. 溯源：thesis 引用的事件必须真实存在于「近期事件节点」中，对应 id 写进 based_on_events。
严格只输出修订后的完整 JSON（字段结构与草稿完全一致，不要 markdown 代码块，不要解释文字）。
若草稿确无问题，原样输出草稿内容。"""



def _sanitize_analysis(data: dict[str, Any], event_ids: list[int]) -> dict[str, Any] | None:
    """清洗 LLM/复核输出的建议（纯函数）：方向合法、数值钳制、依据事件只留真实 id。"""
    if not isinstance(data, dict) or data.get("recommendation") not in RECOMMENDATIONS:
        return None
    try:
        data["confidence"] = float(min(100.0, max(0.0, float(data.get("confidence") or 50))))
    except (TypeError, ValueError):
        data["confidence"] = 50.0
    try:
        data["position_pct"] = float(min(20.0, max(0.0, float(data.get("position_pct") or 0))))
    except (TypeError, ValueError):
        data["position_pct"] = 0.0
    raw = data.get("based_on_events") or event_ids[:5]
    allowed = set(event_ids)
    try:
        data["based_on_events"] = [int(i) for i in raw if int(i) in allowed][:10]
    except (TypeError, ValueError):
        data["based_on_events"] = event_ids[:5]
    return data



def _llm_analysis(symbol: str, model_name: str = "") -> dict[str, Any]:
    """LLM 模式：事件面 + 量化快照 + 历史战绩 → 结构化 JSON 建议。失败返回 {}。"""
    import json as _json

    from ..ai_analyst import _llm_call, ai_configured

    if not ai_configured():
        return {}
    brief = company_brief(symbol)
    event_ids = [e["id"] for e in brief["recent_events"][:15]]
    track = _agent_track("local-llm")
    context = {
        "标的": symbol, "公司": brief["company"], "现价": brief["quote"],
        "量化快照": brief["snapshot"],
        "近期事件节点": brief["recent_events"][:15],
        "最近新闻标题": brief["news_headlines"][:6],
    }
    if brief.get("earnings_date"):
        context["下次财报日"] = brief["earnings_date"]
    if track:
        context["该引擎历史战绩"] = track
    recent = brief.get("recent_analyses") or []
    if recent:
        # 只喂决策相关字段（thesis/outcome），省 token
        context["近期建议及结果"] = [
            {"建议": a["recommendation"], "置信度": a["confidence"],
             "论点": (a.get("thesis") or "")[:150],
             "已对账": bool(a.get("outcome_checked_at")),
             "窗口收益%": a.get("outcome_return"),
             "超额收益%": (round(a["outcome_return"] - a["outcome_benchmark"], 2)
                           if a.get("outcome_return") is not None
                           and a.get("outcome_benchmark") is not None else None),
             "命中": a.get("outcome_hit")}
            for a in recent
        ]

    def _dump(ctx: dict) -> str:
        return _json.dumps(ctx, ensure_ascii=False, default=str)

    # 结构化裁剪：先丢快照里的大块次要字段，最后才硬截断（不再一刀切切坏 JSON）
    payload = _dump(context)
    if len(payload) > 13000:
        snap_ctx = context.get("量化快照") or {}
        snap_ctx.pop("levels", None)
        snap_ctx.pop("dist", None)
        payload = _dump(context)
    if len(payload) > 13000:
        context["近期事件节点"] = context["近期事件节点"][:8]
        payload = _dump(context)[:13000]
    try:
        text = _llm_call(
            [{"role": "system", "content": _LLM_ANALYSIS_PROMPT},
             {"role": "user", "content": payload}],
            temperature=0.2,
            # P0：推理型模型在长上下文下思维链膨胀到 4000+ tokens——实测 6402 input tokens
            # 时思维链 12530 字符，finish_reason=length、正文 0 字符、95.8s 白等（4096 也不够）。
            # reasoning_effort='low' 被网关透传并生效：思维链 4085→70 tokens，15.9s 出完整 JSON。
            # （thinking:{"type":"disabled"} 与 enable_thinking:false 均不被透传，勿再尝试。）
            max_tokens=2000, timeout=90, reasoning_effort="low",
            model_name=model_name,
        )
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}
        data = _sanitize_analysis(_json.loads(m.group(0)), event_ids)
        if data is None:
            return {}
        data["symbol"] = symbol

        # ---- critic 二段式：风控复核（失败/输出非法一律保留草稿，绝不阻塞）----
        try:
            ctext = _llm_call(
                [{"role": "system", "content": _CRITIC_PROMPT},
                 {"role": "user", "content": payload + "\n\n【建议草稿】\n"
                  + _dump({k: v for k, v in data.items() if k != "symbol"})}],
                temperature=0.1, max_tokens=2000, timeout=90, reasoning_effort="low",
                model_name=model_name,
            )
            cm = re.search(r"\{.*\}", ctext, re.S)
            if cm:
                revised = _json.loads(cm.group(0))
                revised.pop("symbol", None)
                merged = _sanitize_analysis({**data, **revised}, event_ids)
                if merged is not None:
                    # 复核只允许微调置信度（±25），防止第二遍把论点带飞
                    merged["confidence"] = min(
                        data["confidence"] + 25.0, max(data["confidence"] - 25.0, merged["confidence"]))
                    data = merged
        except Exception as exc:  # noqa: BLE001
            log.warning("Intel critic 复核失败 %s: %s（保留草稿）", symbol, exc)

        # 仓位与波动挂钩：LLM 自由填的 position_pct 必须过 rv20 缩放（高波减半）
        rv20 = ((brief.get("snapshot") or {}).get("regime_hint") or {}).get("rv20")
        data["position_pct"] = _vol_position_scale(data.get("position_pct"), rv20)
        data.setdefault("event_score", None)
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("Intel LLM 分析失败 %s: %s", symbol, exc)
        return {}


def auto_analyze_symbol(symbol: str, run_id: int | None, model_name: str = "") -> IntelAnalysis | None:
    """对公司做一次自动分析：LLM 优先，本地兜底，入库并返回。"""
    from ..data_provider import get_quote

    data = _llm_analysis(symbol, model_name=model_name)
    engine = "llm"
    if not data:
        data = _local_analysis(symbol)
        engine = "local"
    if not data:
        return None
    price = 0.0
    try:
        price = float((get_quote(symbol) or {}).get("price") or 0.0)
    except Exception:  # noqa: BLE001
        pass
    return add_analysis(data, agent="local-llm" if engine == "llm" else "local-engine",
                        engine=engine, run_id=run_id, price=price)


def analysis_due_symbols(db: Session, interval_minutes: int, limit: int = 3) -> list[str]:
    """建议已过期的公司：无建议 / 有新事件未消化 / 长期无事件例行刷新（3 倍周期）。"""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=interval_minutes * 1.5)
    syms = [c.symbol for c in db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).all()]
    due: list[tuple[dt.datetime, str]] = []
    for sym in syms:
        last_a = (
            db.query(IntelAnalysis).filter(IntelAnalysis.symbol == sym)
            .order_by(IntelAnalysis.created_at.desc()).first()
        )
        last_e = (
            db.query(IntelEvent).filter(IntelEvent.symbol == sym)
            .order_by(IntelEvent.created_at.desc()).first()
        )
        if last_a is None:
            due.append((dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc), sym))
        else:
            # SQLite 存 naive UTC——统一补 tz 再比较（naive/aware 混比会 TypeError）
            la = last_a.created_at if last_a.created_at.tzinfo else last_a.created_at.replace(tzinfo=dt.timezone.utc)
            le = last_e.created_at if (last_e and last_e.created_at.tzinfo) else (
                last_e.created_at.replace(tzinfo=dt.timezone.utc) if last_e else None)
            if le and le > la:
                due.append((la, sym))       # 有新事件未消化，优先
            elif la < cutoff:
                # 无新事件不例行重分析（省 LLM 调用）：超过 3 倍周期才例行刷新一次
                if la >= now - dt.timedelta(minutes=interval_minutes * 3):
                    continue
                due.append((la, sym))       # 长期无事件，低频例行刷新
    due.sort()
    return [s for _, s in due[:limit]]

