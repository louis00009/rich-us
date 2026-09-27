"""交易接口：账户、持仓、下单、模式切换、实盘解锁、实时引擎。"""
from __future__ import annotations

import datetime as dt
import json
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..brokers import get_broker, get_simulated
from ..config import LIVE_CONFIRM_PHRASE
from ..data_provider import get_quote
from ..database import session_scope
from ..engine import ACTIVE_ENGINES, EngineTask
from ..models import EngineRun, Fill, Order, RiskConfig, StrategyConfig
from ..risk.guardrails import check_order
from ..risk.stops import STOP_TYPES, StopConfig
from ..schemas import EngineStartRequest, LiveUnlockRequest, ModeSwitchRequest, OrderRequest
from ..security import verify_password
from .deps import CurrentUser, DbSession

router = APIRouter(prefix="/trading", tags=["交易"])


def _broker_and_mode() -> tuple[object, str]:
    """下单通道与模式（P1-9 统一）。

    UI 模式开关（current_mode）是权威路由：paper 状态下强制走模拟券商，
    绝不经由实盘端口下单 —— 旧实现只看端口，端口 7496 时界面显示「模拟盘」
    也会真实下单。live 开关本身仍受三重锁约束（switch_mode 先验 live_trading_available）。
    """
    if appstate.current_mode() == "paper":
        return get_simulated(), "paper"
    cfg = appstate.get_broker_settings()
    broker, mode = get_broker(cfg)
    return broker, mode


def _currency_of(symbol: str) -> str:
    """T-112：标的计价币种（US=USD / HK=HKD）。"""
    try:
        s = symbol.strip().upper()
        return "HKD" if s.endswith(".HK") else "USD"
    except Exception:  # noqa: BLE001
        return "USD"


def _persist_order_row(kw: dict) -> int:
    """订单落库（P0-2：含 commit，必须在工作线程执行，不能占用事件循环）。

    已成交则同时写入 Fill 记录。返回本地订单 id。
    """
    with session_scope() as s:
        row = Order(**kw)
        s.add(row)
        s.flush()
        oid = int(row.id)
        filled = float(kw.get("filled_qty", 0.0) or 0.0)
        price = float(kw.get("avg_fill_price", 0.0) or 0.0)
        if filled > 0 and price > 0:
            s.add(Fill(order_id=oid, quantity=filled, price=price,
                       commission=float(kw.get("commission", 0.0) or 0.0)))
        return oid


def _mark_runs_stopped(strategy_id: int | None = None) -> int:
    """把 RUNNING 的引擎记录置为 STOPPED（P0-2：含 commit，必须走工作线程）。

    strategy_id 为 None 时处理全部运行中的引擎。
    """
    with session_scope() as s:
        stmt = select(EngineRun).where(EngineRun.status == "RUNNING")
        if strategy_id is not None:
            stmt = stmt.where(EngineRun.strategy_id == strategy_id)
        rows = s.execute(stmt).scalars().all()
        now = dt.datetime.now(dt.timezone.utc)
        for r in rows:
            r.status = "STOPPED"
            r.stopped_at = now
        return len(rows)


# ==================================================================
# 账户 / 持仓 / 订单
# ==================================================================
@router.get("/account")
async def account(user: CurrentUser) -> dict:  # noqa: ARG001
    broker, mode = _broker_and_mode()
    try:
        acc = await run_in_threadpool(broker.account)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"读取账户失败：{exc}") from exc
    ok_live, reason = appstate.live_trading_available()
    data = acc.dict()
    data["configured_mode"] = mode
    data["live_ready"] = ok_live
    data["live_reason"] = reason
    return data


@router.get("/positions")
async def positions(user: CurrentUser) -> dict:  # noqa: ARG001
    broker, _ = _broker_and_mode()
    try:
        items = await run_in_threadpool(broker.positions)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"读取持仓失败：{exc}") from exc
    return {"count": len(items), "items": [p.dict() for p in items]}


