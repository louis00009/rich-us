"""AI 情报中心 API。

两组端点：
  · 管理端（/intel/*）          —— 走平台标准 JWT（CurrentUser），页面使用；
  · Bridge 端（/intel/bridge/*） —— 走独立 X-Intel-Token，供 WorkBuddy / Claude Code /
    Codex 等外部 AI Agent 领任务与提交成果。Bridge 只能读写情报数据，
    与交易账户、持仓、密钥完全隔离。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from .. import intel
from ..database import session_scope
from ..models import IntelAnalysis, IntelBridgeLog, IntelCompany, IntelEvent, IntelRun
from .deps import CurrentUser

router = APIRouter(prefix="/intel", tags=["AI 情报中心"])

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^]{1,16}$")
def _norm_agent(agent: str | None) -> str:
    """解析式处理任意 Agent 名：不设白名单——非法字符替换为 '-' 而非整体拒绝。

    例：'WorkBuddy AI'→'WorkBuddy-AI'，'workbuddy.ai'→'workbuddy-ai'，
    名字完整保留（截 48 与 DB 列宽一致），空值才回退 unknown。
    """
    a = re.sub(r"[^A-Za-z0-9_\-. ]", "-", (agent or "").strip())
    a = re.sub(r"[ .]+", "-", a).strip("-_")[:48]
    return a or "unknown"


# ==================================================================
# Bridge 鉴权
# ==================================================================
def bridge_auth(
    x_intel_token: Annotated[str, Header()] = "",
    token: Annotated[str, Query(include_in_schema=False)] = "",
) -> str:
    """校验 Bridge Token，返回规范化前的 token（仅用于比对）。"""
    st = intel.ensure_settings()
    supplied = x_intel_token or token
    if not supplied or supplied != st.bridge_token:
        raise HTTPException(401, "X-Intel-Token 无效或缺失（可在情报中心页面查看/重置）")
    return supplied


# ==================================================================
# 请求体
# ==================================================================
class MonitorStartReq(BaseModel):
    interval_minutes: int | None = None
    auto_analyze: bool | None = None


class IntelSettingsReq(BaseModel):
    interval_minutes: int | None = None
    auto_analyze: bool | None = None


class CompanyReq(BaseModel):
    symbol: str
    name: str = ""
    theme: str = ""
    focus: str = ""


class CompanyUpdateReq(BaseModel):
    name: str | None = None
    theme: str | None = None
    focus: str | None = None
    enabled: bool | None = None


class BridgeEventsReq(BaseModel):
    agent: str = "unknown"
    events: list[dict[str, Any]] = []


class BridgeAnalysisReq(BaseModel):
    agent: str = "unknown"
    analyses: list[dict[str, Any]] = []


class BridgeDoneReq(BaseModel):
    agent: str = "unknown"
    note: str = ""


# ==================================================================
# 管理端
# ==================================================================
@router.get("/overview")
def overview(user: CurrentUser) -> dict:  # noqa: ARG001
    intel.ensure_default_companies()
    st = intel.ensure_settings()
    with session_scope() as db:
        n_events = db.query(IntelEvent).count()
        n_analyses = db.query(IntelAnalysis).count()
        n_companies = db.query(IntelCompany).count()
        n_enabled = db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).count()
        companies = db.query(IntelCompany).order_by(IntelCompany.id).all()
        recent_events = db.query(IntelEvent).order_by(IntelEvent.created_at.desc()).limit(15).all()
        recent_analyses = db.query(IntelAnalysis).order_by(IntelAnalysis.created_at.desc()).limit(8).all()
        runs = db.query(IntelRun).order_by(IntelRun.id.desc()).limit(10).all()
        tasks_pending = len(intel.pending_tasks(db, st.interval_minutes))
        day_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        logs = db.query(IntelBridgeLog).filter(IntelBridgeLog.ts >= day_ago).all()
        agents: dict[str, str] = {}
        for lg in logs:
            agents.setdefault(lg.agent, lg.ts.isoformat())
        # 每个 agent 保留最近一次活动
        for lg in logs:
            if agents.get(lg.agent, "") < lg.ts.isoformat():
                agents[lg.agent] = lg.ts.isoformat()
    return {
        "settings": {
            "monitor_enabled": bool(st.monitor_enabled),
            "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze),
            "bridge_token": st.bridge_token,
        },
        "scheduler": intel.SCHEDULER.status(),
        "stats": {
            "events_total": n_events,
            "analyses_total": n_analyses,
            "companies_total": n_companies,
            "companies_enabled": n_enabled,
            "tasks_pending": tasks_pending,
            "agents_24h": agents,
        },
        "companies": [
            {
                "id": c.id, "symbol": c.symbol, "name": c.name, "theme": c.theme,
                "focus": c.focus, "enabled": c.enabled,
                "last_scrape_at": c.last_scrape_at.isoformat() if c.last_scrape_at else None,
            }
            for c in companies
        ],
        "recent_events": [intel._event_row(e) for e in recent_events],
        "recent_analyses": [intel._analysis_row(a) for a in recent_analyses],
        "runs": [intel._run_row(r) for r in runs],
    }


@router.put("/settings")
def update_settings(payload: IntelSettingsReq, user: CurrentUser) -> dict:  # noqa: ARG001
    """预配置抓取周期 / 自动分析（不开监控也能改）。"""
    intel.save_settings(interval_minutes=payload.interval_minutes, auto_analyze=payload.auto_analyze)
    st = intel.ensure_settings()
    return {"ok": True, "interval_minutes": st.interval_minutes, "auto_analyze": bool(st.auto_analyze)}


@router.post("/monitor/start")
def monitor_start(payload: MonitorStartReq, user: CurrentUser) -> dict:  # noqa: ARG001
    intel.ensure_default_companies()
    run_id = intel.SCHEDULER.start(payload.interval_minutes, payload.auto_analyze)
    return {"ok": True, "run_id": run_id, "status": intel.SCHEDULER.status()}


@router.post("/monitor/stop")
def monitor_stop(user: CurrentUser) -> dict:  # noqa: ARG001
    result = intel.SCHEDULER.stop()
    return {"ok": True, **result, "status": intel.SCHEDULER.status()}


@router.get("/companies")
def list_companies(user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        rows = db.query(IntelCompany).order_by(IntelCompany.id).all()
        return {"items": [
            {"id": c.id, "symbol": c.symbol, "name": c.name, "theme": c.theme, "focus": c.focus,
             "enabled": c.enabled,
             "last_scrape_at": c.last_scrape_at.isoformat() if c.last_scrape_at else None}
            for c in rows
        ]}


@router.post("/companies")
def add_company(payload: CompanyReq, user: CurrentUser) -> dict:  # noqa: ARG001
    symbol = payload.symbol.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(400, "标的代码格式不合法（示例：NVDA / ASML / BRK.B）")
    with session_scope() as db:
        row = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()
        if row:
            row.enabled = True
            if payload.name:
                row.name = payload.name.strip()[:120]
            if payload.theme:
                row.theme = payload.theme.strip()[:120]
            if payload.focus:
                row.focus = payload.focus.strip()[:500]
            cid = row.id
        else:
            row = IntelCompany(symbol=symbol, name=payload.name.strip()[:120],
                               theme=payload.theme.strip()[:120], focus=payload.focus.strip()[:500],
                               enabled=True)
            db.add(row)
            db.flush()
            cid = row.id
    return {"ok": True, "id": cid, "symbol": symbol}


@router.post("/companies/sync-watchlist")
def sync_companies_from_watchlist(user: CurrentUser) -> dict:  # noqa: ARG001
    """一键把平台关注列表（watchlist）同步进观察标的：已存在的跳过，其余全部启用。

    保持「行情收藏 ↔ AI 观察标的」同一份名单；Intel 侧新增的公司 theme/focus
    先用占位，可随时在列表里编辑。
    """
    from ..models import WatchlistItem

    added: list[str] = []
    skipped = 0
    with session_scope() as db:
        known = {c.symbol for c in db.query(IntelCompany).all()}
        for w in db.query(WatchlistItem).all():
            if w.symbol in known:
                skipped += 1
                continue
            db.add(IntelCompany(symbol=w.symbol, name=(w.note or w.symbol)[:120],
                                theme="关注列表同步", focus="", enabled=True))
            added.append(w.symbol)
    return {"ok": True, "added": added, "added_count": len(added), "skipped": skipped}


@router.put("/companies/{cid}")
def update_company(cid: int, payload: CompanyUpdateReq, user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        row = db.get(IntelCompany, cid)
        if not row:
            raise HTTPException(404, "公司不存在")
        if payload.name is not None:
            row.name = payload.name.strip()[:120]
        if payload.theme is not None:
            row.theme = payload.theme.strip()[:120]
        if payload.focus is not None:
            row.focus = payload.focus.strip()[:500]
        if payload.enabled is not None:
            row.enabled = bool(payload.enabled)
        return {"ok": True}


@router.delete("/companies/{cid}")
def delete_company(cid: int, user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        row = db.get(IntelCompany, cid)
        if not row:
            raise HTTPException(404, "公司不存在")
        db.delete(row)
    return {"ok": True}


@router.get("/events")
def list_events(user: CurrentUser, symbol: str = "", limit: int = 100) -> dict:  # noqa: ARG001
    limit = max(1, min(500, limit))
    with session_scope() as db:
        q = db.query(IntelEvent).order_by(IntelEvent.created_at.desc())
        if symbol:
            q = q.filter(IntelEvent.symbol == symbol.strip().upper())
        rows = q.limit(limit).all()
    return {"items": [intel._event_row(e) for e in rows]}


@router.delete("/events/{eid}")
def delete_event(eid: int, user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        row = db.get(IntelEvent, eid)
        if not row:
            raise HTTPException(404, "事件不存在")
        db.delete(row)
    return {"ok": True}


@router.get("/analyses")
def list_analyses(user: CurrentUser, symbol: str = "", limit: int = 50) -> dict:  # noqa: ARG001
    limit = max(1, min(200, limit))
    with session_scope() as db:
        q = db.query(IntelAnalysis).order_by(IntelAnalysis.created_at.desc())
        if symbol:
            q = q.filter(IntelAnalysis.symbol == symbol.strip().upper())
        rows = q.limit(limit).all()
    return {"items": [intel._analysis_row(a) for a in rows]}


@router.post("/analyze/{symbol}")
def analyze_now(symbol: str, user: CurrentUser) -> dict:  # noqa: ARG001
    """手动触发一次分析（LLM 优先 / 本地兜底），不依赖监控是否开启。"""
    symbol = symbol.strip().upper()
    with session_scope() as db:
        if not db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first():
            raise HTTPException(404, "该公司不在观察列表中，请先添加")
        run = db.query(IntelRun).filter(IntelRun.status == "running").order_by(IntelRun.id.desc()).first()
        run_id = run.id if run else None
    row = intel.auto_analyze_symbol(symbol, run_id)
    if row is None:
        raise HTTPException(502, "分析失败：行情数据不可用或 LLM 异常，请稍后重试")
    return {"ok": True, "analysis": intel._analysis_row(row)}


@router.get("/runs")
def list_runs(user: CurrentUser, limit: int = 30) -> dict:  # noqa: ARG001
    limit = max(1, min(100, limit))
    with session_scope() as db:
        rows = db.query(IntelRun).order_by(IntelRun.id.desc()).limit(limit).all()
    return {"items": [intel._run_row(r) for r in rows]}


@router.get("/runs/{rid}/report")
def run_report(rid: int, user: CurrentUser) -> dict:  # noqa: ARG001
    from pathlib import Path

    with session_scope() as db:
        run = db.get(IntelRun, rid)
        if not run:
            raise HTTPException(404, "批次不存在")
        path = run.report_path
    if not path or not Path(path).exists():
        path = intel.write_report(rid)
        if not path:
            raise HTTPException(404, "批次不存在")
    text = Path(path).read_text(encoding="utf-8")
    return {"path": path, "markdown": text}


@router.post("/bridge-token/reset")
def reset_token(user: CurrentUser) -> dict:  # noqa: ARG001
    token = intel.reset_bridge_token()
    return {"ok": True, "bridge_token": token}


@router.get("/bridge/guide")
def bridge_guide(user: CurrentUser) -> dict:  # noqa: ARG001
    return intel.bridge_guide()


@router.get("/verify/stats")
def verify_stats(user: CurrentUser) -> dict:  # noqa: ARG001
    """按 Agent 聚合的建议验证统计（胜率 / 平均实际收益 / 置信度校准）。"""
    return intel.verify_stats()


@router.post("/verify/run")
def verify_run(user: CurrentUser) -> dict:  # noqa: ARG001
    """手动触发一次到期建议对账（满 7 天未验证的立即结算）。"""
    n = intel.verify_due_analyses(limit=50)
    return {"ok": True, "verified": n, "stats": intel.verify_stats()}


@router.get("/timeline/{symbol}")
def intel_timeline(symbol: str, user: CurrentUser, days: int = 180) -> dict:  # noqa: ARG001
    """公司时间线：过去 N 天事件（含已敲定/在谈/传闻管道）+ 最新 AI 建议 + 行情摘要。

    「财报是滞后指标」——用合同管道前瞻未来 3-6 个月经营状况。
    """
    return intel.timeline(symbol, days=max(30, min(400, int(days or 180))))


@router.get("/history/{symbol}")
def price_history(symbol: str, user: CurrentUser, days: int = 120) -> dict:  # noqa: ARG001
    """日线收盘序列（供事件时间线叠加价格曲线）。"""
    import datetime as _dt

    from ..data_provider import fetch_history

    symbol = symbol.strip().upper()
    days = max(7, min(400, int(days or 120)))
    start = (_dt.datetime.now() - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df, source = fetch_history(symbol, start=start, interval="1d")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"行情获取失败：{exc}") from exc
    if df is None or df.empty:
        return {"symbol": symbol, "source": source, "dates": [], "close": []}
    # 严格按请求区间裁剪（fetch_history 缓存/增量可能返回更早的数据）
    import pandas as _pd

    df = df[df.index >= _pd.to_datetime(start)]
    return {
        "symbol": symbol,
        "source": source,
        "count": len(df),
        "dates": [str(d)[:10] for d in df.index],
        "close": [round(float(x), 4) for x in df["close"]],
    }


# ==================================================================
# Bridge 端（外部 AI Agent：WorkBuddy / Claude Code / Codex ...）
# ==================================================================
@router.get("/bridge/poll")
def bridge_poll(agent: str = "unknown", _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    intel.bridge_log(_norm_agent(agent), "poll")
    intel.ensure_default_companies()
    st = intel.ensure_settings()
    run = intel.SCHEDULER.current_run()
    with session_scope() as db:
        tasks = intel.pending_tasks(db, st.interval_minutes)
        n_enabled = db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).count()
    return {
        "ok": True,
        "agent": _norm_agent(agent),
        "monitor_running": run is not None,
        "run": intel._run_row(run) if run else None,
        "tasks": tasks,
        "watchlist_size": n_enabled,
        "instruction": (
            "对每个 task：联网检索最近 90 天关键节点（模型/产品发布、重大合作、财报、监管、人事）→ "
            "POST /api/intel/bridge/events 提交事件 → GET /api/intel/bridge/brief/{symbol} 取简报 → "
            "POST /api/intel/bridge/analysis 提交买入建议 → 最后 POST /api/intel/bridge/done。"
            "信息必须带真实来源（source_name/source_url），禁止编造。"
        ),
        "event_categories": intel.EVENT_CATEGORIES,
        "recommendation_options": sorted(intel.RECOMMENDATIONS),
    }


@router.get("/bridge/brief/{symbol}")
def bridge_brief(symbol: str, agent: str = "unknown", _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    symbol = symbol.strip().upper()
    brief = intel.company_brief(symbol)
    if not brief["company"]["name"] and not brief["recent_events"] and not brief["company"].get("enabled"):
        # 未建档标的也允许看简报（行情仍可用），仅提示
        brief["note"] = "该标的不在观察列表（事件提交后会自动建档为未启用）"
    intel.bridge_log(_norm_agent(agent), "brief", symbol)
    return {"ok": True, **brief}


@router.post("/bridge/events")
def bridge_events(payload: BridgeEventsReq, _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    agent = _norm_agent(payload.agent)
    if not payload.events:
        raise HTTPException(400, "events 为空")
    run = intel.SCHEDULER.current_run()
    res = intel.add_events(payload.events[:100], agent, run.id if run else None)
    intel.bridge_log(agent, "submit_events",
                     f"+{res['inserted']} dup={res['duplicates']} rej={res['rejected']}")
    return {"ok": True, **res}


@router.post("/bridge/analysis")
def bridge_analysis(payload: BridgeAnalysisReq, _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    agent = _norm_agent(payload.agent)
    if not payload.analyses:
        raise HTTPException(400, "analyses 为空")
    run = intel.SCHEDULER.current_run()
    inserted, errors = 0, []
    for item in payload.analyses[:50]:
        try:
            symbol = str(item.get("symbol", "")).strip().upper()
            if not symbol:
                errors.append("缺少 symbol")
                continue
            from ..data_provider import get_quote

            price = float((get_quote(symbol) or {}).get("price") or 0.0)
            row = intel.add_analysis(item, agent=agent, engine="agent",
                                     run_id=run.id if run else None, price=price)
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{exc}"[:120])
    intel.bridge_log(agent, "submit_analysis", f"+{inserted} err={len(errors)}")
    return {"ok": inserted > 0, "inserted": inserted, "errors": errors}


@router.post("/bridge/done")
def bridge_done(payload: BridgeDoneReq, _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    agent = _norm_agent(payload.agent)
    run = intel.SCHEDULER.current_run()
    with session_scope() as db:
        if run:
            r = db.get(IntelRun, run.id)
            if r:
                intel._seen_add(r, agent)
    intel.bridge_log(agent, "done", payload.note[:400])
    return {"ok": True, "message": "本轮任务已记录，感谢。"}
