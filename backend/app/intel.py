"""
AI 情报中心（Intel Center）
===========================
把「互联网信息抓取 → 美股核心公司关键节点 → AI 买入建议」产品化为一条
可持续运行的流水线：

  A. 外部 AI Agent（WorkBuddy / Claude Code / Codex ...）
     通过 /api/intel/bridge/* 用 X-Intel-Token 领任务（poll / brief）、
     提交事件节点（events）与买入建议（analysis）。与交易账户完全隔离。
  B. 内置 LLM 自动分析（配置 QD_AI_BASE_URL + QD_AI_API_KEY 后自动启用）
     调度器每轮对「有新事件、且建议已过期」的公司自动做 LLM 分析。
  C. 本地量化引擎（零配置兜底）
     未配置 LLM 时完全基于行情数据给出建议，保证监控开启后始终有产出。

一键开启/截止：
  POST /api/intel/monitor/start  → 生成 IntelRun(running) + 启动调度线程
  POST /api/intel/monitor/stop   → 关闭线程 + run 置 finished + Markdown 报告落盘
服务重启后 monitor_enabled=true 自动恢复监控（resume_on_startup）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .config import RUNTIME_DIR, settings
from .database import session_scope
from .models import (
    IntelAnalysis,
    IntelBridgeLog,
    IntelCompany,
    IntelEvent,
    IntelRun,
    IntelSetting,
)

log = logging.getLogger("quantdesk.intel")

REPORT_DIR = RUNTIME_DIR / "intel" / "reports"

EVENT_CATEGORIES = {
    "model_release": "模型发布",
    "product_launch": "产品发布",
    "partnership": "合作/联盟",
    "earnings": "财报/业绩",
    "regulatory": "监管/政策",
    "personnel": "人事变动",
    "macro": "宏观/行业",
    "other": "其他",
}
# 前瞻管道阶段：财报滞后，用合同/订单管道前瞻未来 3-6 个月经营可见性
EVENT_STAGES = {
    "confirmed": "已敲定",
    "negotiating": "在谈",
    "rumor": "传闻",
}
SENTIMENTS = {"positive", "neutral", "negative"}
RECOMMENDATIONS = {"strong_buy", "buy", "hold", "reduce", "avoid"}
HORIZONS = {"intraday", "swing", "position"}
REC_CN = {
    "strong_buy": "强烈买入",
    "buy": "买入",
    "hold": "持有",
    "reduce": "减持",
    "avoid": "回避",
}

# 默认观察标的：美股核心公司（可增删，存 intel_companies）
DEFAULT_COMPANIES: list[dict[str, str]] = [
    {"symbol": "NVDA", "name": "NVIDIA", "theme": "AI 算力", "focus": "数据中心 GPU/Blackwell/Rubin 节奏、大厂资本开支、出口管制"},
    {"symbol": "MSFT", "name": "Microsoft", "theme": "AI 应用 + 云", "focus": "Azure 增速、Copilot 商业化、OpenAI 关系"},
    {"symbol": "GOOGL", "name": "Alphabet", "theme": "AI + 搜索 + 广告", "focus": "Gemini 迭代、TPU 自研、搜索份额、反垄断"},
    {"symbol": "AAPL", "name": "Apple", "theme": "消费电子 + AI", "focus": "iPhone 周期、Apple Intelligence、中国区销售"},
    {"symbol": "META", "name": "Meta Platforms", "theme": "AI + 社交广告", "focus": "Llama 开源策略、广告推荐效率、 Reality Labs 亏损"},
    {"symbol": "AMZN", "name": "Amazon", "theme": "云 + 电商 + 机器人", "focus": "AWS 增速与利润率、自研 Trainium、物流自动化"},
    {"symbol": "TSLA", "name": "Tesla", "theme": "自动驾驶 + 机器人", "focus": "FSD 进展、Robotaxi/Optimus 里程碑、交付量"},
    {"symbol": "AVGO", "name": "Broadcom", "theme": "AI ASIC + 网络", "focus": "定制 ASIC 客户、VMware 整合、网络芯片"},
    {"symbol": "AMD", "name": "AMD", "theme": "AI 芯片挑战者", "focus": "MI 系列放量、数据中心份额、CPU 竞争"},
    {"symbol": "NFLX", "name": "Netflix", "theme": "流媒体 + 广告", "focus": "订阅/广告层增长、内容投入、涨价节奏"},
    {"symbol": "ORCL", "name": "Oracle", "theme": "云数据库 + OCI", "focus": "OCI 增速、AI 合同积压、Stargate 进展"},
    {"symbol": "CRM", "name": "Salesforce", "theme": "企业软件 + Agent", "focus": "Agentforce 商业化、利润率改善"},
    {"symbol": "JPM", "name": "JPMorgan", "theme": "银行龙头", "focus": "净利息收入、资本市场回暖、信贷质量"},
    {"symbol": "V", "name": "Visa", "theme": "支付网络", "focus": "跨境交易量、稳定币威胁与机会"},
    {"symbol": "WMT", "name": "Walmart", "theme": "零售 + 广告", "focus": "电商增速、会员收入、自动化降本"},
    {"symbol": "COST", "name": "Costco", "theme": "会员制零售", "focus": "会员费提价、电商增长、同店销售"},
    {"symbol": "UNH", "name": "UnitedHealth", "theme": "医疗健康", "focus": "医保赔付率、Optum 增长、监管"},
    {"symbol": "LLY", "name": "Eli Lilly", "theme": "减肥药 + 创新药", "focus": "Zepbound/Mounjaro 放量、产能扩张、管线数据"},
    {"symbol": "XOM", "name": "ExxonMobil", "theme": "能源 + LNG", "focus": "产量指引、炼化利润率、资本回报"},
    {"symbol": "ASML", "name": "ASML", "theme": "光刻机垄断", "focus": "EUV 订单、High-NA 出货、中国区占比"},
]


# ==================================================================
# 设置与初始化
# ==================================================================
def ensure_settings() -> IntelSetting:
    """读取（并按需创建）单行设置；bridge_token 为空则生成。"""
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        if row is None:
            row = IntelSetting(id=1, bridge_token=_gen_token())
            db.add(row)
            db.flush()
        elif not row.bridge_token:
            row.bridge_token = _gen_token()
        if db.dirty:
            db.flush()  # autoflush=False：expunge 前必须先落库，否则修改被静默丢弃
        db.expunge(row)
        return row


def _gen_token() -> str:
    import secrets

    return "qdintel_" + secrets.token_hex(16)


def reset_bridge_token() -> str:
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        row.bridge_token = _gen_token()
        token = row.bridge_token
    log.info("Intel bridge token 已重置")
    return token


def save_settings(*, interval_minutes: int | None = None, auto_analyze: bool | None = None) -> IntelSetting:
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        if interval_minutes is not None:
            row.interval_minutes = max(5, min(720, int(interval_minutes)))
        if auto_analyze is not None:
            row.auto_analyze = bool(auto_analyze)
        if db.dirty:
            db.flush()  # autoflush=False：expunge 前必须先落库，否则修改被静默丢弃
        db.expunge(row)
        return row


def ensure_default_companies() -> None:
    """首次使用时灌入默认美股核心公司（已存在则跳过）。"""
    with session_scope() as db:
        existing = {c.symbol for c in db.query(IntelCompany).all()}
        for item in DEFAULT_COMPANIES:
            if item["symbol"] not in existing:
                db.add(IntelCompany(**item))


# ==================================================================
# 事件 / 建议入库（含去重）
# ==================================================================
def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (title or "").lower())[:60]


def make_dedupe_key(symbol: str, category: str, title: str) -> str:
    return hashlib.sha1(f"{symbol}|{category}|{_norm_title(title)}".encode()).hexdigest()[:40]


def add_events(items: list[dict[str, Any]], agent: str, run_id: int | None) -> dict[str, int]:
    """批量入库事件节点。返回 {inserted, duplicates, rejected}。"""
    inserted = duplicates = rejected = 0
    touched: set[str] = set()
    with session_scope() as db:
        for raw in items:
            try:
                symbol = str(raw.get("symbol", "")).strip().upper()[:32]
                title = str(raw.get("title", "")).strip()[:300]
                if not symbol or not title:
                    rejected += 1
                    continue
                category = str(raw.get("category", "other")).strip()
                if category not in EVENT_CATEGORIES:
                    category = "other"
                stage = str(raw.get("stage", "")).strip().lower()
                if stage not in EVENT_STAGES:
                    stage = ""
                sentiment = str(raw.get("sentiment", "neutral")).strip()
                if sentiment not in SENTIMENTS:
                    sentiment = "neutral"
                try:
                    impact = max(1, min(5, int(raw.get("impact") or 3)))
                except (TypeError, ValueError):
                    impact = 3
                occurred_on = str(raw.get("occurred_on") or raw.get("published_at") or "").strip()[:10]
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", occurred_on):
                    occurred_on = ""
                key = make_dedupe_key(symbol, category, title)
                if db.query(IntelEvent.id).filter(IntelEvent.dedupe_key == key).first():
                    duplicates += 1
                    continue
                # 未知标的：自动建档为未启用（不进入自动任务），由用户决定是否关注
                if not db.query(IntelCompany.id).filter(IntelCompany.symbol == symbol).first():
                    db.add(IntelCompany(symbol=symbol, name=str(raw.get("company_name", ""))[:120],
                                        enabled=False, note="由 AI Agent 提交事件时自动创建"))
                db.add(IntelEvent(
                    symbol=symbol, occurred_on=occurred_on, category=category,
                    title=title, summary=str(raw.get("summary", "")).strip()[:2000],
                    impact=impact, sentiment=sentiment, stage=stage,
                    source_name=str(raw.get("source_name", "")).strip()[:200],
                    source_url=str(raw.get("source_url", "")).strip()[:600],
                    dedupe_key=key, agent=agent, run_id=run_id,
                ))
                db.flush()  # 立即可见：同批重复项与后续唯一键检查都能命中
                touched.add(symbol)
                inserted += 1
            except Exception:  # noqa: BLE001 —— 单条失败不拖垮整批
                rejected += 1
        if run_id:
            run = db.get(IntelRun, run_id)
            if run:
                run.events_found = (run.events_found or 0) + inserted
                _seen_add(run, agent)
        for sym in touched:
            comp = db.query(IntelCompany).filter(IntelCompany.symbol == sym).first()
            if comp:
                comp.last_scrape_at = dt.datetime.now(dt.timezone.utc)
    return {"inserted": inserted, "duplicates": duplicates, "rejected": rejected}


def _seen_add(run: IntelRun, agent: str) -> None:
    try:
        seen = json.loads(run.agents_seen or "[]")
    except json.JSONDecodeError:
        seen = []
    if agent and agent not in seen:
        seen.append(agent)
        run.agents_seen = json.dumps(seen[:12], ensure_ascii=False)


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
        return row


def bridge_log(agent: str, action: str, detail: str = "", ok: bool = True) -> None:
    try:
        with session_scope() as db:
            db.add(IntelBridgeLog(agent=agent[:48] or "unknown", action=action,
                                  detail=str(detail)[:800], ok=ok))
    except Exception:  # noqa: BLE001
        pass


# ==================================================================
# 研究上下文（给 Agent 的简报 / 给 LLM 的 prompt）
# ==================================================================
def pending_tasks(db: Session, interval_minutes: int) -> list[dict[str, Any]]:
    """到期待抓取的公司：从未抓取，或上次抓取已超过 1.2 个周期。"""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=interval_minutes * 1.2)
    out: list[dict[str, Any]] = []
    for c in db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).all():
        # 历史缺陷：DB 里的 naive UTC 与 aware cutoff 直接比较会 TypeError——统一补 UTC 后再比
        last = c.last_scrape_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        if last is None or last < cutoff:
            out.append({
                "symbol": c.symbol, "name": c.name, "theme": c.theme, "focus": c.focus,
                "last_scrape_at": c.last_scrape_at.isoformat() if c.last_scrape_at else None,
                "due_reason": "never" if c.last_scrape_at is None else "stale",
            })
    return out


def company_brief(symbol: str) -> dict[str, Any]:
    """单公司研究简报：公司档案 + 实时量化快照摘要 + 近期事件 + 新闻标题。"""
    from .ai_analyst import market_snapshot
    from .data_provider import get_quote

    symbol = symbol.strip().upper()
    with session_scope() as db:
        comp = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()
        events = (
            db.query(IntelEvent).filter(IntelEvent.symbol == symbol)
            .order_by(IntelEvent.created_at.desc()).limit(30).all()
        )
        last_analysis = (
            db.query(IntelAnalysis).filter(IntelAnalysis.symbol == symbol)
            .order_by(IntelAnalysis.created_at.desc()).first()
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
        from .news import fetch_news

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
        "last_analysis": _analysis_row(last_analysis) if last_analysis else None,
        "news_headlines": news,
        "event_categories": EVENT_CATEGORIES,
        "recommendation_options": sorted(RECOMMENDATIONS),
        "submitted_via": "POST /api/intel/bridge/events 与 POST /api/intel/bridge/analysis",
    }


def _event_row(e: IntelEvent) -> dict[str, Any]:
    return {
        "id": e.id, "symbol": e.symbol, "occurred_on": e.occurred_on, "category": e.category,
        "category_cn": EVENT_CATEGORIES.get(e.category, e.category),
        "title": e.title, "summary": e.summary, "impact": e.impact, "sentiment": e.sentiment,
        "source_name": e.source_name, "source_url": e.source_url, "agent": e.agent,
        "created_at": e.created_at.isoformat(),
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
        "outcome_hit": a.outcome_hit, "outcome_window_days": a.outcome_window_days,
        "created_at": a.created_at.isoformat(),
    }


# ==================================================================
# 自动分析（LLM 优先，本地量化兜底）
# ==================================================================
_LOCAL_REC_MAP = [(50, "strong_buy"), (20, "buy"), (-20, "hold"), (-50, "reduce"), (-999, "avoid")]

_EVENT_FACE_WEIGHT = 0.20   # 事件面在综合评分中的权重（本地引擎）
_EVENT_FACE_DAYS = 90       # 事件面回看窗口


def _event_face(symbol: str, days: int = _EVENT_FACE_DAYS) -> dict[str, Any]:
    """事件面评分：近期信息按「影响度 × 时间衰减」加权。

    每条事件权重 = (impact/5) × max(0.05, 1 - 距今天数/90)
    score = 100 × (利好权重和 − 利空权重和) / max(利好+利空, 0.5)   ∈ [-100, +100]
    中性事件只计数不参与分子；无利好/利空 → score=None。
    返回 {score, n, pos, neg, neu, top: [按权重排序的事件摘要], ids}
    """
    now = dt.datetime.now(dt.timezone.utc)
    with session_scope() as db:
        rows = (
            db.query(IntelEvent).filter(IntelEvent.symbol == symbol.upper())
            .order_by(IntelEvent.created_at.desc()).limit(40).all()
        )
        events = [
            {
                "id": e.id, "title": e.title, "category": e.category, "impact": e.impact,
                "sentiment": e.sentiment, "occurred_on": e.occurred_on,
                "created_at": e.created_at.isoformat() if e.created_at else "",
                "age_days": None,
            }
            for e in rows
        ]
    pos_w = neg_w = 0.0
    pos_n = neg_n = neu_n = 0
    for it in events:
        ref = it["occurred_on"] or (it.get("created_at") or "")
        try:
            d0 = dt.date.fromisoformat(str(ref)[:10])
            age = (now.date() - d0).days
        except (ValueError, TypeError):
            age = days  # 日期未知：按最远窗口计（最保守）
        it["age_days"] = age
        w = (it["impact"] / 5.0) * max(0.05, 1.0 - max(0, age) / days)
        if it["sentiment"] == "positive":
            pos_w += w
            pos_n += 1
        elif it["sentiment"] == "negative":
            neg_w += w
            neg_n += 1
        else:
            neu_n += 1
    score = round(100.0 * (pos_w - neg_w) / max(pos_w + neg_w, 0.5), 1) if (pos_w + neg_w) > 0 else None
    top = sorted(events, key=lambda x: -((x["impact"] / 5.0) * max(0.05, 1.0 - max(0, x["age_days"] or days) / days)))[:4]
    return {"score": score, "n": len(events), "pos": pos_n, "neg": neg_n, "neu": neu_n,
            "top": top, "ids": [t["id"] for t in top]}


def _rec_from_score(score: float) -> str:
    return next(r for th, r in _LOCAL_REC_MAP if score >= th)


def _local_analysis(symbol: str) -> dict[str, Any]:
    """零配置兜底：本地量化引擎 + 事件面加权（engine=local）。

    综合 = 0.8 × 量化评分 + 0.2 × 事件面评分 —— 保证建议随最近信息变化，
    而不是只看 K 线。thesis 明确写出依据的事件标题，可溯源。
    """
    from .ai_analyst import analyze_local, market_snapshot

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


def _llm_analysis(symbol: str) -> dict[str, Any]:
    """LLM 模式：事件面 + 量化快照 → 结构化 JSON 建议。失败返回 {}。"""
    import json as _json

    from .ai_analyst import _llm_call, ai_configured

    if not ai_configured():
        return {}
    brief = company_brief(symbol)
    event_ids = [e["id"] for e in brief["recent_events"][:20]]
    context = {
        "标的": symbol, "公司": brief["company"], "现价": brief["quote"],
        "量化快照": brief["snapshot"],
        "近期事件节点": brief["recent_events"][:20],
        "最近新闻标题": brief["news_headlines"][:8],
    }
    try:
        text = _llm_call(
            [{"role": "system", "content": _LLM_ANALYSIS_PROMPT},
             {"role": "user", "content": _json.dumps(context, ensure_ascii=False, default=str)[:12000]}],
            temperature=0.2, max_tokens=900,
        )
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}
        data = _json.loads(m.group(0))
        data["symbol"] = symbol
        if data.get("recommendation") not in RECOMMENDATIONS:
            return {}
        # 依据事件：模型给了就用（过滤为真实存在的 id），没给默认取最近 5 条
        raw_ids = data.get("based_on_events") or event_ids[:5]
        try:
            allowed = set(event_ids)
            data["based_on_events"] = [int(i) for i in raw_ids if int(i) in allowed][:10]
        except (TypeError, ValueError):
            data["based_on_events"] = event_ids[:5]
        data.setdefault("event_score", None)
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("Intel LLM 分析失败 %s: %s", symbol, exc)
        return {}


def auto_analyze_symbol(symbol: str, run_id: int | None) -> IntelAnalysis | None:
    """对公司做一次自动分析：LLM 优先，本地兜底，入库并返回。"""
    from .data_provider import get_quote

    data = _llm_analysis(symbol)
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
    """建议已过期的公司：无建议 / 建议早于最新事件 / 建议超过 1.5 周期。"""
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
                due.append((la, sym))       # 建议过期，轮询刷新
    due.sort()
    return [s for _, s in due[:limit]]


# ==================================================================
# 调度器
# ==================================================================
class IntelScheduler:
    """监控调度线程：轻 tick（20s 刷新报价/计数）+ 重 tick（按周期生成任务与自动分析）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heavy = 0.0

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def current_run(self, db: Session | None = None) -> IntelRun | None:
        own = db is None
        if own:
            from .database import SessionLocal

            db = SessionLocal()  # type: ignore[assignment]
        try:
            row = (
                db.query(IntelRun).filter(IntelRun.status == "running")  # type: ignore[union-attr]
                .order_by(IntelRun.id.desc()).first()
            )
            if row and own:
                db.expunge(row)  # type: ignore[union-attr]
            return row
        finally:
            if own:
                db.close()  # type: ignore[union-attr]

    def start(self, interval_minutes: int | None = None, auto_analyze: bool | None = None) -> int:
        """一键开启：创建 run + 启动线程。已在运行则返回现有 run_id。"""
        with self._lock:
            st = ensure_settings()
            if interval_minutes is not None:
                st = save_settings(interval_minutes=interval_minutes)
            if auto_analyze is not None:
                st = save_settings(auto_analyze=auto_analyze)
            cur = self.current_run()
            if self.alive:
                if cur:
                    return cur.id
                # 线程活着但 run 丢失（异常场景）：补建 run，绝不重复开线程
                with session_scope() as db:
                    run = IntelRun(interval_minutes=st.interval_minutes,
                                   auto_analyze=st.auto_analyze, note="run 丢失后补建")
                    db.add(run)
                    db.flush()
                    return run.id
            # 清理僵尸 running（服务重启残留）
            if cur:
                self._close_run(cur.id, status="stopped", note="服务重启前遗留批次，已自动关闭")
                cur = None
            with session_scope() as db:
                run = IntelRun(
                    interval_minutes=st.interval_minutes, auto_analyze=st.auto_analyze,
                    note="监控开启",
                )
                db.add(run)
                db.flush()
                run_id = run.id
            with session_scope() as db:
                row = db.get(IntelSetting, 1)
                row.monitor_enabled = True
            self._stop.clear()
            self._last_heavy = 0.0
            self._thread = threading.Thread(target=self._loop, name="intel-scheduler", daemon=True)
            self._thread.start()
            from .state import log as audit_log

            audit_log("intel_start", "INFO", f"AI 情报监控开启（run #{run_id}，周期 {st.interval_minutes} 分钟）")
            return run_id

    def stop(self) -> dict[str, Any]:
        """一键截止：停线程 + 关 run + 报告落盘。"""
        with self._lock:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=4)
            self._thread = None
            cur = self.current_run()
            result: dict[str, Any] = {"stopped": bool(cur)}
            if cur:
                self._close_run(cur.id, status="finished", note="手动截止")
                result["run_id"] = cur.id
                result["report_path"] = write_report(cur.id)
            with session_scope() as db:
                row = db.get(IntelSetting, 1)
                row.monitor_enabled = False
            from .state import log as audit_log

            audit_log("intel_stop", "INFO", "AI 情报监控截止，报告已归档")
            return result

    # ----------------------------------------------------------------
    def _close_run(self, run_id: int, *, status: str, note: str) -> None:
        with session_scope() as db:
            run = db.get(IntelRun, run_id)
            if run and run.status == "running":
                run.status = status
                run.ended_at = dt.datetime.now(dt.timezone.utc)
                run.note = note

    def _loop(self) -> None:
        st = ensure_settings()
        heavy_every = max(300, st.interval_minutes * 60)
        while not self._stop.wait(20):
            try:
                self._tick(heavy_every)
            except Exception:  # noqa: BLE001 —— 任何异常都不能杀死调度线程
                log.exception("Intel 调度 tick 异常")

    def _tick(self, heavy_every: float) -> None:
        run = self.current_run()
        if run is None:
            return
        run_id, interval = run.id, run.interval_minutes
        # 轻活：刷新观察标的报价（供简报与报告使用）
        try:
            from .data_provider import get_quotes

            with session_scope() as db:
                syms = [c.symbol for c in db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).all()]
            if syms:
                get_quotes(syms)
        except Exception:  # noqa: BLE001
            pass
        now = time.time()
        if now - self._last_heavy < heavy_every:
            with session_scope() as db:
                r = db.get(IntelRun, run_id)
                if r and r.status == "running":
                    r.tick_count = (r.tick_count or 0) + 1
                    r.last_tick_at = dt.datetime.now(dt.timezone.utc)
            return
        self._last_heavy = now
        st = ensure_settings()
        # 重活 1：任务整备（把到期公司标记为待抓取——由 bridge/poll 暴露给 Agent）
        with session_scope() as db:
            tasks = pending_tasks(db, st.interval_minutes)
            r = db.get(IntelRun, run_id)
            if r and r.status == "running":
                r.tick_count = (r.tick_count or 0) + 1
                r.last_tick_at = dt.datetime.now(dt.timezone.utc)
        # 重活 2：自动分析（LLM 优先 / 本地兜底），每轮最多 3 家，避免阻塞
        if st.auto_analyze:
            from .database import SessionLocal

            db2 = SessionLocal()
            try:
                due = analysis_due_symbols(db2, st.interval_minutes, limit=3)
            finally:
                db2.close()
            for sym in due:
                if self._stop.is_set():
                    break
                try:
                    row = auto_analyze_symbol(sym, run_id)
                    if row:
                        log.info("Intel 自动分析 %s → %s（%s）", sym, row.recommendation, row.engine)
                except Exception:  # noqa: BLE001
                    log.exception("Intel 自动分析失败 %s", sym)
        # 重活 3：建议验证对账（满 7 天的建议 vs 实际涨跌），每轮最多 8 条
        try:
            n = verify_due_analyses(limit=8)
            if n:
                log.info("Intel 到期建议验证 %s 条", n)
        except Exception:  # noqa: BLE001
            log.exception("Intel 建议验证失败")

    def status(self) -> dict[str, Any]:
        st = ensure_settings()
        cur = self.current_run()
        return {
            "scheduler_alive": self.alive,
            "monitor_enabled": bool(st.monitor_enabled),
            "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze),
            "current_run": _run_row(cur) if cur else None,
        }