@router.get("/orders")
def orders(db: DbSession, user: CurrentUser, limit: int = 100) -> dict:  # noqa: ARG001
    rows = db.execute(select(Order).order_by(Order.created_at.desc()).limit(min(limit, 500))).scalars().all()
    return {
        "items": [
            {
                "id": r.id, "client_order_id": r.client_order_id,
                "broker_order_id": r.broker_order_id, "mode": r.mode, "broker": r.broker,
                "symbol": r.symbol, "side": r.side, "quantity": r.quantity,
                "order_type": r.order_type, "limit_price": r.limit_price, "stop_price": r.stop_price,
                "status": r.status, "filled_qty": r.filled_qty, "avg_fill_price": r.avg_fill_price,
                "commission": r.commission, "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]
    }


@router.get("/open-orders")
async def open_orders(user: CurrentUser) -> dict:  # noqa: ARG001
    broker, _ = _broker_and_mode()
    fn = getattr(broker, "open_orders", None)
    if fn is None:
        return {"items": [], "note": "当前券商不支持查询挂单"}
    try:
        return {"items": await run_in_threadpool(fn)}
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "error": str(exc)}


# ==================================================================
# 下单
# ==================================================================
@router.post("/preview")
async def preview_order(payload: OrderRequest, user: CurrentUser) -> dict:  # noqa: ARG001
    """下单前预检：返回护栏判定结果与预估成本，不产生任何订单。"""
    broker, mode = _broker_and_mode()
    quote = await run_in_threadpool(get_quote, payload.symbol.upper())
    px = float(quote.get("price") or 0.0)
    if px <= 0:
        raise HTTPException(400, f"无法获取 {payload.symbol} 的行情价格")
    ref_px = float(payload.limit_price) if (payload.order_type == "LMT" and payload.limit_price) else px

    acc = await run_in_threadpool(broker.account)
    plist = await run_in_threadpool(broker.positions)
    limits = await run_in_threadpool(appstate.risk_limits)
    ctx = await run_in_threadpool(appstate.build_guard_context, acc, plist)
    guard = check_order(symbol=payload.symbol.upper(), side=payload.side,
                        quantity=payload.quantity, price=ref_px, limits=limits, ctx=ctx)
    notional = payload.quantity * ref_px
    return {
        "ok": guard.ok,
        "code": guard.code,
        "reason": guard.reason,
        "warnings": guard.warnings,
        "adjusted_qty": guard.adjusted_qty,
        "estimated": {
            "reference_price": round(ref_px, 4),
            "notional": round(notional, 2),
            "commission_estimate": round(max(notional * 0.00005, 0.35), 2),
            "pct_of_equity": round(notional / acc.equity * 100, 2) if acc.equity else 0.0,
        },
        "account_equity": acc.equity,
        "mode": mode,
        "quote": quote,
    }


@router.post("/order")
async def place_order(payload: OrderRequest, user: CurrentUser) -> dict:
    # P0-2：本函数是 async，但 appstate.* / session_scope() 都是**同步阻塞**调用
    # （内部开 session 查库、写库）。SQLite 写锁 + commit 若在事件循环线程上执行，
    # 会冻结整个进程 —— 引擎 tick、WS 推送、其他 API 全部停摆。
    # 因此所有同步 I/O 一律走 run_in_threadpool。
    broker, mode = _broker_and_mode()

    if not payload.confirm:
        raise HTTPException(400, "必须显式确认（confirm=true）才能下单")

    risk_row = await run_in_threadpool(appstate.get_risk_row)
    if risk_row.kill_switch:
        await run_in_threadpool(appstate.log, "order_blocked", "CRITICAL",
                                "熔断开关已启用，拒绝下单", user.username)
        raise HTTPException(423, "熔断开关已启用，禁止下单。请先在风控页面解除。")

    if mode == "live":
        ok, reason = await run_in_threadpool(appstate.live_trading_available)
        if not ok:
            await run_in_threadpool(appstate.log, "live_order_blocked", "CRITICAL",
                                    f"实盘下单被拒：{reason}", user.username)
            raise HTTPException(403, f"实盘通道未就绪：{reason}")

    quote = await run_in_threadpool(get_quote, payload.symbol.upper())
    px = float(quote.get("price") or 0.0)
    if px <= 0:
        raise HTTPException(400, f"无法获取 {payload.symbol} 的行情价格")
    # P2-2：合成行情（所有真实数据源都不可用时的兜底）**不得**作为下单参考价。
    # 旧实现会静默拿它算护栏金额与成交估值，且响应不回带来源 ——
    # 等于用「按标的哈希生成的假价格」下单。这里直接拒绝并留审计。
    if str(quote.get("source") or "") == "synthetic":
        await run_in_threadpool(appstate.log, "order_blocked", "CRITICAL",
                                f"{payload.symbol} 下单被拒：行情来源为合成数据（非真实行情）",
                                user.username)
        raise HTTPException(
            503,
            f"{payload.symbol} 当前仅有合成行情（所有真实数据源均不可用），已拒绝下单。"
            "请检查网络/数据源配置后重试。",
        )
    ref_px = float(payload.limit_price) if (payload.order_type == "LMT" and payload.limit_price) else px

    acc = await run_in_threadpool(broker.account)
    plist = await run_in_threadpool(broker.positions)
    limits = await run_in_threadpool(appstate.risk_limits)
    ctx = await run_in_threadpool(appstate.build_guard_context, acc, plist)
    guard = check_order(symbol=payload.symbol.upper(), side=payload.side,
                        quantity=payload.quantity, price=ref_px, limits=limits, ctx=ctx)
    if not guard.ok:
        await run_in_threadpool(
            appstate.log, "order_blocked", "WARN",
            f"{payload.symbol} {payload.side} {payload.quantity} 被护栏拒绝：{guard.reason}",
            user.username,
        )
        raise HTTPException(422, f"风控护栏拒绝：{guard.reason}（{guard.code}）")

    qty = guard.adjusted_qty or payload.quantity
    result = await run_in_threadpool(
        broker.place_order,
        payload.symbol.upper(), payload.side.upper(), qty, payload.order_type,
        payload.limit_price, payload.stop_price, payload.tif,
        payload.take_profit_price, payload.stop_loss_price,
    )

    # 状态取值优先级：券商最新快照 > 下单返回 > 兜底。绝不拿请求股数当成交。
    broker_name = getattr(broker, "name", "simulated") or "simulated"
    snap: dict = {}
    try:
        snap = broker.order_status_snapshot(str(result.order_id)) or {}
    except Exception:  # noqa: BLE001
        snap = {}
    filled = float(snap.get("filled", 0.0) or 0.0) or float(result.filled_qty or 0.0)
    avg_px = float(snap.get("avg_price", 0.0) or 0.0) or float(result.avg_price or 0.0)
    status = str(snap.get("status") or result.status or "SUBMITTED")
    # 已成交但券商未回价时用参考价兜底估值（仅影响展示）
    est_price = avg_px or (ref_px if filled > 0 else 0.0)

    order_db_id = await run_in_threadpool(_persist_order_row, {
        "client_order_id": f"UI-{uuid.uuid4().hex[:12].upper()}",
        "broker_order_id": str(result.order_id), "mode": mode,
        "broker": broker_name,
        "symbol": payload.symbol.upper(), "side": payload.side.upper(), "quantity": qty,
        "order_type": payload.order_type, "limit_price": payload.limit_price,
        "stop_price": payload.stop_price,
        "status": status, "filled_qty": filled, "avg_fill_price": est_price,
        "commission": result.commission or 0.0,
        "reason": payload.reason or "手动下单",
        "currency": _currency_of(payload.symbol),
    })

    level = "INFO" if result.ok else "WARN"
    await run_in_threadpool(appstate.log, "order_placed", level,
                            f"{payload.symbol} {payload.side} {qty:g} {payload.order_type} → {status}",
                            user.username)
    return {
        "ok": result.ok, "order_id": result.order_id, "db_id": order_db_id,
        "status": status, "message": result.message,
        "filled_qty": filled, "avg_price": avg_px,
        "commission": result.commission, "warnings": guard.warnings, "mode": mode,
        "broker": broker_name,
        # P2-2：回带行情来源，调用方才能判断参考价是否来自真实数据源
        "quote_source": str(quote.get("source") or ""),
    }


@router.post("/cancel/{order_id}")
async def cancel(order_id: str, user: CurrentUser) -> dict:
    broker, _ = _broker_and_mode()
    res = await run_in_threadpool(broker.cancel_order, order_id)
    appstate.log("order_cancel", "INFO" if res.ok else "WARN",
                 f"撤单 {order_id}: {res.message}", actor=user.username)
    return res.dict()


@router.post("/cancel-all")
async def cancel_all(user: CurrentUser) -> dict:
    """撤销当前券商连接下的全部挂单（紧急制动，无需口令）。"""
    broker, _ = _broker_and_mode()
    try:
        n = await run_in_threadpool(broker.cancel_all)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"撤单失败：{exc}") from exc
    appstate.log("cancel_all", "WARN", f"撤销全部挂单，共 {n} 笔", actor=user.username)
    return {"ok": True, "cancelled": n, "message": f"已提交撤销 {n} 笔挂单"}


