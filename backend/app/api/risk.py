"""风控接口：护栏配置、熔断开关、审计日志。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from .. import state as appstate
from ..models import AuditLog
from ..risk import summarize_limits
from ..schemas import KillSwitchRequest, RiskConfigIn
from ..security import verify_password
from .deps import CurrentUser, DbSession

router = APIRouter(prefix="/risk", tags=["风控"])


def _row_dict(r) -> dict:  # noqa: ANN001
    return {
        "max_position_pct": r.max_position_pct,
        "max_gross_exposure_pct": r.max_gross_exposure_pct,
        "max_open_positions": r.max_open_positions,
        "min_order_notional": r.min_order_notional,
        "max_order_notional": r.max_order_notional,
        "max_daily_loss_pct": r.max_daily_loss_pct,
        "max_drawdown_pct": r.max_drawdown_pct,
        "stop_type": r.stop_type,
        "stop_value": r.stop_value,
        "take_profit_r": r.take_profit_r,
        "time_stop_bars": r.time_stop_bars,
        "sizing_method": r.sizing_method,
        "risk_per_trade_pct": r.risk_per_trade_pct,
        "trading_hours_only": bool(r.trading_hours_only),
        "whitelist": r.whitelist or "",
        "blacklist": r.blacklist or "",
        "kill_switch": bool(r.kill_switch),
        "live_unlocked": bool(r.live_unlocked),
        # 市场感知（T-113/T-114）
        "allow_short": bool(getattr(r, "allow_short", False)),
        "allow_extended_hours": bool(getattr(r, "allow_extended_hours", False)),
        "hk_max_gross_exposure_pct": float(getattr(r, "hk_max_gross_exposure_pct", 100.0)),
        "max_daily_orders": int(getattr(r, "max_daily_orders", 0) or 0),
        "max_orders_per_minute": int(getattr(r, "max_orders_per_minute", 0) or 0),
        "updated_at": r.updated_at.isoformat() if r.updated_at else "",
    }


@router.get("/config")
def get_config(user: CurrentUser) -> dict:  # noqa: ARG001
    row = appstate.get_risk_row()
    return {
        "config": _row_dict(row),
        "summary": summarize_limits(appstate.risk_limits()),
        "live_env_gate": bool(appstate.app_settings.allow_live_trading),
        "live_unlocked": appstate.live_unlocked(),
    }


@router.put("/config")
def update_config(payload: RiskConfigIn, user: CurrentUser) -> dict:
    row = appstate.update_risk_config(payload.model_dump())
    appstate.log("risk_config_update", "WARN", f"更新风控配置：{payload.model_dump()}", actor=user.username)
    return {
        "ok": True,
        "config": _row_dict(row),
        "summary": summarize_limits(appstate.risk_limits()),
        "message": "风控配置已更新（对下一笔订单立即生效）",
    }


@router.post("/kill-switch")
def kill_switch(payload: KillSwitchRequest, user: CurrentUser) -> dict:
    """
    熔断开关：启用无需口令（紧急制动），解除需要口令（防止误触）。
    """
    if payload.engaged:
        row = appstate.update_risk_config({"kill_switch": True})
        appstate.log("kill_switch_on", "CRITICAL", "🛑 熔断开关已启用，全部下单通道关闭", actor=user.username)
        return {
            "ok": True, "kill_switch": True,
            "message": "已启用熔断：所有新订单（含实时引擎）将被拒绝。已有的持仓不会被自动平仓，请自行决定处理方式。",
            "config": _row_dict(row),
        }

    if not payload.password or not verify_password(payload.password, user.password_hash):
        raise HTTPException(400, "解除熔断需要输入账户口令")
    row = appstate.update_risk_config({"kill_switch": False})
    appstate.log("kill_switch_off", "WARN", "熔断开关已解除", actor=user.username)
    return {"ok": True, "kill_switch": False, "message": "熔断已解除，下单通道恢复", "config": _row_dict(row)}


@router.get("/audit")
def audit(db: DbSession, user: CurrentUser, limit: int = 200, level: str = "", action: str = "") -> dict:  # noqa: ARG001
    stmt = select(AuditLog).order_by(AuditLog.ts.desc()).limit(min(limit, 1000))
    if level:
        stmt = stmt.where(AuditLog.level == level.upper())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = db.execute(stmt).scalars().all()
    return {
        "items": [
            {
                "id": r.id, "ts": r.ts.isoformat() if r.ts else "",
                "actor": r.actor, "action": r.action, "level": r.level,
                "detail": r.detail, "ip": r.ip,
            }
            for r in rows
        ]
    }


@router.get("/exposure")
async def exposure(user: CurrentUser) -> dict:  # noqa: ARG001
    """当前组合敞口分布，用于风控页面可视化。"""
    from ..brokers import get_broker
    from starlette.concurrency import run_in_threadpool

    cfg = await run_in_threadpool(appstate.get_broker_settings)
    broker, mode = get_broker(cfg)
    acc = await run_in_threadpool(broker.account)
    plist = await run_in_threadpool(broker.positions)
    limits = await run_in_threadpool(appstate.risk_limits)

    by_symbol = [
        {
            "symbol": p.symbol, "market_value": p.market_value,
            "pct": round(abs(p.market_value) / acc.equity * 100, 2) if acc.equity else 0.0,
            "quantity": p.quantity, "avg_cost": p.avg_cost,
            "unrealized_pnl": p.unrealized_pnl,
            "headroom_pct": round(max(limits.max_position_pct - (abs(p.market_value) / acc.equity * 100 if acc.equity else 0), 0), 2),
        }
        for p in plist
    ]
    gross = sum(abs(p.market_value) for p in plist)
    net = sum(p.market_value for p in plist)
    long_mv = sum(p.market_value for p in plist if p.market_value > 0)
    short_mv = sum(p.market_value for p in plist if p.market_value < 0)
    return {
        "mode": mode,
        "equity": acc.equity,
        "cash": acc.cash,
        "gross_exposure": round(gross, 2),
        "gross_pct": round(gross / acc.equity * 100, 2) if acc.equity else 0.0,
        "net_exposure": round(net, 2),
        "net_pct": round(net / acc.equity * 100, 2) if acc.equity else 0.0,
        "long_value": round(long_mv, 2),
        "short_value": round(short_mv, 2),
        "positions": by_symbol,
        "usage": {
            "position_pct_used": round(max([p["pct"] for p in by_symbol], default=0.0), 2),
            "position_pct_limit": limits.max_position_pct,
            "gross_pct_used": round(gross / acc.equity * 100, 2) if acc.equity else 0.0,
            "gross_pct_limit": limits.max_gross_exposure_pct,
            "open_positions": len(by_symbol),
            "positions_limit": limits.max_open_positions,
        },
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
