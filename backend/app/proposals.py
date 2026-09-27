"""AI 交易提案（T-107）
=====================
闭环：AI 研判产出建议单（status=proposed）→ 人工在 AI 接管中心批准/拒绝
→ 批准后走**完整下单链**（熔断 → 实盘三重锁 → 风控护栏 → 券商下单 → 落库）
→ 回写 order_id + 决策日志（PROPOSED → APPROVED → ORDER）。

硬边界：
  · 提案永远只有建议权 —— 未经人工 approve 绝不产生订单；
  · approve 走的护栏与手动下单完全一致，不做任何豁免。
"""
from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import select

from .database import session_scope
from .models import AiProposal, Order
from .state import log as app_log


def create(symbol: str, action: str, size_pct: float, rationale: str,
           entry: float = 0.0, stop: float | None = None, take_profit: float | None = None,
           factors: dict | None = None, created_by: str = "ai") -> dict[str, Any]:
    """创建提案（AI 调用）。返回提案 dict。"""
    symbol = symbol.strip().upper()
    action = action.strip().upper()
    if action not in ("BUY", "SELL", "CLOSE"):
        raise ValueError(f"非法方向 {action}（仅 BUY/SELL/CLOSE）")
    if not 0 < float(size_pct) <= 100:
        raise ValueError("size_pct 必须在 (0, 100]")
    with session_scope() as s:
        row = AiProposal(
            symbol=symbol, action=action, size_pct=round(float(size_pct), 2),
            entry=round(float(entry or 0.0), 4),
            stop=round(float(stop), 4) if stop else None,
            take_profit=round(float(take_profit), 4) if take_profit else None,
            rationale=(rationale or "")[:4000],
            factors_json=json.dumps(factors or {}, ensure_ascii=False, default=str),
            created_by=created_by[:48],
        )
        s.add(row)
        s.flush()
        out = _to_dict(row)
    app_log("ai_proposal", "INFO", f"AI 提案 {symbol} {action} {size_pct:g}%（{created_by}）")
    return out


def create_from_analysis(result: dict[str, Any], model: str) -> dict[str, Any] | None:
    """AI 研判达标时自动生成提案：|综合评分| ≥ 45 且建议仓位 ≥ 5%。

    只在单标的研判时生成（组合研判语义不清晰）。
    """
    try:
        if result.get("error"):
            return None
        score = float(result.get("composite_score") or 0)
        size = float(result.get("suggested_position_pct") or 0)
        if abs(score) < 45 or size < 5:
            return None
        symbol = str(result.get("symbol", "")).upper()
        if not symbol:
            return None
        action = "BUY" if result.get("bias") == "多头" else ("SELL" if result.get("bias") == "空头" else None)
        if action is None:
            return None
        levels = result.get("levels") or {}
        sup = levels.get("支撑") or []
        res = levels.get("阻力") or []
        px = float(result.get("price") or 0)
        stop = round(min(sup) * 0.995, 4) if (sup and action == "BUY") else (round(max(res) * 1.005, 4) if (res and action == "SELL") else None)
        tp = round(max(res) * 0.995, 4) if (res and action == "BUY") else (round(min(sup) * 1.005, 4) if (sup and action == "SELL") else None)
        return create(
            symbol=symbol, action=action, size_pct=min(size, 20.0),
            rationale=f"综合评分 {score:+.1f}（{result.get('regime', '')}）｜"
                      f"维度 {json.dumps(result.get('dimensions', {}), ensure_ascii=False)}｜"
                      f"建议仓位 {size:g}%（上限 20%）",
            entry=px, stop=stop, take_profit=tp,
            factors={"score": score, "confidence": result.get("confidence"),
                     "dimensions": result.get("dimensions"), "atr_pct": result.get("atr_pct"),
                     "horizon": result.get("horizon")},
            created_by=f"ai:{model}",
        )
    except Exception:  # noqa: BLE001 —— 提案生成失败绝不影响研判主流程
        return None


def list_proposals(status: str = "", limit: int = 30) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = s.query(AiProposal).order_by(AiProposal.ts.desc(), AiProposal.id.desc())
        if status:
            q = q.filter(AiProposal.status == status)
        rows = q.limit(min(limit, 100)).all()
        return [_to_dict(r) for r in rows]