def _run_row(r: IntelRun) -> dict[str, Any]:
    return {
        "id": r.id, "status": r.status, "interval_minutes": r.interval_minutes,
        "auto_analyze": bool(r.auto_analyze), "started_at": r.started_at.isoformat(),
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "tick_count": r.tick_count, "last_tick_at": r.last_tick_at.isoformat() if r.last_tick_at else None,
        "events_found": r.events_found, "analyses_done": r.analyses_done,
        "agents_seen": r.agents_seen, "note": r.note, "report_path": r.report_path,
    }


SCHEDULER = IntelScheduler()


def resume_on_startup() -> None:
    """服务启动：按持久化开关恢复监控；僵尸 running 批次自动收尾。"""
    try:
        ensure_default_companies()
        st = ensure_settings()
        cur = SCHEDULER.current_run()
        if cur and not SCHEDULER.alive:
            SCHEDULER._close_run(cur.id, status="stopped", note="服务重启，批次自动收尾")
        if st.monitor_enabled:
            run_id = SCHEDULER.start()
            log.info("Intel 监控已自恢复（run #%s）", run_id)
    except Exception:  # noqa: BLE001
        log.exception("Intel 监控自恢复失败")


# ==================================================================
# 报告落盘
# ==================================================================
def write_report(run_id: int) -> str:
    """把一次批次的全部节点 + 建议写成 Markdown 存档。返回文件路径。"""
    with session_scope() as db:
        run = db.get(IntelRun, run_id)
        if run is None:
            return ""
        events = (
            db.query(IntelEvent).filter(IntelEvent.run_id == run_id)
            .order_by(IntelEvent.created_at.desc()).all()
        )
        analyses = (
            db.query(IntelAnalysis).filter(IntelAnalysis.run_id == run_id)
            .order_by(IntelAnalysis.created_at.desc()).all()
        )
        companies = {c.symbol: c for c in db.query(IntelCompany).all()}
        path = _render_report(run, events, analyses, companies)
        run.report_path = path
    return path


