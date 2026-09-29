"""AI 情报中心 · Bridge 端 API（外部 AI Agent）。

从 `api/intel.py` 抽出（铁律 9 拆分，2026-09-29）。

供 WorkBuddy / Claude Code / Codex 等外部 AI Agent 领任务与提交成果。
**鉴权独立于平台 JWT**（走 `X-Intel-Token`），且只能读写情报数据 ——
与交易账户、持仓、密钥完全隔离。

路径：本 router 的 `prefix` 是 `/bridge`，被挂到 `api/intel.py` 的 `/intel` router 下，
最终 URL 为 `/api/intel/bridge/...` —— 与拆分前完全一致。
⚠️ 若这里写成 `prefix="/intel/bridge"`，会与父 router 的 `/intel` 叠加成
`/api/intel/intel/bridge/...`（实测踩过），务必只写 `/bridge`。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from .. import intel
from ..database import session_scope
from ..models import IntelCompany, IntelRun
from .intel_common import (
    BridgeAnalysisReq,
    BridgeDoneReq,
    BridgeEventsReq,
    _norm_agent,
    bridge_auth,
)

router = APIRouter(prefix="/bridge", tags=["AI 情报中心 · Bridge"])


@router.get("/poll")
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


@router.get("/brief/{symbol}")
def bridge_brief(symbol: str, agent: str = "unknown", _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    symbol = symbol.strip().upper()
    brief = intel.company_brief(symbol)
    if not brief["company"]["name"] and not brief["recent_events"] and not brief["company"].get("enabled"):
        # 未建档标的也允许看简报（行情仍可用），仅提示
        brief["note"] = "该标的不在观察列表（事件提交后会自动建档为未启用）"
    intel.bridge_log(_norm_agent(agent), "brief", symbol)
    return {"ok": True, **brief}


@router.post("/events")
def bridge_events(payload: BridgeEventsReq, _auth: Annotated[str, Depends(bridge_auth)] = "") -> dict:
    agent = _norm_agent(payload.agent)
    if not payload.events:
        raise HTTPException(400, "events 为空")
    run = intel.SCHEDULER.current_run()
    res = intel.add_events(payload.events[:100], agent, run.id if run else None)
    intel.bridge_log(agent, "submit_events",
                     f"+{res['inserted']} dup={res['duplicates']} rej={res['rejected']}")
    return {"ok": True, **res}


@router.post("/analysis")
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


@router.post("/done")
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
