"""
AI 情报中心（Intel Center）
===========================
把「互联网信息抓取 → 美股核心公司关键节点 → AI 买入建议」产品化为一条
可持续运行的流水线：

  B. 内置 AI 全自动管道（配置 AI 后无需任何外部 Agent，默认开启）
     调度器每轮对到期公司执行：多源新闻抓取（finnhub/yahoo-rss/ibkr）→ LLM 把新闻
     结构化为「公司关键节点」事件入库 → 结合事件面与量化快照产出买入建议。
     来源真实性由架构保证：occurred_on/source_name/source_url 一律继承新闻条目，
     LLM 只做挑选与打标，不触碰来源字段（杜绝编造链接）。
  C. 本地量化引擎（零配置兜底）
     未配置 LLM 时完全基于行情数据给出建议，保证监控开启后始终有产出。
  D. 外部 AI Agent（WorkBuddy / Claude Code / Codex ...）
     通过 /api/intel/bridge/* 用 X-Intel-Token 领任务（poll / brief）、
     提交事件节点（events）与买入建议（analysis）。与交易账户完全隔离，
     定位为「能联网深度搜索」的增强通道。

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

from sqlalchemy import case
from sqlalchemy.orm import Session

from .config import RUNTIME_DIR, settings
from .database import session_scope
from . import intel_classify as classify
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


def save_settings(*, interval_minutes: int | None = None, auto_analyze: bool | None = None,
                  ai_scrape: bool | None = None) -> IntelSetting:
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        if interval_minutes is not None:
            row.interval_minutes = max(5, min(720, int(interval_minutes)))
        if auto_analyze is not None:
            row.auto_analyze = bool(auto_analyze)
        if ai_scrape is not None:
            row.ai_scrape = bool(ai_scrape)
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


def _norm_event_time(raw: str) -> str:
    """归一化事件发生时刻为 'YYYY-MM-DD HH:MM'（原样保留来源时区，通常是 UTC）。

    只接受带日期 + 时分的可解析串（ISO / 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD HH:MM:SS'）；
    解析失败返回空串——宁可不显示，也不臆造一个时间。
    """
    s = (raw or "").strip().replace("T", " ")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ ](\d{2}:\d{2})", s)
    if not m:
        return ""
    return f"{m.group(1)} {m.group(2)}"


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
                # 归一化：提交方留空 / 给了 other 时用确定性规则补 category 与 stage。
                # ⚠️ 必须在算 dedupe_key **之前** —— key 含 category，顺序错了会让
                # 「同一事件重复提交」漏判成两条。详见 intel_classify 模块 docstring。
                normalized = classify.normalize_event(
                    {"title": title, "summary": raw.get("summary"), "category": category, "stage": stage}
                )
                category = normalized["category"]
                stage = normalized["stage"]
                sentiment = str(raw.get("sentiment", "neutral")).strip()
                if sentiment not in SENTIMENTS:
                    sentiment = "neutral"
                try:
                    impact = max(1, min(5, int(raw.get("impact") or 3)))
                except (TypeError, ValueError):
                    impact = 3
                raw_at = str(raw.get("occurred_at") or raw.get("published_at") or "").strip()
                occurred_on = str(raw.get("occurred_on") or "").strip()[:10] or raw_at[:10]
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", occurred_on):
                    occurred_on = ""
                occurred_at = _norm_event_time(raw_at)
                # 时刻缺失但日期已知：不臆造时间，留空由前端只显示日期
                if occurred_at and occurred_on and occurred_at[:10] != occurred_on:
                    occurred_at = ""
                key = make_dedupe_key(symbol, category, title)
                if db.query(IntelEvent.id).filter(IntelEvent.dedupe_key == key).first():
                    duplicates += 1
                    continue
                # 未知标的：自动建档为未启用（不进入自动任务），由用户决定是否关注
                if not db.query(IntelCompany.id).filter(IntelCompany.symbol == symbol).first():
                    db.add(IntelCompany(symbol=symbol, name=str(raw.get("company_name", ""))[:120],
                                        enabled=False, note="由 AI Agent 提交事件时自动创建"))
                db.add(IntelEvent(
                    symbol=symbol, occurred_on=occurred_on, occurred_at=occurred_at, category=category,
                    title=title, summary=str(raw.get("summary", "")).strip()[:2000],
                    impact=impact, sentiment=sentiment, stage=stage,
                    source_name=str(raw.get("source_name", "")).strip()[:200],
                    source_url=str(raw.get("source_url", "")).strip()[:600],
                    dedupe_key=key, agent=agent, run_id=run_id,
                ))
                db.flush()  # 立即可见：同批重复项与后续唯一键检查都能命中
                touched.add(symbol)
                inserted += 1
            except Exception as exc:  # noqa: BLE001 —— 单条失败不拖垮整批
                # 记录原因：静默吞异常会让「提交成功但 0 入库」无法定位
                logging.getLogger("quantdesk.intel").warning(
                    "事件入库失败 symbol=%s title=%s: %s: %s",
                    raw.get("symbol"), str(raw.get("title"))[:40], type(exc).__name__, exc)
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


# ------------------------------------------------------------------
# 下次财报日（yfinance calendar，单标的内存缓存 7 天 / 失败 6 小时重试）
# ------------------------------------------------------------------
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
    from .ai_analyst import market_snapshot
    from .data_provider import get_quote

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
        "last_analysis": _analysis_row(last_analyses[0]) if last_analyses else None,
        # 近 3 条建议及其对账结果：让 LLM 显式「维持/修正」而不是每次独立重判
        "recent_analyses": [_analysis_row(a) for a in last_analyses],
        "earnings_date": _earnings_date(symbol),
        "news_headlines": news,
        "event_categories": EVENT_CATEGORIES,
        "recommendation_options": sorted(RECOMMENDATIONS),
        "submitted_via": "POST /api/intel/bridge/events 与 POST /api/intel/bridge/analysis",
    }


def _event_row(e: IntelEvent) -> dict[str, Any]:
    return {
        "id": e.id, "symbol": e.symbol, "occurred_on": e.occurred_on, "occurred_at": e.occurred_at or "",
        "category": e.category,
        "category_cn": EVENT_CATEGORIES.get(e.category, e.category),
        "title": e.title, "summary": e.summary, "impact": e.impact, "sentiment": e.sentiment,
        "source_name": e.source_name, "source_url": e.source_url, "agent": e.agent,
        # 媒体评论/行情播报/分析师动作（规则判定，非公司自身事件）——
        # 前端据此把这类条目降级展示，避免把噪音和真实催化剂混在一起。
        "commentary": classify.is_commentary(e.title or ""),
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
        "outcome_benchmark": a.outcome_benchmark,
        "outcome_hit": a.outcome_hit, "outcome_window_days": a.outcome_window_days,
        "created_at": a.created_at.isoformat(),
    }


# ==================================================================
# 内置 AI 自动抓取：多源新闻 → LLM 结构化关键节点 → 事件入库
# ==================================================================
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
- stage: confirmed=新闻明确说已公告/签约/落地；negotiating=官方口径在谈/磋商；rumor=传闻未证实；普通事件留空字符串

严格只输出 JSON 数组（不要 markdown 代码块），格式示例：
[{{"idx":0,"summary":"...","category":"product_launch","sentiment":"positive","impact":4,"stage":"confirmed"}}]
没有关键节点就输出 []。"""