def _render_report(run: IntelRun, events: list[IntelEvent], analyses: list[IntelAnalysis],
                   companies: dict[str, IntelCompany]) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = run.ended_at.strftime("%Y%m%d-%H%M%S") if run.ended_at else dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"run-{run.id}-{stamp}.md"
    lines: list[str] = []
    lines.append(f"# AI 情报批次报告 · Run #{run.id}")
    lines.append("")
    lines.append(f"- 运行窗口：{run.started_at:%Y-%m-%d %H:%M} UTC → {run.ended_at:%Y-%m-%d %H:%M} UTC" if run.ended_at
                 else f"- 开始：{run.started_at:%Y-%m-%d %H:%M} UTC（未截止）")
    lines.append(f"- 抓取周期：{run.interval_minutes} 分钟｜LLM 自动分析：{'开' if run.auto_analyze else '关'}")
    lines.append(f"- 事件节点：{len(events)} 条｜AI 建议：{len(analyses)} 条｜参与 Agent：{run.agents_seen}")
    lines.append("")
    by_symbol: dict[str, list[IntelEvent]] = {}
    for e in events:
        by_symbol.setdefault(e.symbol, []).append(e)
    lines.append("## 一、公司关键节点（事件时间线）")
    lines.append("")
    if not by_symbol:
        lines.append("（本批次未提交事件节点）")
    for sym in sorted(by_symbol, key=lambda s: -len(by_symbol[s])):
        c = companies.get(sym)
        lines.append(f"### {sym}（{c.name if c else ''}｜{c.theme if c else ''}）")
        lines.append("")
        for e in sorted(by_symbol[sym], key=lambda x: (x.occurred_on or "9999"), reverse=True):
            star = "★" * e.impact
            sent = {"positive": "🟢 利好", "negative": "🔴 利空", "neutral": "⚪ 中性"}.get(e.sentiment, e.sentiment)
            lines.append(
                f"- **{e.occurred_on or '日期未知'}｜{EVENT_CATEGORIES.get(e.category, e.category)}｜{sent}｜影响 {star}** — "
                f"{e.title}（来源：{e.source_name or '未知'}，提交：{e.agent}）"
            )
            if e.summary:
                lines.append(f"  - {e.summary}")
            if e.source_url:
                lines.append(f"  - 链接：{e.source_url}")
        lines.append("")
    lines.append("## 二、AI 买入建议")
    lines.append("")
    if not analyses:
        lines.append("（本批次未产出建议）")
    for a in analyses:
        c = companies.get(a.symbol)
        lines.append(f"### {a.symbol}（{c.name if c else ''}）— {REC_CN.get(a.recommendation, a.recommendation)}")
        lines.append("")
        lines.append(f"- 生成时间：{a.created_at:%Y-%m-%d %H:%M} UTC｜引擎：{a.engine}｜Agent：{a.agent}｜置信度：{a.confidence:.0f}%")
        if a.price_at_analysis:
            lines.append(f"- 分析时价格：{a.price_at_analysis}｜建议仓位：{a.position_pct}%｜周期：{a.horizon}")
        if a.thesis:
            lines.append(f"- 论点：{a.thesis}")
        if a.catalysts:
            lines.append(f"- 催化剂：{a.catalysts}")
        if a.risks:
            lines.append(f"- 风险：{a.risks}")
        if a.invalidation:
            lines.append(f"- 失效条件：{a.invalidation}")
        lines.append("")
    lines.append("## 三、免责说明")
    lines.append("")
    lines.append("本报告由本地流水线归档：事件与建议来自 AI Agent 抓取/分析，仅供研究参考，不构成投资建议。")
    lines.append("数据可溯源性：每条事件带来源名称/链接，每条建议带引擎与 Agent 标注。")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ==================================================================