@router.get("/fills")
async def fills(user: CurrentUser) -> dict:  # noqa: ARG001
    """券商侧今日成交回报（用于与本地订单表对账）。"""
    broker, _ = _broker_and_mode()
    try:
        rows = await run_in_threadpool(broker.today_fills)
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "error": str(exc)}
    return {"items": rows, "count": len(rows)}


@router.get("/broker-status")
async def broker_status(user: CurrentUser, db: DbSession) -> dict:  # noqa: ARG001
    """当前券商的详细能力与运行状态。"""
    broker, mode = _broker_and_mode()
    try:
        st = await run_in_threadpool(broker.status)
    except Exception as exc:  # noqa: BLE001
        st = {"broker": broker.name, "connected": False, "error": str(exc)}
    st["mode"] = mode
    st["configured_mode"] = mode
    return st


# ==================================================================
# 模式与实盘解锁
# ==================================================================
@router.get("/mode")
def get_mode(user: CurrentUser) -> dict:  # noqa: ARG001
    ok, reason = appstate.live_trading_available()
    cfg = appstate.get_broker_settings()
    return {
        # P1-9：mode = 实际下单通道（UI 开关 ∧ 端口），与口令门控、下单路由同源；
        # ui_mode 是 UI 开关本身（重启后回到 paper）。
        "mode": appstate.effective_mode(),
        "ui_mode": appstate.current_mode(),
        "broker": cfg.get("provider"),
        "port": cfg.get("port"),
        "live_env_gate": bool(appstate.app_settings.allow_live_trading),
        "live_unlocked": appstate.live_unlocked(),
        "live_ready": ok,
        "live_reason": reason,
        "confirm_phrase": LIVE_CONFIRM_PHRASE,
    }