def decide(proposal_id: int, approve: bool, reviewer: str, password: str = "") -> dict[str, Any]:
    """批准 / 拒绝。批准时立即执行（走完整下单链）。

    实盘模式（IBKR 实盘端口）下批准 = 下真单，**必须再次校验账户口令**（第四道防线）；
    模拟盘无需口令。
    """
    import datetime as _dtm

    from . import state as appstate
    from .security import verify_password

    _broker_probe, exec_mode = _probe_mode()
    if approve and exec_mode == "live":
        if not password:
            raise PermissionError("实盘执行需要账户口令确认（第四道防线）")
        from .database import SessionLocal
        from .models import User

        with SessionLocal() as s:
            u = s.query(User).filter(User.username == reviewer).first()
            if u is None or not verify_password(password, u.password_hash):
                app_log("live_proposal_denied", "CRITICAL",
                        f"实盘提案 #{proposal_id} 口令校验失败", actor=reviewer)
                raise PermissionError("账户口令不正确——实盘提案未执行")

    with session_scope() as s:
        row = s.get(AiProposal, proposal_id)
        if row is None:
            raise LookupError(f"提案 {proposal_id} 不存在")
        if row.status != "proposed":
            raise ValueError(f"提案已处理（{row.status}），不能重复操作")
        # 自提案 + 自批准 = 风控隔离失效。AI 创建的提案（created_by="ai:*"）不受影响。
        if approve and row.created_by and row.created_by == reviewer:
            app_log("proposal_self_approve_denied", "WARN",
                    f"提案 #{proposal_id} 创建人 {reviewer} 试图自批准", actor=reviewer)
            raise PermissionError("不能批准自己创建的提案（自提案+自批准没有制衡）")
        row.reviewed_by = reviewer[:48]
        if not approve:
            row.status = "rejected"
            out = _to_dict(row)
        else:
            row.status = "approved"
            out = _to_dict(row)

    from .decisions import log_decision

    if approve:
        try:
            exec_res = _execute(out, reviewer)
            with session_scope() as s:
                row = s.get(AiProposal, proposal_id)
                row.status = "executed" if exec_res.get("ok") else "expired"
                row.order_id = exec_res.get("db_id")
                out = _to_dict(row)
            log_decision(
                actor=f"user:{reviewer}", action="BUY" if out["action"] == "BUY" else "SELL",
                decision=f"批准 AI 提案 #{proposal_id}：{out['symbol']} {out['action']} {out['size_pct']:g}%"
                         f" → 订单 {exec_res.get('db_id')}",
                reasoning=f"执行 {exec_res.get('status', '')}，成交 {exec_res.get('filled_qty', 0)} @ {exec_res.get('avg_price', 0)}"
                          f"（模式：{exec_mode}）",
                symbol=out["symbol"], context={"proposal_id": proposal_id, "mode": exec_mode, **exec_res},
            )
        except Exception as exc:  # noqa: BLE001
            with session_scope() as s:
                row = s.get(AiProposal, proposal_id)
                row.status = "expired"
                out = _to_dict(row)
            log_decision(
                actor=f"user:{reviewer}", action="SKIP", decision=f"AI 提案 #{proposal_id} 执行失败",
                reasoning=f"{type(exc).__name__}: {exc}", symbol=out["symbol"],
                context={"proposal_id": proposal_id},
            )
            raise
    else:
        log_decision(
            actor=f"user:{reviewer}", action="SKIP",
            decision=f"拒绝 AI 提案 #{proposal_id}：{out['symbol']} {out['action']} {out['size_pct']:g}%",
            reasoning=(out.get("rationale") or "")[:500], symbol=out["symbol"],
            context={"proposal_id": proposal_id},
        )
    return out


def _probe_mode() -> tuple[Any, str]:
    """只读探测当前券商与模式（不建连）。P1-9：与下单路由同源 —— UI 开关为权威。"""
    from . import state as appstate

    if appstate.current_mode() == "paper":
        return None, "paper"
    from .brokers import get_broker

    broker, mode = get_broker(appstate.get_broker_settings())
    return broker, mode