# 建议验证闭环：到期对账 → 每个 Agent 的胜率与校准
# ==================================================================
_VERIFY_TOLERANCE = 1.0   # ±1% 死区：区间收益落在死区视为"平"，不计命中


def _hit_for(recommendation: str, ret: float) -> bool | None:
    """方向对错判定：看多类涨才算对，看空类跌才算对；死区内为平(None)。"""
    if abs(ret) <= _VERIFY_TOLERANCE:
        return None
    bullish = recommendation in ("strong_buy", "buy")
    return (ret > 0) if bullish else (ret < 0)


def verify_due_analyses(limit: int = 8) -> int:
    """验证所有「满 7 天未对账」的建议，返回本次验证条数。

    取当前价（≈到期价）对比 price_at_analysis；hold 无方向，不验证。
    """
    from .data_provider import get_quote

    now = dt.datetime.now(dt.timezone.utc)
    verified = 0
    with session_scope() as db:
        due = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.outcome_checked_at.is_(None))
            .filter(IntelAnalysis.recommendation != "hold")
            .filter(IntelAnalysis.created_at <= now - dt.timedelta(days=7))
            .order_by(IntelAnalysis.created_at.asc())
            .limit(limit)
            .all()
        )
        pairs = []
        for a in due:
            q = get_quote(a.symbol)
            px = float((q or {}).get("price") or 0.0)
            if px <= 0 or a.price_at_analysis <= 0:
                continue
            ret = round((px / a.price_at_analysis - 1) * 100, 2)
            a.outcome_checked_at = now
            a.outcome_price = round(px, 4)
            a.outcome_return = ret
            a.outcome_hit = _hit_for(a.recommendation, ret)
            pairs.append((a.symbol, a.recommendation, ret, a.outcome_hit))
            verified += 1
    if verified:
        log.info("Intel 建议验证 %s 条: %s", verified, pairs)
    return verified