@router.post("/mode")
def switch_mode(payload: ModeSwitchRequest, user: CurrentUser, db: DbSession) -> dict:
    if payload.mode == "live":
        ok, reason = appstate.live_trading_available()
        if not ok:
            appstate.log("mode_switch_blocked", "CRITICAL", f"切换到实盘被拒：{reason}", actor=user.username)
            raise HTTPException(403, f"无法切换到实盘：{reason}")
        appstate.set_current_mode("live")
        appstate.log("mode_switch", "CRITICAL", "⚠️ 已切换到实盘模式", actor=user.username)
        return {"ok": True, "mode": "live", "message": "已切换到实盘模式，请务必确认风控参数"}

    # P2 清理：旧实现 `row.kill_switch = row.kill_switch` 自赋值死代码且 session 从不
    # commit —— 整段无效果，直接删除（切 paper 的降锁动作在 set_current_mode 内）。
    appstate.set_current_mode("paper")
    appstate.log("mode_switch", "INFO", "已切换到模拟盘模式", actor=user.username)
    return {"ok": True, "mode": "paper", "message": "已切换到模拟盘模式"}


@router.post("/live-unlock")
def live_unlock(payload: LiveUnlockRequest, user: CurrentUser) -> dict:
    from ..config import settings as app_settings

    if not app_settings.allow_live_trading:
        raise HTTPException(
            403,
            "第一道锁未开启：请先设置环境变量 QD_ALLOW_LIVE_TRADING=true 并重启服务",
        )
    # 锁定（enable=False）是「降险」操作，不设门槛——
    # 若锁定也要口令，就等于让减少风险比增加风险更难，安全方向反了。
    if payload.enable:
        if payload.confirm_phrase.strip() != LIVE_CONFIRM_PHRASE:
            appstate.log("live_unlock_failed", "CRITICAL", "确认短语不正确", actor=user.username)
            raise HTTPException(400, f"确认短语不正确，必须逐字输入：{LIVE_CONFIRM_PHRASE}")
        if not payload.password or not verify_password(payload.password, user.password_hash):
            appstate.log("live_unlock_failed", "CRITICAL", "账户口令校验失败", actor=user.username)
            raise HTTPException(400, "账户口令不正确")

    appstate.set_live_unlocked(payload.enable)
    if payload.enable:
        appstate.log("live_unlocked", "CRITICAL", "⚠️ 实盘已解锁（第二道锁开启）", actor=user.username)
        return {"ok": True, "live_unlocked": True, "message": "实盘已解锁。请复核券商端口与风控参数后再切换模式。"}
    appstate.log("live_locked", "INFO", "实盘已重新锁定", actor=user.username)
    return {"ok": True, "live_unlocked": False, "message": "实盘已锁定"}