def ai_harvest_events(symbol: str, run_id: int | None = None, news_limit: int = 15,
                      model_name: str = "") -> dict[str, Any]:
    """内置 AI 抓取：多源新闻 → LLM 挑选+打标关键节点 → 事件入库。

    model_name：空 = 设置页默认模型；非空 = QD_AI_EXTRA_MODELS 别名或网关模型 id
    （解析见 ai_analyst._llm_config_for）——「AI 立即抓取」的模型下拉即用此通道。

    防编造设计（架构保证，不依赖 LLM 自觉）：
      · occurred_on / source_name / source_url 由代码从新闻条目直接继承，LLM 不接触来源字段；
      · title 直接用新闻原标题 —— 与 dedupe_key 归一化口径一致，同一新闻天然去重；
      · LLM 只输出 idx + 打标字段，idx 无法映射回新闻条目时丢弃该条。

    无论本轮是否提取出事件都刷新 last_scrape_at：新闻全是噪音也视为「已抓过」，
    避免下一轮对同一家反复空抓。
    """
    from .ai_analyst import _llm_call, ai_configured
    from .news import fetch_news

    symbol = symbol.strip().upper()
    out: dict[str, Any] = {"symbol": symbol, "news_n": 0, "extracted": 0,
                           "inserted": 0, "duplicates": 0, "rejected": 0, "llm_used": False}
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

    # 2. LLM 挑选 + 打标（来源字段不进 prompt，token 省、编造无门）
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
    parsed: list[dict[str, Any]] = []
    # 推理型模型（glm 一类）思维链固定先烧 1800~3200 token（ai_tasks.py 实测结论）：
    # max_tokens 下限 6144、上限也是 6144（8192 会让网关失败）；timeout 180s；空返回补试一次。
    msgs = [{"role": "user", "content": prompt[:14000]}]
    try:
        t0 = time.monotonic()
        # reasoning_effort='low'：压缩思维链（长上下文下思维链可膨胀至 4000+ token，
        # 实测会把 6144 预算烧光、finish=length、正文 0 字符）——见 _llm_analysis 同款修复。
        text = (_llm_call(msgs, temperature=0.1, max_tokens=6144, timeout=180,
                          reasoning_effort="low", model_name=model_name) or "").strip()
        if not text and time.monotonic() - t0 < 60:
            text = (_llm_call(msgs, temperature=0.1, max_tokens=6144, timeout=180,
                              reasoning_effort="low", model_name=model_name) or "").strip()
        if not text:
            out["error"] = "LLM 返回空内容（思维链耗尽 token 预算，补试后仍为空）"
        else:
            m = re.search(r"\[.*\]", text, re.S)
            if not m:
                out["error"] = "LLM 返回内容中未找到 JSON 数组"
            else:
                try:
                    candidate = json.loads(m.group(0))
                except json.JSONDecodeError:
                    candidate = None
                    out["error"] = "LLM 返回 JSON 解析失败"
                if isinstance(candidate, list):
                    parsed = [p for p in candidate if isinstance(p, dict)]
                    out["llm_used"] = True
                    out.pop("error", None)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"LLM 结构化失败 {type(exc).__name__}: {exc}"[:160]

    # 3. idx → 新闻条目回填，组装事件（来源字段全部继承，零编造）
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
    from .ai_analyst import ai_configured

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
    for i, sym in enumerate(batch):
        if cancel_event is not None and cancel_event.is_set():
            break
        if progress_cb is not None:
            progress_cb(i, len(batch), f"正在抓取 {sym}（新闻 → LLM 提取 → 分析）…")
        if run_id is None:
            run = SCHEDULER.current_run()
            run_id_now = run.id if run else None
        else:
            run_id_now = run_id
        r = ai_harvest_events(sym, run_id=run_id_now, model_name=model)
        if with_analysis:
            try:
                row = auto_analyze_symbol(sym, run_id_now, model_name=model)
                r["analysis"] = _analysis_row(row) if row else None
            except Exception as exc:  # noqa: BLE001
                r["analysis_error"] = f"{type(exc).__name__}: {exc}"[:160]
        out.append(r)
    if progress_cb is not None:
        progress_cb(len(out), len(batch), "抓取完成")
    return out