def verify_stats() -> dict[str, Any]:
    """按 Agent 聚合验证结果：胜率、平均实际收益、平均置信度（校准参考）。"""
    with session_scope() as db:
        rows = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.outcome_checked_at.is_(None) == False)  # noqa: E712
            .all()
        )
        pending = (
            db.query(IntelAnalysis).filter(IntelAnalysis.outcome_checked_at.is_(None))
            .filter(IntelAnalysis.recommendation != "hold")
            .filter(IntelAnalysis.created_at <= dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7))
            .count()
        )
        total = db.query(IntelAnalysis).count()
    by_agent: dict[str, dict[str, Any]] = {}
    for a in rows:
        if a.outcome_hit is None:
            continue  # 平局与 hold 不计入胜负
        d = by_agent.setdefault(a.agent or "unknown", {"n": 0, "hits": 0, "rets": [], "confs": []})
        d["n"] += 1
        d["hits"] += 1 if a.outcome_hit else 0
        d["rets"].append(a.outcome_return or 0.0)
        d["confs"].append(a.confidence)
    agents = []
    for agent, d in sorted(by_agent.items(), key=lambda kv: -kv[1]["n"]):
        agents.append({
            "agent": agent,
            "n": d["n"],
            "hits": d["hits"],
            "hit_rate": round(d["hits"] / d["n"] * 100, 1) if d["n"] else None,
            "avg_return": round(sum(d["rets"]) / len(d["rets"]), 2) if d["rets"] else None,
            "avg_confidence": round(sum(d["confs"]) / len(d["confs"]), 1) if d["confs"] else None,
        })
    all_rets = [(a.outcome_return or 0.0) for a in rows if a.outcome_hit is not None]
    return {
        "verified_total": len(rows),
        "pending": pending,
        "analyses_total": total,
        "agents": agents,
        "global_hit_rate": (
            round(sum(1 for a in rows if a.outcome_hit) / len(all_rets) * 100, 1) if all_rets else None
        ),
        "tolerance_pct": _VERIFY_TOLERANCE,
        "window_days": 7,
    }