def _execute(prop: dict[str, Any], reviewer: str) -> dict[str, Any]:
    """执行已批准的提案：熔断 → 实盘检查 → 护栏 → 下单 → 落库（与手动下单同等护栏）。"""
    from . import state as appstate
    from .brokers import get_broker
    from .data_provider import get_quote
    from .models import Fill
    from .risk.guardrails import check_order

    symbol, action = prop["symbol"], prop["action"]
    # P1-9：与手动下单同一路由 —— UI 模式开关是权威（paper 时强制模拟券商），
    # 端口 7496 而界面显示模拟盘时绝不真实下单。
    if appstate.current_mode() == "paper":
        from .brokers import get_simulated

        broker, mode = get_simulated(), "paper"
    else:
        broker, mode = get_broker(appstate.get_broker_settings())

    if appstate.get_risk_row().kill_switch:
        raise RuntimeError("熔断开关已启用，禁止执行 AI 提案")
    if mode == "live":
        ok, reason = appstate.live_trading_available()
        if not ok:
            raise RuntimeError(f"实盘通道未就绪：{reason}")

    quote = get_quote(symbol)
    px = float(quote.get("price") or 0)
    if px <= 0:
        raise RuntimeError(f"无法获取 {symbol} 行情")

    acc = broker.account()
    if action == "CLOSE":
        pos = next((p for p in broker.positions() if p.symbol == symbol and p.quantity > 0), None)
        if pos is None:
            raise RuntimeError(f"{symbol} 无持仓可平")
        side, qty = "SELL" if pos.quantity > 0 else "BUY", abs(pos.quantity)
    else:
        if acc.equity <= 0:
            raise RuntimeError("账户权益异常")
        qty = int(math.floor(acc.equity * float(prop["size_pct"]) / 100.0 / px))
        if qty < 1:
            raise RuntimeError(f"建议仓位 {prop['size_pct']:g}% 不足以买入 1 股（权益 {acc.equity:g}，价格 {px:g}）")
        side = action

    limits = appstate.risk_limits()
    # P0-5/P1-5：统一用 state.build_guard_context —— 计数器（日内/每分钟笔数）、
    # 分市场敞口（含 HKD→base 折算）由中心化构造补齐。
    ctx = appstate.build_guard_context(acc, broker.positions())
    guard = check_order(symbol=symbol, side=side, quantity=qty, price=px, limits=limits, ctx=ctx)
    if not guard.ok:
        raise RuntimeError(f"风控护栏拒绝：{guard.reason}（{guard.code}）")
    qty = guard.adjusted_qty or qty

    result = broker.place_order(symbol, side, qty, "MKT", None, None, "DAY",
                                prop.get("take_profit"), prop.get("stop"))
    with session_scope() as s:
        row = Order(
            client_order_id=f"AIP{prop['id']}-{uuid4s()}", broker_order_id=str(result.order_id),
            mode=mode, broker=getattr(broker, "name", "simulated") or "simulated",
            symbol=symbol, side=side, quantity=qty, order_type="MKT",
            status=str(result.status or "SUBMITTED"), filled_qty=float(result.filled_qty or 0),
            avg_fill_price=float(result.avg_price or 0) or px,
            commission=result.commission or 0.0, reason=f"AI 提案 #{prop['id']}（批准人 {reviewer}）",
            currency="HKD" if symbol.endswith(".HK") else "USD",
        )
        s.add(row)
        s.flush()
        if float(result.filled_qty or 0) > 0:
            s.add(Fill(order_id=row.id, quantity=float(result.filled_qty),
                       price=float(result.avg_price or 0) or px, commission=result.commission or 0.0))
        exec_out = {"ok": bool(result.ok), "order_id": result.order_id, "db_id": row.id,
                    "status": str(result.status or ""), "filled_qty": float(result.filled_qty or 0),
                    "avg_price": float(result.avg_price or 0) or px, "qty": qty, "side": side}
    app_log("ai_proposal_exec", "INFO", f"AI 提案 #{prop['id']} 执行：{symbol} {side} {qty}", actor=reviewer)
    return exec_out


def uuid4s() -> str:
    import uuid
    return uuid.uuid4().hex[:8].upper()


def _to_dict(r: AiProposal) -> dict[str, Any]:
    return {
        "id": r.id, "ts": r.ts.isoformat() if r.ts else "",
        "symbol": r.symbol, "action": r.action, "size_pct": r.size_pct,
        "entry": r.entry, "stop": r.stop, "take_profit": r.take_profit,
        "rationale": r.rationale, "factors": json.loads(r.factors_json or "{}"),
        "status": r.status, "created_by": r.created_by, "reviewed_by": r.reviewed_by,
        "order_id": r.order_id,
    }
