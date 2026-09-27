"""AI 接管（Ops）接口：一屏总览 + 一键操作 + 决策追溯查询。

设计目标：**任何 LLM** 拿到 `/api/ops/overview` 的 JSON + `/api/docs` 的 OpenAPI，
即可在无人工解释的情况下接管平台 —— 所以每个字段都带 `字段说明`。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from .. import alerts as alertmod
from .. import decisions as decisionsmod
from ..config import FRONTEND_DIST, RUNTIME_DIR, settings
from ..database import SessionLocal
from ..engine import ACTIVE_ENGINES
from .deps import CurrentUser

router = APIRouter(prefix="/ops", tags=["AI 接管"])

FIELD_DOC = {
    "system": "系统状态：mode=模拟/实盘、broker=券商、kill_switch=熔断（true 时拒单）",
    "account": "账户：equity=权益(USD)、day_pnl=当日盈亏、cash=现金",
    "positions": "当前持仓列表：quantity>0 为持有；market_value=市值；avg_cost=成本",
    "watchlist_quotes": "关注标的实时行情：price/change_pct（红涨绿跌按中国习惯在前端渲染）",
    "engines": "活跃交易引擎：strategy_id 锚定；runtime_stats 含 exec_count/last_tick/最近执行耗时",
    "engine_plan": "引擎当前计划：target_weights=目标权重；last_actions=最近动作；last_skipped=最近被拦原因",
    "recent_decisions": "决策日志：每个决策的 因子(context)→结论(decision)→依据(reasoning) 完整链条",
    "unread_alerts": "未读智能提示数（新闻关键词/技术信号）",
    "decision_stats": "近 N 小时决策统计：by_actor（谁决定的）/ by_action（做了什么）",
}


@router.get("/overview")
def ops_overview(user: CurrentUser, include_decisions: int = Query(20, ge=0, le=100)) -> dict:  # noqa: ARG001
    """AI 一屏总览。单一请求拿到接管所需的全部上下文。"""
    from .. import state as appstate
    from ..brokers import get_broker
    from ..data_provider import get_quotes

    out: dict = {"字段说明": FIELD_DOC}

    # 系统
    st = appstate.system_status()
    st["runtime_dir"] = str(RUNTIME_DIR)
    st["frontend_built"] = (FRONTEND_DIST / "index.html").exists()
    # 实盘就绪状态（三重锁逐项）：供 AI 与人工判断「现在能不能下真单」
    ok_live, live_reason = appstate.live_trading_available()
    st["live_ready"] = ok_live
    st["live_reason"] = live_reason
    st["live_unlocked"] = appstate.live_unlocked()
    out["system"] = st

    # 账户与持仓（券商不可用时如实报错，不猜）
    try:
        # P3：与**下单通道保持同源**。旧实现直接 `get_broker()`（吃默认配置），
        # 而 paper 模式下真实下单走的是内置模拟券商 —— overview 展示的账户
        # 可能与实际下单通道不是同一个。这里复用 trading 的路由逻辑。
        from .trading import _broker_and_mode

        broker, _bmode = _broker_and_mode()
        acc = broker.account()
        out["account"] = {
            "connected": acc.connected, "equity": acc.equity, "cash": acc.cash,
            "day_pnl": acc.day_pnl, "message": getattr(acc, "message", ""),
        }
        out["positions"] = [
            {
                "symbol": p.symbol, "quantity": p.quantity, "avg_cost": p.avg_cost,
                "last_price": p.last_price, "market_value": p.market_value,
                "currency": getattr(p, "currency", ""), "market": getattr(p, "market", "US"),
            }
            for p in broker.positions() if p.quantity > 0
        ]
    except Exception as exc:  # noqa: BLE001
        out["account"] = {"connected": False, "error": f"{type(exc).__name__}: {exc}"}
        out["positions"] = []

    # 关注行情
    try:
        from ..models import WatchlistItem

        with SessionLocal() as s:
            syms = [w.symbol for w in s.query(WatchlistItem).all()]
        out["watchlist_quotes"] = get_quotes(syms) if syms else []
    except Exception as exc:  # noqa: BLE001
        out["watchlist_quotes"] = {"error": f"{type(exc).__name__}: {exc}"}

    # 引擎（含计划）
    engines = []
    for sid, t in ACTIVE_ENGINES.items():
        try:
            rs = t.runtime_stats()
        except Exception:  # noqa: BLE001
            rs = {}
        tick = getattr(t, "last_tick_detail", None)
        engines.append({
            "strategy_id": sid,
            "strategy_name": getattr(t, "strategy_name", ""),
            "mode": getattr(t, "mode", ""),
            "running": t.running,
            "symbols": getattr(t, "symbols", []),
            "runtime_stats": rs,
            "target_weights": dict(getattr(t, "last_targets", {}) or {}),
            "last_actions": getattr(tick, "actions", []) if tick else [],
            "last_skipped": getattr(tick, "skipped", []) if tick else [],
            "last_errors": getattr(tick, "errors", []) if tick else [],
        })
    out["engines"] = engines
    out["decision_stats"] = decisionsmod.stats(hours=24)

    if include_decisions > 0:
        out["recent_decisions"] = decisionsmod.list_decisions(limit=include_decisions)
    out["unread_alerts"] = alertmod.unread_count()
    out["recent_alerts"] = alertmod.list_events(limit=10)
    # 待审 AI 提案（T-107）：AI 接管方与人工共用同一视图
    from .. import proposals as propmod

    out["proposals"] = propmod.list_proposals(limit=10)
    out["pending_proposals"] = sum(1 for p in out["proposals"] if p["status"] == "proposed")
    return out


@router.get("/guide")
def ops_guide(user: CurrentUser) -> dict:  # noqa: ARG001
    """AI 操作手册（机器可读）。供任何 LLM/Agent 在接管前读取。"""
    import importlib.resources
    from pathlib import Path

    guide_path = Path(__file__).resolve().parent.parent.parent.parent / "AI_GUIDE.md"
    if guide_path.exists():
        content = guide_path.read_text(encoding="utf-8")
    else:
        content = "见 /api/ops/overview 的「字段说明」与 /api/docs。"
    return {
        "format": "markdown",
        "hint": "读完本手册 + GET /api/ops/overview 即可接管平台；接口清单见 /api/openapi.json",
        "content": content,
    }


@router.get("/decisions")
def ops_decisions(
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    actor: str = "",
    symbol: str = "",
    action: str = "",
) -> dict:
    """决策日志查询（可按 actor/symbol/action 过滤）。"""
    return {"items": decisionsmod.list_decisions(limit=limit, actor=actor, symbol=symbol, action_contains=action)}


# ==================================================================
# AI 提案（T-107）：AI 建议 → 人工批准 → 走完整下单链
# ==================================================================
@router.get("/proposals")
def ops_proposals(user: CurrentUser, status: str = "", limit: int = Query(30, ge=1, le=100)) -> dict:  # noqa: ARG001
    from .. import proposals as propmod

    return {"items": propmod.list_proposals(status=status, limit=limit)}


@router.post("/proposals")
def ops_proposal_create(payload: dict, user: CurrentUser) -> dict:
    """创建提案（AI 接管方调用）。body: symbol/action/size_pct/rationale/entry/stop/take_profit/factors"""
    from .. import proposals as propmod

    try:
        p = propmod.create(
            symbol=str(payload.get("symbol", "")),
            action=str(payload.get("action", "")),
            size_pct=float(payload.get("size_pct", 0)),
            rationale=str(payload.get("rationale", "")),
            entry=float(payload.get("entry") or 0),
            stop=payload.get("stop"),
            take_profit=payload.get("take_profit"),
            factors=payload.get("factors") or {},
            created_by=str(payload.get("created_by") or f"user:{user.username}"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "proposal": p}


@router.post("/proposals/{proposal_id}/approve")
def ops_proposal_approve(proposal_id: int, payload: dict | None = None, user: CurrentUser = None) -> dict:
    """批准并立即执行（走完整下单链：熔断/实盘三重锁/风控护栏/实盘口令，一个不少）。

    实盘模式（IBKR 实盘端口）下 body 必须带 {"password": "<账户口令>"}。
    """
    from .. import proposals as propmod

    password = str((payload or {}).get("password", ""))
    try:
        p = propmod.decide(proposal_id, approve=True, reviewer=user.username, password=password)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(422, f"执行失败：{exc}") from exc
    return {"ok": True, "proposal": p}


@router.post("/proposals/{proposal_id}/reject")
def ops_proposal_reject(proposal_id: int, user: CurrentUser) -> dict:
    from .. import proposals as propmod

    try:
        p = propmod.decide(proposal_id, approve=False, reviewer=user.username)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "proposal": p}


@router.post("/engine/{strategy_id}/stop")
async def ops_engine_stop(strategy_id: int, user: CurrentUser) -> dict:  # noqa: ARG001
    """一键停止某个引擎（AI 或人工皆可调用）。"""
    from .. import state as appstate
    from ..database import session_scope
    from ..models import EngineRun

    task = ACTIVE_ENGINES.pop(strategy_id, None)
    if task is None:
        raise HTTPException(404, "该策略没有正在运行的引擎")
    await task.stop()

    def _mark_stopped() -> None:
        # P0-2：session_scope 内含 commit，是同步阻塞调用 —— 必须走工作线程，
        # 否则 SQLite 写锁会卡住整个事件循环（引擎 tick / WS 推送 / 其他 API 全停）。
        with session_scope() as s:
            row = s.get(EngineRun, task.engine_run_id)
            if row:
                row.status = "STOPPED"

    await run_in_threadpool(_mark_stopped)
    await run_in_threadpool(appstate.log, "ops_engine_stop", "INFO",
                            f"接管中心停止引擎 #{task.engine_run_id}", user.username)
    return {"ok": True, "strategy_id": strategy_id, "stopped": True}


@router.post("/kill-switch")
def ops_kill_switch(enable: bool = True, body: dict | None = None, user: CurrentUser = None) -> dict:
    """一键熔断/解除。enable=true 后所有新订单被拒绝（已有持仓不动）。

    安全规则与 /risk/kill-switch 对齐（修复评估报告指出的矛盾）：
    启用无需口令（紧急制动，降险操作）；**解除必须校验账户口令**（升险操作）。
    """
    from .. import state as appstate
    from ..security import verify_password

    if not enable:
        pw = str((body or {}).get("password") or "")
        if not pw or not verify_password(pw, user.password_hash):
            raise HTTPException(400, "解除熔断需要输入账户口令（与风控页规则一致）")
    appstate.update_risk_config({"kill_switch": bool(enable)})
    appstate.log("ops_kill_switch", "CRITICAL" if enable else "WARN",
                 f"接管中心{'启用' if enable else '解除'}熔断", actor=user.username)
    return {"ok": True, "kill_switch": bool(enable)}