# ==================================================================
# Bridge 接入指南
# ==================================================================
def bridge_base_url() -> str:
    host = "127.0.0.1" if settings.host in ("0.0.0.0", "127.0.0.1") else settings.host
    return f"http://{host}:{settings.port}"


def bridge_guide() -> dict[str, Any]:
    st = ensure_settings()
    base = bridge_base_url()
    token = st.bridge_token
    common = (
        f"接口约定：\n"
        f"  · 所有请求带 header：X-Intel-Token: {token}\n"
        f"  · 领任务：GET {base}/api/intel/bridge/poll?agent=<你的名字>\n"
        f"  · 公司简报：GET {base}/api/intel/bridge/brief/<SYMBOL>\n"
        f"  · 提交事件：POST {base}/api/intel/bridge/events\n"
        f"  · 提供建议：POST {base}/api/intel/bridge/analysis\n"
        f"  · 收工确认：POST {base}/api/intel/bridge/done\n"
    )
    prompts = {
        "workbuddy": (
            f"请作为 QuantDesk 的外部情报 Agent（在所有提交中把 agent 参数填为：workbuddy）执行一轮情报抓取。\n{common}\n"
            "【执行步骤】\n"
            "1. GET /api/intel/bridge/poll?agent=workbuddy 获取待抓取公司列表；\n"
            "2. 对每家公司联网检索最近 90 天的关键节点（产品发布/重大合同签约/财报/监管/人事）；\n"
            "3. 每条节点 POST /api/intel/bridge/events 提交，字段要求：\n"
            "   · symbol、occurred_on（YYYY-MM-DD，事件发生日，必填）、category、title、summary\n"
            "   · source_name + source_url（必须真实可访问，禁止编造）\n"
            "   · stage（前瞻管道阶段）：confirmed=已公告签约/落地，negotiating=官方口径在谈/磋商，rumor=媒体传闻未证实，普通事件留空\n"
            "   · sentiment（positive/neutral/negative）与 impact（1-5 星）\n"
            "4. GET /api/intel/bridge/brief/<SYMBOL> 取简报，结合事件面与量化快照，POST /api/intel/bridge/analysis 提交建议：\n"
            "   recommendation（strong_buy/buy/hold/reduce/avoid）、confidence 0-100、thesis、catalysts、risks、position_pct 0-20、invalidation\n"
            "5. 全部完成后 POST /api/intel/bridge/done。\n"
            "【质量红线】只提交有真实来源的信息；区分『已敲定事实』与『在谈/传闻』，不要把传闻标成 confirmed。"
        ),
        "claude_code": (
            f"用 curl 与 QuantDesk 情报桥接完成一轮抓取（提交时 agent 参数填：claude-code）。\n{common}\n"
            f"示例：curl -s -H \"X-Intel-Token: {token}\" \"{base}/api/intel/bridge/poll?agent=claude-code\"\n"
            "【执行步骤】\n"
            "1. poll 获取 tasks（每家含 symbol 与抓取原因）；\n"
            "2. 逐家联网检索最近 90 天关键节点；\n"
            "3. POST /events 提交事件——字段：symbol、occurred_on（YYYY-MM-DD 必填）、category、title、summary、"
            "source_name/source_url（真实链接）、stage（confirmed=已敲定/negotiating=在谈/rumor=传闻，普通事件留空）、sentiment、impact 1-5；\n"
            "4. GET /bridge/brief/<SYMBOL> 后 POST /analysis 提交建议（recommendation/confidence/thesis/catalysts/risks/position_pct/invalidation）；\n"
            "5. POST /done 收工。"
        ),
        "codex": (
            f"执行 QuantDesk 情报抓取任务（提交时 agent 参数填：codex）。\n{common}\n"
            f"curl -s -H \"X-Intel-Token: {token}\" \"{base}/api/intel/bridge/poll?agent=codex\"\n"
            "【流程】poll → 逐家联网调研（近 90 天：产品/合同签约/财报/监管/人事）→ POST /events → "
            "GET /bridge/brief/<SYMBOL> → POST /analysis → POST /done。\n"
            "【事件字段】symbol、occurred_on（YYYY-MM-DD 必填）、category、title、summary、source_name/source_url（真实链接）、"
            "stage（confirmed=已敲定/negotiating=在谈/rumor=传闻/空=普通事件）、sentiment、impact 1-5。\n"
            "【红线】信息必须带真实来源；区分事实与传闻；禁止编造。"
        ),
    }
    return {
        "base_url": base,
        "token": token,
        "token_header": "X-Intel-Token",
        "endpoints": {
            "poll": f"{base}/api/intel/bridge/poll",
            "brief": f"{base}/api/intel/bridge/brief/{{symbol}}",
            "events": f"{base}/api/intel/bridge/events",
            "analysis": f"{base}/api/intel/bridge/analysis",
            "done": f"{base}/api/intel/bridge/done",
        },
        "prompts": prompts,
        "event_categories": EVENT_CATEGORIES,
        "recommendation_options": sorted(RECOMMENDATIONS),
        "security_note": "Bridge 与交易账户完全隔离：只能读写情报数据，无法下单、无法访问持仓与密钥。token 可随时在页面重置。",
    }