# ==================================================================
# 实时引擎
# ==================================================================
@router.get("/engine")
def engine_status(db: DbSession, user: CurrentUser) -> dict:  # noqa: ARG001
    rows = db.execute(select(EngineRun).order_by(EngineRun.started_at.desc()).limit(30)).scalars().all()
    live = {
        rid: {
            "running": t.running, "tick_count": t.tick_count, "last_tick": t.last_tick,
            "last_error": t.last_error, "targets": t.last_targets,
            "last_detail": (t.last_tick_detail.__dict__ if t.last_tick_detail else None),
            # 双层节奏 + 事件驱动的运行时指标（前端延迟面板直接消费）
            "runtime": t.runtime_stats(),
        }
        for rid, t in ACTIVE_ENGINES.items()
    }
    return {
        "runs": [
            {
                "id": r.id, "strategy_id": r.strategy_id, "mode": r.mode, "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else "",
                "stopped_at": r.stopped_at.isoformat() if r.stopped_at else None,
                "last_tick": r.last_tick.isoformat() if r.last_tick else None,
                "tick_count": r.tick_count, "message": r.message,
            }
            for r in rows
        ],
        "active": live,
    }


@router.post("/engine/start")
async def engine_start(payload: EngineStartRequest, user: CurrentUser, db: DbSession) -> dict:
    # P0-2：本函数是 async，但 DB / 审计都是同步阻塞调用，一律走线程池。
    # 注意 task.start() 必须留在事件循环线程 —— 它内部调用 asyncio.create_task()，
    # 若在线程池里执行则没有运行中的事件循环，会直接抛 RuntimeError。
    risk_row = await run_in_threadpool(appstate.get_risk_row)
    if risk_row.kill_switch:
        raise HTTPException(423, "熔断开关已启用，无法启动引擎")

    cfg = await run_in_threadpool(db.get, StrategyConfig, payload.strategy_id)
    if not cfg:
        raise HTTPException(404, "策略不存在")
    if cfg.id in ACTIVE_ENGINES and ACTIVE_ENGINES[cfg.id].running:
        raise HTTPException(409, "该策略的引擎已在运行")

    mode = payload.mode
    if mode == "live":
        ok, reason = await run_in_threadpool(appstate.live_trading_available)
        if not ok:
            await run_in_threadpool(appstate.log, "engine_live_blocked", "CRITICAL",
                                    f"实盘引擎启动被拒：{reason}", user.username)
            raise HTTPException(403, f"无法以实盘模式启动引擎：{reason}")

    def _j(s: str, d):  # noqa: ANN001
        try:
            return json.loads(s) if s else d
        except json.JSONDecodeError:
            return d

    stop_cfg = StopConfig(
        stop_type=risk_row.stop_type, stop_value=risk_row.stop_value,
        take_profit_r=risk_row.take_profit_r, time_stop_bars=risk_row.time_stop_bars,
    )
    if stop_cfg.stop_type not in STOP_TYPES:
        stop_cfg.stop_type = "none"

    def _create_run() -> int:
        run = EngineRun(strategy_id=cfg.id, mode=mode, status="RUNNING")
        db.add(run)
        db.commit()
        db.refresh(run)
        return int(run.id)

    run_id = await run_in_threadpool(_create_run)
    limits = await run_in_threadpool(appstate.risk_limits)

    task = EngineTask(
        engine_run_id=run_id, strategy_id=cfg.id, strategy_name=cfg.name,
        spec_key=cfg.strategy_key, params=_j(cfg.params_json, {}),
        rule=_j(cfg.rule_json, None), code=cfg.code or "",
        symbols=_j(cfg.symbols_json, []) or ["SPY"],
        mode=mode, interval_sec=payload.interval_sec,
        exec_interval_sec=payload.exec_interval_sec,
        exec_mode=payload.exec_mode,
        stop_cfg=stop_cfg, limits=limits,
        sizing_method=risk_row.sizing_method,
        risk_per_trade_pct=risk_row.risk_per_trade_pct,
        max_position_pct=risk_row.max_position_pct,
        gross_pct=risk_row.max_gross_exposure_pct,
        place_protective=payload.place_protective,
    )
    ACTIVE_ENGINES[cfg.id] = task
    task.start()          # 必须在事件循环线程执行（内部 asyncio.create_task）
    level = "CRITICAL" if mode == "live" else "INFO"
    await run_in_threadpool(
        appstate.log, "engine_start_request", level,
        f"{'⚠️ 实盘' if mode == 'live' else '模拟盘'}引擎启动：{cfg.name}"
        f"（信号 {payload.interval_sec:g}s / 执行 {payload.exec_interval_sec:g}s"
        f" · {payload.exec_mode}，保护性委托={payload.place_protective}）",
        user.username,
    )
    return {
        "ok": True, "run_id": run_id, "strategy_id": cfg.id, "mode": mode,
        "exec_mode": payload.exec_mode,
        "exec_interval_sec": payload.exec_interval_sec,
        "message": f"引擎已启动：{cfg.name}（{'实盘 ⚠️' if mode == 'live' else '模拟盘'}）",
    }