# ==================================================================
# 自动分析（LLM 优先，本地量化兜底）
# ==================================================================
_LOCAL_REC_MAP = [(50, "strong_buy"), (20, "buy"), (-20, "hold"), (-50, "reduce"), (-999, "avoid")]

_EVENT_FACE_WEIGHT = 0.20   # 事件面在综合评分中的权重（本地引擎）
_EVENT_FACE_DAYS = 90       # 事件面回看窗口


# 前瞻管道阶段权重（与 intel_digest.STAGE_WEIGHT 同口径）：已敲定 > 在谈 > 传闻
_STAGE_WEIGHT: dict[str, float] = {"confirmed": 1.25, "negotiating": 1.0, "rumor": 0.65}
# 同一 (发生日, 方向) 最多计入权重的事件条数：同一条消息被路透/Bloomberg/官网
# 各发一遍（标题不同绕过 dedupe）时不再线性刷分
_EVENT_FACE_DAILY_CAP = 3


def _event_face_weights(events: list[dict[str, Any]], days: int, today: dt.date) -> list[dict[str, Any]]:
    """事件面权重计算（纯函数，无 I/O，供 correct 节单测）。

    每条事件 weight = (impact/5) × 时间衰减 max(0.05, 1 - age/days) × 阶段权重，
    再按 (发生日, 方向) 分组取权重最高的前 _EVENT_FACE_DAILY_CAP 条计入（kept）。
    返回 [{weight, age_days, kept}]，与输入事件按下标一一对应。
    """
    out: list[dict[str, Any]] = []
    for it in events:
        ref = it.get("occurred_on") or (it.get("created_at") or "")
        try:
            d0 = dt.date.fromisoformat(str(ref)[:10])
            age = (today - d0).days
        except (ValueError, TypeError):
            age = days  # 日期未知：按最远窗口计（最保守）
        out.append({"weight": 0.0, "age_days": age, "kept": True, "day": str(ref)[:10]})

    for i, it in enumerate(events):
        age = out[i]["age_days"]
        stage = str(it.get("stage") or "")
        out[i]["weight"] = (
            (it.get("impact") or 0) / 5.0
            * max(0.05, 1.0 - max(0, age) / days)
            * _STAGE_WEIGHT.get(stage, 1.0)
        )

    # 同 (发生日, 方向) 封顶：按权重降序保留前 N 条
    groups: dict[tuple[str, str], list[int]] = {}
    for i, it in enumerate(events):
        sent = str(it.get("sentiment") or "neutral")
        groups.setdefault((out[i]["day"], sent), []).append(i)
    for idxs in groups.values():
        for i in sorted(idxs, key=lambda j: -out[j]["weight"])[_EVENT_FACE_DAILY_CAP:]:
            out[i]["kept"] = False
    return out