def timeline(symbol: str, days: int = 180) -> dict[str, Any]:
    """公司时间线：过去 N 天事件（含前瞻管道）+ 最新 AI 建议 + 行情摘要。

    「财报是滞后指标」——用已敲定合同/在谈订单管道前瞻未来 3-6 个月经营。
    """
    symbol = symbol.strip().upper()
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with session_scope() as db:
        evs = (
            db.query(IntelEvent)
            .filter(IntelEvent.symbol == symbol, IntelEvent.occurred_on >= cutoff)
            .order_by(IntelEvent.occurred_on.desc(), IntelEvent.id.desc())
            .limit(120)
            .all()
        )
        ana = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.symbol == symbol)
            .order_by(IntelAnalysis.id.desc())
            .first()
        )
        comp = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()

    def _ev(e: IntelEvent) -> dict[str, Any]:
        return {
            "id": e.id, "occurred_on": e.occurred_on, "category": e.category,
            "category_cn": EVENT_CATEGORIES.get(e.category, e.category),
            "title": e.title, "summary": e.summary, "impact": e.impact,
            "sentiment": e.sentiment, "stage": e.stage,
            "stage_cn": EVENT_STAGES.get(e.stage, "") if e.stage else "",
            "source_name": e.source_name, "source_url": e.source_url,
            "agent": e.agent,
        }

    events = [_ev(e) for e in evs]
    pipeline = {
        st: sum(1 for x in events if x["stage"] == st) for st in EVENT_STAGES
    }
    pos = sum(1 for x in events if x["sentiment"] == "positive")
    neg = sum(1 for x in events if x["sentiment"] == "negative")
    # 前瞻可见性评分：已敲定=+2/条（封顶 20），在谈=+1/条（封顶 10），负面事件 -2（封顶 -12）
    visibility = min(20, pipeline.get("confirmed", 0) * 2) + min(10, pipeline.get("negotiating", 0)) \
        - min(12, neg * 2)

    quote = {}
    try:
        from .data_provider import get_quote

        quote = get_quote(symbol) or {}
    except Exception:  # noqa: BLE001
        pass

    return {
        "symbol": symbol,
        "name": (comp.name if comp else "") or "",
        "enabled": bool(comp.enabled) if comp else False,
        "days": days,
        "events": events,
        "counts": {
            "total": len(events),
            "positive": pos,
            "negative": neg,
            "neutral": len(events) - pos - neg,
            **pipeline,
        },
        "pipeline": pipeline,                       # confirmed/negotiating/rumor 计数
        "visibility_score": visibility,             # 经营可见性评分（前瞻）
        "latest_analysis": {
            "recommendation": ana.recommendation,
            "recommendation_cn": REC_CN.get(ana.recommendation, ana.recommendation),
            "confidence": ana.confidence,
            "thesis": ana.thesis,
            "catalysts": ana.catalysts,
            "risks": ana.risks,
            "position_pct": ana.position_pct,
            "horizon": ana.horizon,
            "event_score": ana.event_score,
            "agent": ana.agent,
            "created_at": ana.created_at.isoformat() if ana.created_at else "",
        } if ana else None,
        "quote": quote,
    }