@router.post("/engine/stop-all")
async def engine_stop_all(user: CurrentUser, db: DbSession) -> dict:
    """一键停止全部运行中的引擎（紧急情况使用）。"""
    stopped = []
    for sid in list(ACTIVE_ENGINES.keys()):
        task = ACTIVE_ENGINES.pop(sid, None)
        if task is None:
            continue
        await task.stop()
        stopped.append(task.strategy_name)
    await run_in_threadpool(_mark_runs_stopped)
    await run_in_threadpool(appstate.log, "engine_stop_all", "WARN",
                            f"一键停止全部引擎（{len(stopped)} 个）：{', '.join(stopped) or '无'}",
                            user.username)
    return {"ok": True, "stopped": stopped, "message": f"已停止 {len(stopped)} 个引擎"}


@router.post("/engine/stop/{strategy_id}")
async def engine_stop(strategy_id: int, user: CurrentUser, db: DbSession) -> dict:
    task = ACTIVE_ENGINES.get(strategy_id)
    if not task:
        raise HTTPException(404, "该策略没有正在运行的引擎")
    await task.stop()
    ACTIVE_ENGINES.pop(strategy_id, None)
    await run_in_threadpool(_mark_runs_stopped, strategy_id)
    await run_in_threadpool(appstate.log, "engine_stop_request", "INFO",
                            f"停止引擎 strategy_id={strategy_id}", user.username)
    return {"ok": True, "message": "引擎已停止"}


@router.post("/engine/dry-run/{strategy_id}")
async def engine_dry_run(strategy_id: int, user: CurrentUser, db: DbSession) -> dict:
    """演练：只计算将要下发的订单，不实际执行。

    刻意**不复用正在运行的引擎实例**——那会污染它的 tick_count / last_tick，
    并与后台循环并发访问同一份状态。这里每次构造一次性实例。
    """
    cfg = await run_in_threadpool(db.get, StrategyConfig, strategy_id)
    if not cfg:
        raise HTTPException(404, "策略不存在")
    risk_row = await run_in_threadpool(appstate.get_risk_row)

    def _j(s: str, d):  # noqa: ANN001
        try:
            return json.loads(s) if s else d
        except json.JSONDecodeError:
            return d

    running = ACTIVE_ENGINES.get(strategy_id)
    mode = running.mode if running is not None else "paper"
    spec = EngineTask(
        engine_run_id=0, strategy_id=cfg.id, strategy_name=cfg.name,
        spec_key=cfg.strategy_key, params=_j(cfg.params_json, {}),
        rule=_j(cfg.rule_json, None), code=cfg.code or "",
        symbols=_j(cfg.symbols_json, []) or ["SPY"],
        mode=mode, interval_sec=60,
        stop_cfg=StopConfig(stop_type=risk_row.stop_type, stop_value=risk_row.stop_value,
                            take_profit_r=risk_row.take_profit_r,
                            time_stop_bars=risk_row.time_stop_bars),
        limits=await run_in_threadpool(appstate.risk_limits),
        sizing_method=risk_row.sizing_method,
        risk_per_trade_pct=risk_row.risk_per_trade_pct,
        max_position_pct=risk_row.max_position_pct,
        gross_pct=risk_row.max_gross_exposure_pct,
    )
    tick = await spec.run_once(dry_run=True)
    await run_in_threadpool(appstate.log, "engine_dry_run", "INFO",
                            f"策略 {cfg.name} 演练完成", user.username)
    return {
        "ok": True,
        "reused_running_engine": False,
        "ts": tick.ts,
        "account_equity": tick.account_equity,
        "target_weights": tick.target_weights,
        "planned_orders": tick.actions,
        "blocked": tick.skipped,
        "errors": tick.errors,
    }


# ==================================================================
# 模拟账户
# ==================================================================
@router.post("/sim/reset")
def sim_reset(user: CurrentUser, cash: float = 100_000.0) -> dict:
    sim = get_simulated()
    sim.reset(cash)
    appstate.log("sim_reset", "WARN", f"重置模拟账户，初始资金 ${cash:,.0f}", actor=user.username)
    return {"ok": True, "message": f"模拟账户已重置为 ${cash:,.0f}"}