def _event_face(symbol: str, days: int = _EVENT_FACE_DAYS) -> dict[str, Any]:
    """事件面评分：近期信息按「影响度 × 时间衰减 × 阶段」加权。

    每条事件权重 = (impact/5) × max(0.05, 1 - 距今天数/days) × stage 权重
      · stage：confirmed 1.25 / negotiating 1.0 / rumor 0.65（与 digest 同口径）；
      · 同 (发生日, 方向) 最多计 3 条 —— 多源转发不再线性刷分。
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
                "sentiment": e.sentiment, "occurred_on": e.occurred_on, "stage": e.stage or "",
                "created_at": e.created_at.isoformat() if e.created_at else "",
                "age_days": None,
            }
            for e in rows
        ]
    wts = _event_face_weights(events, days, now.date())
    pos_w = neg_w = 0.0
    pos_n = neg_n = neu_n = 0
    for it, w in zip(events, wts):
        it["age_days"] = w["age_days"]
        it["weight"] = round(w["weight"], 4)
        if not w["kept"]:
            continue
        if it["sentiment"] == "positive":
            pos_w += w["weight"]
            pos_n += 1
        elif it["sentiment"] == "negative":
            neg_w += w["weight"]
            neg_n += 1
        else:
            neu_n += 1
    score = round(100.0 * (pos_w - neg_w) / max(pos_w + neg_w, 0.5), 1) if (pos_w + neg_w) > 0 else None
    top = sorted((it for it, w in zip(events, wts) if w["kept"]),
                 key=lambda x: -x.get("weight", 0.0))[:4]
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


def _vol_position_scale(position_pct: float, rv20: float | None) -> float:
    """建议仓位随已实现波动率缩放（纯函数，供 correct 节单测）。

    rv20 为年化小数（0.18 = 18%）。高波动压缩仓位、低波动适度放大，
    硬上限 20% 与护栏 max_position_pct 对齐：
      rv20 ≥ 40% → ×0.5（TSLA 级波动不给满仓）
      rv20 ≥ 25% → ×0.75
      rv20 ≤ 10% → ×1.25（低波标的仓位效率更高）
    position_pct 无效（≤0）返回 0；rv20 未知原样放行（只做上限钳制）。
    """
    try:
        pos = float(position_pct or 0)
    except (TypeError, ValueError):
        return 0.0
    if pos <= 0:
        return 0.0
    scale = 1.0
    if rv20 is not None:
        if rv20 >= 0.40:
            scale = 0.5
        elif rv20 >= 0.25:
            scale = 0.75
        elif rv20 <= 0.10:
            scale = 1.25
    return round(min(pos * scale, 20.0), 1)


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

    from .ai_analyst import _llm_call, ai_configured

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
    from .data_provider import get_quote

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
        # 重活 1.5：内置 AI 抓取（多源新闻 → 关键节点事件），AI 已配置且开关打开时自动运行
        if st.ai_scrape:
            try:
                from .ai_analyst import ai_configured

                if ai_configured():
                    for r in ai_scrape_companies(limit=3, with_analysis=False, run_id=run_id):
                        if r.get("inserted"):
                            log.info("Intel AI 抓取 %s：+%s 事件（新闻 %s 条）",
                                     r.get("symbol"), r.get("inserted"), r.get("news_n"))
                        elif r.get("error"):
                            log.warning("Intel AI 抓取 %s 失败：%s", r.get("symbol"), r.get("error"))
            except Exception:  # noqa: BLE001 —— 抓取失败不阻塞后续分析
                log.exception("Intel AI 抓取轮失败")
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
        # 重活 4：每日必读清单（**纯规则、不调 LLM**）—— 这是「AI 主动分析并记录」
        # 的确定性部分：每轮把当日事件按重要度重排并落库留痕，用户打开页面即刻可读。
        # 放在最后：即便它失败（例如行情源不可用导致时机区间缺失）也不影响抓取与建议。
        try:
            from . import intel_digest

            digest = intel_digest.build_digest()
            intel_digest.save_digest(digest, generated_by="scheduler")
            log.info("Intel 每日必读已更新：必读 %s 条 / 候选 %s 条",
                     (digest.get("totals") or {}).get("top"), (digest.get("totals") or {}).get("events"))
        except Exception:  # noqa: BLE001
            log.exception("Intel 每日必读生成失败")

    def status(self) -> dict[str, Any]:
        st = ensure_settings()
        cur = self.current_run()
        from .ai_analyst import ai_configured

        return {
            "scheduler_alive": self.alive,
            "monitor_enabled": bool(st.monitor_enabled),
            "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze),
            "ai_scrape": bool(st.ai_scrape),
            "llm_configured": ai_configured(),
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
_VERIFY_BENCHMARK = "SPY"  # 超额收益基准（买方口径：跑赢大盘才算看对）
_HOLD_TOLERANCE = 3.0     # hold 验证：窗口内标的相对基准横在 ±3% 内 → 观望正确

# 验证窗口按建议的 horizon 分档：intraday 建议用 7 天对账毫无意义
VERIFY_WINDOW_DAYS = {"intraday": 2, "swing": 7, "position": 30}


def window_days_for(horizon: str | None) -> int:
    """horizon → 对账窗口（自然日）。未知值回落 swing/7 天。"""
    return VERIFY_WINDOW_DAYS.get((horizon or "swing").strip().lower(), 7)


def _hold_hit(ret: float) -> bool:
    """hold 判定（纯函数）：窗口收益相对基准横在 ±3% 内 → 「观望」正确。"""
    return abs(ret) <= _HOLD_TOLERANCE


def _hit_for(recommendation: str, ret: float) -> bool | None:
    """方向对错判定：看多类涨才算对，看空类跌才算对；死区内为平(None)。

    v2：传入的是**超额收益**（标的收益 − SPY 同期收益）——牛市里涨 2% 而大盘
    涨 3% 不算看对。标的本身是基准（SPY 对 SPY）时超额恒为 0，调用方回退用
    绝对收益判定。
    """
    if abs(ret) <= _VERIFY_TOLERANCE:
        return None
    bullish = recommendation in ("strong_buy", "buy")
    return (ret > 0) if bullish else (ret < 0)


def _close_on_or_before(df: "pd.DataFrame", day: dt.date) -> tuple[dt.date, float] | None:
    """序列里 ≤ day 的最后一根 bar 的 (日期, 收盘)。空/越界返回 None。"""
    import pandas as pd

    if df is None or df.empty:
        return None
    try:
        idx = df.index[df.index.normalize() <= pd.Timestamp(day)]
        if len(idx) == 0:
            return None
        d = idx[-1].normalize()
        px = float(df["close"].loc[d])
        if not px > 0:
            return None
        return d.date(), px
    except Exception:  # noqa: BLE001
        return None


def verify_due_analyses(limit: int = 8) -> int:
    """验证所有「满各自 horizon 窗口未对账」的建议，返回本次验证条数。

    v2（对账口径升级）：
      · 窗口按 horizon 分档：intraday→2 天 / swing→7 天 / position→30 天；
      · 定价精确化：不再用「调度线程跑到时的现价」，而是取历史日线里
        **基线日收盘**（≤分析日）与**目标日收盘**（≤分析日+窗口）——
        无论对账晚跑几天，结果都可复现、可审计；
      · 命中判定改用**相对 SPY 的超额收益**：牛市里跑输大盘的「看多」不算对。
        SPY 自身的建议回退用绝对收益（对自身求超额恒为 0，无意义）。
    三段式不变：① 事务内只读查出到期清单 → ② 事务外取历史序列（网络）→
    ③ 新事务写回。绝不在 SQLite 写事务内做网络调用。
    """
    from .data_provider import fetch_history

    now = dt.datetime.now(dt.timezone.utc)

    def _aware(x: dt.datetime) -> dt.datetime:
        # SQLite 存 naive UTC——统一补 tz 再比较（naive/aware 混比会 TypeError）
        return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)

    # ① 只读：到期清单（按各自 horizon 窗口判定），立刻关事务
    # hold 也参与验证：窗口内相对基准横在 ±3% 内 = 观望正确（不再是永远不算错的逃逸口）
    with session_scope() as db:
        cand = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.outcome_checked_at.is_(None))
            .filter(IntelAnalysis.created_at <= now - dt.timedelta(days=min(VERIFY_WINDOW_DAYS.values())))
            .order_by(IntelAnalysis.created_at.asc())
            .limit(limit * 4)
            .all()
        )
        tasks = [
            {"id": a.id, "symbol": a.symbol,
             "price_at_analysis": a.price_at_analysis, "recommendation": a.recommendation,
             "created": _aware(a.created_at), "window": window_days_for(a.horizon)}
            for a in cand
            if _aware(a.created_at) <= now - dt.timedelta(days=window_days_for(a.horizon))
        ][:limit]
    if not tasks:
        return 0

    # ② 无锁区：历史日线精确对账（单条失败跳过，不拖垮整批）
    bench_symbol = _VERIFY_BENCHMARK
    bench_cache: dict[str, "pd.DataFrame | None"] = {}

    def _hist(sym: str, start: str, end: str):
        key = f"{sym}|{start}|{end}"
        if key not in bench_cache:
            try:
                df, _src = fetch_history(sym, start=start, end=end, interval="1d")
            except Exception:  # noqa: BLE001
                df = None
            bench_cache[key] = df if (df is not None and not df.empty) else None
        return bench_cache[key]

    results: list[tuple[int, float, float, float | None, bool | None, int]] = []
    for t in tasks:
        created: dt.datetime = t["created"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        win = t["window"]
        base_day = created.date()
        target_day = base_day + dt.timedelta(days=win)
        start = (base_day - dt.timedelta(days=10)).isoformat()
        end = (min(target_day, now.date()) + dt.timedelta(days=3)).isoformat()

        sym_df = _hist(t["symbol"], start, end)
        base_bar = _close_on_or_before(sym_df, base_day)
        # 基线价优先用历史收盘（可复现）；历史不可用退回分析时现价
        if base_bar is not None:
            baseline_px = base_bar[1]
            baseline_date = base_bar[0]
        elif t["price_at_analysis"] and t["price_at_analysis"] > 0:
            baseline_px = float(t["price_at_analysis"])
            baseline_date = base_day
        else:
            continue
        tgt_bar = _close_on_or_before(sym_df, target_day)
        if tgt_bar is None or tgt_bar[0] < baseline_date:
            continue  # 目标日尚无收盘（数据缺口），留待下轮
        outcome_px = tgt_bar[1]

        ret = round((outcome_px / baseline_px - 1) * 100, 2)
        # 基准（SPY）：同一基线日 → 同一目标日
        bench_ret: float | None = None
        if t["symbol"].upper() != bench_symbol:
            bdf = _hist(bench_symbol, start, end)
            b_base = _close_on_or_before(bdf, base_day)
            b_tgt = _close_on_or_before(bdf, tgt_bar[0])
            if b_base and b_tgt and b_base[1] > 0:
                bench_ret = round((b_tgt[1] / b_base[1] - 1) * 100, 2)
        judge = ret if (bench_ret is None or t["symbol"].upper() == bench_symbol) \
            else round(ret - bench_ret, 2)
        if t["recommendation"] == "hold":
            hit: bool | None = _hold_hit(judge)
        else:
            hit = _hit_for(t["recommendation"], judge)
        results.append((t["id"], outcome_px, ret, bench_ret, hit, win))

    # ③ 短事务写回（已被并发验证过的条目跳过）
    pairs = []
    with session_scope() as db:
        for aid, px, ret, bench_ret, hit, win in results:
            a = db.get(IntelAnalysis, aid)
            if not a or a.outcome_checked_at is not None:
                continue
            a.outcome_checked_at = now
            a.outcome_price = round(px, 4)
            a.outcome_return = ret
            a.outcome_benchmark = bench_ret
            a.outcome_hit = hit
            a.outcome_window_days = win
            pairs.append((a.symbol, a.recommendation, ret, bench_ret, hit))
    if pairs:
        log.info("Intel 建议验证 %s 条: %s", len(pairs), pairs)
    return len(pairs)


# 置信度校准分桶（下闭上开，最后桶闭区间）
_CAL_BUCKETS: list[tuple[str, float, float]] = [
    ("0-50", 0, 50), ("50-65", 50, 65), ("65-80", 65, 80), ("80+", 80, 100.01),
]


def _calibrate(pairs: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    """置信度分桶校准（纯函数）：每桶 n / 命中数 / 实际胜率 / 平均置信度。

    校准良好的引擎应满足：桶内「平均置信度 ≈ 实际胜率」。
    """
    out: list[dict[str, Any]] = []
    for label, lo, hi in _CAL_BUCKETS:
        seg = [(c, h) for c, h in pairs if lo <= c < hi]
        if not seg:
            continue
        n = len(seg)
        hits = sum(1 for _, h in seg if h)
        out.append({
            "bucket": label,
            "n": n,
            "hits": hits,
            "hit_rate": round(hits / n * 100, 1),
            "avg_confidence": round(sum(c for c, _ in seg) / n, 1),
        })
    return out


def _brier(pairs: list[tuple[float, bool]]) -> float | None:
    """Brier 分数（纯函数）：mean((conf/100 − hit)²)，0 完美 / 0.25 瞎猜，越小越好。"""
    if not pairs:
        return None
    return round(sum(((c / 100.0) - (1.0 if h else 0.0)) ** 2 for c, h in pairs) / len(pairs), 4)


def verify_stats() -> dict[str, Any]:
    """按 Agent 聚合验证结果：胜率、平均收益/超额收益、平均置信度、Brier、校准分桶。"""
    with session_scope() as db:
        rows = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.outcome_checked_at.is_(None) == False)  # noqa: E712
            .all()
        )
        pending = (
            db.query(IntelAnalysis).filter(IntelAnalysis.outcome_checked_at.is_(None))
            .filter(
                IntelAnalysis.created_at
                <= dt.datetime.now(dt.timezone.utc)
                - dt.timedelta(days=min(VERIFY_WINDOW_DAYS.values()))
            )
            .count()
        )
        total = db.query(IntelAnalysis).count()
    by_agent: dict[str, dict[str, Any]] = {}
    for a in rows:
        if a.outcome_hit is None:
            continue  # 平局不计入胜负（hold 现在也验证：横在 ±3% 内算对，False 算错）
        d = by_agent.setdefault(a.agent or "unknown", {
            "n": 0, "hits": 0, "rets": [], "excess": [], "confs": [], "pairs": []})
        d["n"] += 1
        d["hits"] += 1 if a.outcome_hit else 0
        d["rets"].append(a.outcome_return or 0.0)
        if a.outcome_benchmark is not None:
            d["excess"].append(round((a.outcome_return or 0.0) - a.outcome_benchmark, 2))
        d["confs"].append(a.confidence)
        d["pairs"].append((a.confidence, bool(a.outcome_hit)))
    agents = []
    for agent, d in sorted(by_agent.items(), key=lambda kv: -kv[1]["n"]):
        agents.append({
            "agent": agent,
            "n": d["n"],
            "hits": d["hits"],
            "hit_rate": round(d["hits"] / d["n"] * 100, 1) if d["n"] else None,
            "avg_return": round(sum(d["rets"]) / len(d["rets"]), 2) if d["rets"] else None,
            "avg_excess_return": round(sum(d["excess"]) / len(d["excess"]), 2) if d["excess"] else None,
            "avg_confidence": round(sum(d["confs"]) / len(d["confs"]), 1) if d["confs"] else None,
            "brier": _brier(d["pairs"]),
            "calibration": _calibrate(d["pairs"]),
        })
    all_rets = [(a.outcome_return or 0.0) for a in rows if a.outcome_hit is not None]
    all_pairs = [(a.confidence, bool(a.outcome_hit)) for a in rows if a.outcome_hit is not None]
    all_excess = [
        round((a.outcome_return or 0.0) - a.outcome_benchmark, 2)
        for a in rows if a.outcome_hit is not None and a.outcome_benchmark is not None
    ]
    return {
        "verified_total": len(rows),
        "pending": pending,
        "analyses_total": total,
        "agents": agents,
        "global_hit_rate": (
            round(sum(1 for a in rows if a.outcome_hit) / len(all_rets) * 100, 1) if all_rets else None
        ),
        "global_avg_excess_return": round(sum(all_excess) / len(all_excess), 2) if all_excess else None,
        "global_brier": _brier(all_pairs),
        "global_calibration": _calibrate(all_pairs),
        "tolerance_pct": _VERIFY_TOLERANCE,
        "window_days": 7,  # 兼容旧字段；实际窗口按 horizon 分档见 window_days_by_horizon
        "window_days_by_horizon": VERIFY_WINDOW_DAYS,
        "benchmark": _VERIFY_BENCHMARK,
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
            # 已知日期优先：occurred_on 为空（日期未知）排最后，同日再按时刻倒序
            .order_by(
                case((IntelEvent.occurred_on != "", 0), else_=1),
                IntelEvent.occurred_on.desc(),
                IntelEvent.occurred_at.desc(),
                IntelEvent.id.desc(),
            )
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
            "id": e.id, "occurred_on": e.occurred_on, "occurred_at": e.occurred_at or "",
            "category": e.category,
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
