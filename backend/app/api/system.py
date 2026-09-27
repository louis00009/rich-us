"""系统接口：状态、券商设置与连通性测试、审计概览。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..brokers import get_broker
from ..config import FRONTEND_DIST, RUNTIME_DIR, settings
from ..schemas import BrokerSettingsIn
from .deps import CurrentUser

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/status")
def status(user: CurrentUser) -> dict:  # noqa: ARG001
    base = appstate.system_status()
    base["runtime_dir"] = str(RUNTIME_DIR)
    base["frontend_built"] = (FRONTEND_DIST / "index.html").exists()
    base["engine_tick_sec"] = settings.engine_tick_sec
    return base


@router.get("/latency")
def latency(user: CurrentUser) -> dict:  # noqa: ARG001
    """交易路径分段延迟（p50/p95/p99 + 预算健康度）+ 最近慢请求（T-137 延迟面板）。"""
    from ..engine.latency import get_latency

    out = get_latency().summary()
    out["slow_requests"] = appstate.slow_requests()
    return out


@router.get("/broker")
def get_broker_settings(user: CurrentUser) -> dict:  # noqa: ARG001
    cfg = appstate.get_broker_settings()
    return {
        "config": cfg,
        "presets": [
            {"key": "simulated", "label": "模拟盘（内置，零风险）", "host": "-", "port": 0},
            {"key": "tws-paper", "label": "TWS 纸面", "host": "127.0.0.1", "port": settings.ibkr_paper_tws_port},
            {"key": "tws-live", "label": "TWS 实盘", "host": "127.0.0.1", "port": settings.ibkr_live_tws_port},
            {"key": "gw-paper", "label": "IB Gateway 纸面", "host": "127.0.0.1", "port": settings.ibkr_paper_gw_port},
            {"key": "gw-live", "label": "IB Gateway 实盘", "host": "127.0.0.1", "port": settings.ibkr_live_gw_port},
        ],
        "setup_guide": [
            "1. 安装并登录 TWS（或 IB Gateway），使用纸面账户登录",
            "2. TWS → 文件 → 全局配置 → API → 设置：勾选「启用 ActiveX 和 Socket 客户端」",
            "3. 取消勾选「只读 API」才能下单；如需本工具只读监控则保持勾选",
            "4. 端口：TWS 纸面 7497 / 实盘 7496；Gateway 纸面 4002 / 实盘 4001",
            "5. 在「已信任的 IP 地址」中添加 127.0.0.1（或取消「仅接受本地连接」时填本机 IP）",
            "6. 若同一时间有多个客户端连接，请为每个客户端分配不同的 client_id",
            "7. 回到本页保存并点击「测试连接」",
        ],
    }


@router.put("/broker")
def put_broker_settings(payload: BrokerSettingsIn, user: CurrentUser) -> dict:
    cfg = appstate.set_broker_settings(payload.model_dump())
    port = int(cfg.get("port", 0))
    is_live_port = port in (7496, 4001)
    appstate.log("broker_settings_update", "WARN" if is_live_port else "INFO",
                 f"券商设置更新：provider={cfg.get('provider')} {cfg.get('host')}:{port} "
                 f"readonly={cfg.get('readonly')}", actor=user.username)
    warn = ""
    if is_live_port:
        warn = "⚠️ 当前端口为实盘端口。实盘下单仍受「环境变量 + 运行时解锁 + 逐笔护栏」三道锁保护。"
    return {"ok": True, "config": cfg, "warning": warn}


@router.post("/broker/test")
async def test_broker(user: CurrentUser) -> dict:  # noqa: ARG001
    # P0-2：get_broker_settings / log 均为同步查库，走线程池避免阻塞事件循环
    cfg = await run_in_threadpool(appstate.get_broker_settings)
    broker, mode = get_broker(cfg)
    try:
        ok, msg = await run_in_threadpool(broker.connect)
    except Exception as exc:  # noqa: BLE001
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    detail = {}
    if ok:
        try:
            acc = await run_in_threadpool(broker.account)
            detail = acc.dict()
        except Exception as exc:  # noqa: BLE001
            detail = {"error": str(exc)}
    await run_in_threadpool(appstate.log, "broker_test", "INFO" if ok else "WARN",
                            f"券商连通性测试：{msg}", user.username)
    return {"ok": ok, "message": msg, "mode": mode, "provider": cfg.get("provider"), "account": detail}


@router.post("/broker/disconnect")
async def disconnect_broker(user: CurrentUser) -> dict:
    cfg = await run_in_threadpool(appstate.get_broker_settings)
    broker, _ = get_broker(cfg)
    try:
        await run_in_threadpool(broker.disconnect)
        await run_in_threadpool(appstate.log, "broker_disconnect", "INFO",
                                "已断开券商连接", user.username)
        return {"ok": True, "message": "已断开"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.get("/audit-summary")
def audit_summary(user: CurrentUser) -> dict:  # noqa: ARG001
    from sqlalchemy import func, select

    from ..database import SessionLocal
    from ..models import AuditLog, BacktestRun, Order, StrategyConfig

    with SessionLocal() as s:
        by_level = dict(s.execute(select(AuditLog.level, func.count()).group_by(AuditLog.level)).all())
        total_audit = s.query(AuditLog).count()
        orders = s.query(Order).count()
        live_orders = s.query(Order).filter(Order.mode == "live").count()
        backtests = s.query(BacktestRun).count()
        strategies = s.query(StrategyConfig).count()
    return {
        "audit_total": total_audit,
        "audit_by_level": by_level,
        "orders_total": orders,
        "live_orders": live_orders,
        "backtests": backtests,
        "custom_strategies": strategies,
    }
