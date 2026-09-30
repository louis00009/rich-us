"""EngineTask 的执行层 mixin（FILE_SIZE_DEBT Batch F-4 从 live.py 拆出）。

执行层（轻，高频）：读内存行情 + 止损 + 风控 + 下单。**不拉历史、不跑策略。**
"""
from __future__ import annotations

import datetime as dt
import time
import uuid
from typing import Any

import pandas as pd
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..brokers.base import Broker
from ..risk.guardrails import check_order
from ..risk.sizing import cap_targets, weights_to_notionals
from . import latency as lat
from .live_types import EngineTick


class _LiveExecMixin:
    """执行层：差分 → 护栏 → 下单 → 落库。"""

    async def _execute(self, dry_run: bool = False) -> EngineTick:
        """执行层：读内存行情 + 止损 + 风控 + 下单。**不拉历史、不跑策略。**"""
        t_exec = time.perf_counter()
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        tick = EngineTick(ts=ts, phase="exec")
        tick.signal_age_sec = round(self._signal_age_sec(), 3)
        tick.target_weights = dict(self.last_targets)
        try:
            # --- 风控热加载：熔断与限额调整必须即时生效 ---
            limits, kill = self._live_limits()
            if kill:
                tick.errors.append("⛔ 熔断开关已启用，本 tick 跳过全部下单（配置解除后自动恢复）")
                self._update_run_row("RUNNING", msg="熔断中：暂停下单")
                return tick
            if self.mode == "live" and not appstate.live_unlocked():
                tick.errors.append("⛔ 实盘已重新锁定，本 tick 跳过下单")
                self._update_run_row("RUNNING", msg="实盘已锁定：暂停下单")
                return tick

            symbols = list(getattr(self, "_signal_symbols", []) or [])
            if not self.last_targets or not symbols:
                tick.errors.append(self.last_signal_error or "策略尚未产生有效信号")
                return tick
            w_row = pd.Series({s: float(self.last_targets.get(s, 0.0)) for s in symbols})

            broker = self._broker()
            acc = await run_in_threadpool(broker.account)
            tick.account_equity = acc.equity
            if acc.equity <= 0:
                tick.errors.append(
                    getattr(acc, "message", "") or "账户权益为 0，无法计算仓位；请检查券商连接"
                )
                return tick

            # --- 止损优先 ---
            if not dry_run:
                stops = await run_in_threadpool(self._check_stops, broker, acc.equity)
                tick.actions.extend(stops)
                if stops:
                    acc = await run_in_threadpool(broker.account)

            plist = await run_in_threadpool(broker.positions)
            positions = {p.symbol: p for p in plist}
            peak = max(acc.equity, self._peak_equity, acc.equity - acc.day_pnl)
            self._peak_equity = peak

            # P0-5/P1-5：护栏上下文中心化构造 —— 计数器（日内/每分钟笔数）与
            # 分市场敞口（HKD→base 折算）此前从未赋值，三条风控形同虚设。
            ctx = appstate.build_guard_context(acc, plist)

            # 取行情：中枢内存优先（µs 级），缺的才走网络
            qmap = await run_in_threadpool(self._quotes, symbols)
            tick.quote_source = self.last_quotes_source

            def px_of(s: str) -> float:
                q = qmap.get(s.upper())
                if q and float(q.get("price") or 0) > 0:
                    return float(q["price"])
                p = positions.get(s)
                return float(p.last_price) if p and p.last_price else 0.0

            if self.sizing_method and self.sizing_method != "weight":
                prices = pd.Series({s: px_of(s) for s in symbols})
                targets = weights_to_notionals(
                    w_row, acc.equity, prices, self.sizing_method,
                    max_position_pct=self.max_position_pct, gross_pct=self.gross_pct,
                    risk_per_trade_pct=self.risk_per_trade_pct, stop_mult=self.stop_cfg.stop_value,
                )
            else:
                # P0-1：weight 模式同样必须施加两级组合约束。
                # 旧实现 targets = 权重 × 权益，无单标的上限、无总敞口约束 ——
                # 多标的策略输出逐标的 ±1 权重时会凭空放大杠杆。
                targets = cap_targets(
                    {s: float(w_row[s]) * acc.equity for s in symbols},
                    acc.equity, self.max_position_pct, self.gross_pct,
                )

            for sym in symbols:
                target_notional = targets.get(sym, 0.0)
                cur = positions.get(sym)
                cur_qty = cur.quantity if cur else 0.0
                px = px_of(sym)
                if px <= 0:
                    continue
                cur_notional = cur_qty * px
                delta_notional = target_notional - cur_notional
                # 调仓死区：低于权益的这个比例就不动，避免为几块钱反复交易。
                # 旧实现是硬编码的 0.005 且**静默跳过** —— 用户看到「策略有信号但没下单」
                # 完全无从排查。现在把死区做成常量，并对「明显有信号但被死区挡下」的情况
                # 显式记录一条 skipped，让界面能解释清楚。
                deadband = acc.equity * self.rebalance_deadband_pct / 100.0
                if abs(delta_notional) < deadband:
                    if abs(delta_notional) >= deadband * 0.2:
                        tick.skipped.append({
                            "symbol": sym, "side": "BUY" if delta_notional > 0 else "SELL",
                            "quantity": 0.0, "code": "BELOW_DEADBAND",
                            "reason": (
                                f"目标名义差额 {abs(delta_notional):,.0f} 低于调仓死区 "
                                f"{deadband:,.0f}（权益的 {self.rebalance_deadband_pct:g}%），"
                                f"本次不动仓"
                            ),
                        })
                    continue

                delta_qty = delta_notional / px
                side = "BUY" if delta_qty > 0 else "SELL"
                qty = abs(delta_qty)

                # ---- 手数取整（港股每手可能 100/200/400 股，必须取整）----
                lot = 1
                lot_note = ""
                try:
                    from ..markets.lots import round_qty

                    qty_r, lot, lot_note = round_qty(sym, qty, side=side)
                    qty = qty_r
                except Exception as exc:  # noqa: BLE001
                    lot_note = f"手数规则不可用：{exc}"
                if qty <= 0:
                    tick.skipped.append({
                        "symbol": sym, "side": side, "quantity": round(qty, 4),
                        "code": "LOT_TOO_SMALL",
                        "reason": f"按每手 {lot} 股取整后不足 1 手（目标名义 {target_notional:,.0f}）"
                                  + (f"；{lot_note}" if lot_note else ""),
                    })
                    continue

                t_risk = time.perf_counter()
                guard = check_order(
                    symbol=sym, side=side, quantity=qty, price=px,
                    limits=limits, ctx=ctx,
                )
                lat.get_latency().record(lat.RISK_CHECK, (time.perf_counter() - t_risk) * 1000.0)
                if not guard.ok:
                    tick.skipped.append({"symbol": sym, "side": side, "quantity": round(qty, 4),
                                         "code": guard.code, "reason": guard.reason})
                    appstate.log("guardrail_block", "WARN",
                                 f"{sym} {side} {qty:.4f} 被护栏拒绝: {guard.reason}", detail=guard.code)
                    continue
                if guard.adjusted_qty:
                    qty = guard.adjusted_qty

                if dry_run:
                    tick.actions.append({"type": "DRY_RUN", "symbol": sym, "side": side,
                                         "quantity": round(qty, 4), "lot": lot,
                                         "target_notional": round(target_notional, 2)})
                    continue

                t_order = time.perf_counter()
                res = await run_in_threadpool(broker.place_order, sym, side, qty, "MKT")
                order_ms = (time.perf_counter() - t_order) * 1000.0
                lat.get_latency().record(lat.ORDER_ROUNDTRIP, order_ms)
                tick.actions.append({
                    "type": "ORDER", "symbol": sym, "side": side, "quantity": round(qty, 4),
                    "lot": lot, "ok": res.ok, "status": res.status, "order_id": res.order_id,
                    "avg_price": res.avg_price, "message": res.message,
                    "latency_ms": getattr(res, "latency_ms", 0.0) or round(order_ms, 2),
                })
                appstate.log(
                    "engine_order", "INFO" if res.ok else "WARN",
                    f"引擎下单 {sym} {side} {qty:.4f} → {res.status}", detail=res.message,
                )
                if res.ok:
                    self._persist_order(sym, side, qty, res, px, broker=broker)
                    # P2-11：优先用券商回填的**实际成交量**推进持仓与止损规模。
                    # 旧实现一律用请求量 qty —— 未成交/部分成交时，敞口护栏与
                    # StopTracker 都按「未成交的单」计算，规模失真。
                    filled = float(getattr(res, "filled_qty", 0.0) or 0.0)
                    eff_qty = filled if filled > 0 else qty   # 券商未回填时按请求量保守估计
                    pos_after = cur_qty + (eff_qty if side == "BUY" else -eff_qty)
                    # P1-6：同一 tick 内回写风控上下文 —— 后续标的的护栏判定必须看到
                    # 本笔订单之后的敞口。旧实现 ctx 从不更新，10 只标的各 20% 目标
                    # 会全部通过检查，实际建出 200% 敞口。
                    signed_qty = qty if side == "BUY" else -qty
                    prev_mv = float(ctx.open_positions.get(sym, 0.0))
                    px_base = px
                    if sym.upper().endswith(".HK"):
                        try:
                            from ..markets import fx

                            px_base = fx.to_base(px, "HKD", "USD")
                        except Exception:  # noqa: BLE001 —— 折算失败按原值（宁高估不低估）
                            px_base = px
                    new_mv = prev_mv + signed_qty * px_base
                    ctx.open_positions[sym] = new_mv
                    ctx.gross_exposure = max(ctx.gross_exposure + abs(new_mv) - abs(prev_mv), 0.0)
                    mk = "HK" if sym.upper().endswith(".HK") else "US"
                    ctx.market_exposure[mk] = max(
                        ctx.market_exposure.get(mk, 0.0) + abs(new_mv) - abs(prev_mv), 0.0
                    )
                    ctx.orders_today += 1
                    ctx.orders_last_minute += 1
                    if abs(pos_after) < 1e-9:
                        # 已清仓 → 撤掉保护性委托，并重置止损状态
                        await run_in_threadpool(self._cancel_protective, broker, sym)
                        if sym in self.trackers:
                            self.trackers[sym].s.reset()
                    elif cur_qty == 0 or (pos_after > 0) != (cur_qty > 0):
                        # 新开仓（含反手）→ 建立止损跟踪 + 实盘挂保护性委托
                        from ..risk.stops import StopTracker

                        tr = StopTracker(self.stop_cfg, sym)
                        # P1-1：传策略 bar 序号（_bar_seq），不是执行 tick 数
                        tr.open(1 if pos_after > 0 else -1, res.avg_price or px, self._bar_seq,
                                self._atr_for(sym) or None)
                        self.trackers[sym] = tr
                        await run_in_threadpool(
                            self._place_protective, broker, sym, abs(pos_after), side, res.avg_price or px
                        )
            if not dry_run:
                await run_in_threadpool(self._snapshot_positions, broker)
        except Exception as exc:  # noqa: BLE001
            tick.errors.append(f"{type(exc).__name__}: {exc}")
            self.last_error = tick.errors[-1]
        finally:
            tick.exec_ms = round((time.perf_counter() - t_exec) * 1000.0, 2)
            self.exec_loop_ms.append(tick.exec_ms)
            lat.get_latency().record(lat.ENGINE_EXEC, tick.exec_ms)
            self.exec_count += 1
            self.tick_count += 1
            self.last_tick = ts
            self.last_tick_detail = tick
            self._log_exec_decision(tick, dry_run)
        return tick

    def _log_exec_decision(self, tick: EngineTick, dry_run: bool) -> None:
        """把本 tick 的每个决策落 decision_logs（可回溯；绝不抛异常影响交易）。"""
        try:
            from ..decisions import log_decision

            ctx = {
                "equity": tick.account_equity,
                "quote_source": tick.quote_source,
                "signal_age_sec": tick.signal_age_sec,
                "signal_recomputed": tick.signal_recomputed,
                "target_weights": tick.target_weights,
                "exec_ms": tick.exec_ms,
                "errors": tick.errors,
            }
            # 每笔实际下单单独一条（含订单号）
            for a in tick.actions:
                if a.get("type") == "ORDER":
                    log_decision(
                        actor=f"engine:{self.engine_run_id}",
                        action=a.get("side", "?"),
                        decision=f"{a.get('side')} {a.get('quantity')} {a.get('symbol')} → {a.get('status')}",
                        reasoning=(
                            f"目标权重 {tick.target_weights.get(a.get('symbol'), 0):.4f}；"
                            f"行情源 {tick.quote_source}；信号年龄 {tick.signal_age_sec}s；"
                            f"每手 {a.get('lot')} 股"
                        ),
                        symbol=a.get("symbol", ""),
                        context={**ctx, "action": a},
                        engine_run_id=self.engine_run_id,
                    )
                elif a.get("type") == "DRY_RUN":
                    log_decision(
                        actor=f"engine:{self.engine_run_id}",
                        action="DRY_RUN",
                        decision=f"（dry-run）{a.get('side')} {a.get('quantity')} {a.get('symbol')}",
                        symbol=a.get("symbol", ""),
                        context={**ctx, "action": a},
                        engine_run_id=self.engine_run_id,
                    )
            # 止损动作
            for a in tick.actions:
                if a.get("type") == "STOP":
                    log_decision(
                        actor=f"engine:{self.engine_run_id}",
                        action="STOP",
                        decision=str(a),
                        symbol=a.get("symbol", ""),
                        context=ctx,
                        engine_run_id=self.engine_run_id,
                    )
            # 被跳过的决策批量记一条（SKIP 原因是可回溯性的关键）
            if tick.skipped:
                log_decision(
                    actor=f"engine:{self.engine_run_id}",
                    action="SKIP",
                    decision="；".join(
                        f"{s.get('symbol')} {s.get('side')} {s.get('code')}" for s in tick.skipped[:10]
                    ),
                    reasoning="；".join(
                        f"[{s.get('code')}] {s.get('reason', '')[:120]}" for s in tick.skipped[:10]
                    ),
                    context={**ctx, "skipped": tick.skipped[:20]},
                    engine_run_id=self.engine_run_id,
                )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def _persist_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        res: Any,
        ref_px: float,
        order_type: str = "MKT",
        reason: str = "",
        broker: Broker | None = None,
    ) -> None:
        """落库订单与成交。

        关键：**不使用请求股数/参考价冒充成交**。IBKR 下单是异步的，返回时
        往往还是 Submitted 且 filled_qty=0；写成"已成交 qty 股 @ 参考价"会让
        用户在界面上看到与券商完全不符的成交价。

        状态取值优先级：券商最新快照 > 下单返回 > 兜底 Submitted。
        """
        from ..database import session_scope
        from ..models import Fill, Order as OrderRow

        oid = str(getattr(res, "order_id", "") or "")
        snap: dict[str, Any] = {}
        if broker is not None and oid:
            try:
                snap = broker.order_status_snapshot(oid) or {}
            except Exception:  # noqa: BLE001
                snap = {}

        filled = float(snap.get("filled", 0.0) or 0.0) or float(getattr(res, "filled_qty", 0.0) or 0.0)
        avg_px = float(snap.get("avg_price", 0.0) or 0.0) or float(getattr(res, "avg_price", 0.0) or 0.0)
        commission = float(getattr(res, "commission", 0.0) or 0.0)
        status = str(snap.get("status") or getattr(res, "status", "") or "SUBMITTED")
        # 已确认成交但券商未回价时，用参考价兜底估值（仅影响展示，不改变成交事实）
        est_price = avg_px or (float(ref_px) if filled > 0 else 0.0)

        with session_scope() as s:
            row = OrderRow(
                client_order_id=f"ENG-{uuid.uuid4().hex[:12].upper()}",
                broker_order_id=oid,
                mode=self.mode,
                broker=self._broker_name,
                symbol=symbol, side=side, quantity=qty, order_type=order_type,
                status=status,
                filled_qty=filled,
                avg_fill_price=est_price,
                commission=commission,
                strategy_id=self.strategy_id,
                reason=reason or f"实时引擎 · {self.strategy_name}",
            )
            s.add(row)
            s.flush()
            if filled > 0 and est_price > 0:
                s.add(Fill(order_id=row.id, quantity=filled, price=est_price, commission=commission))

    # ------------------------------------------------------------------
    def _snapshot_positions(self, broker: Broker) -> None:
        """把当前持仓快照落库，供跨重启对账与历史展示。"""
        from sqlalchemy import select

        from ..database import session_scope
        from ..models import PositionSnapshot

        try:
            plist = broker.positions()
        except Exception:  # noqa: BLE001
            return
        try:
            with session_scope() as s:
                for p in plist:
                    row = s.execute(
                        select(PositionSnapshot).where(
                            PositionSnapshot.mode == self.mode,
                            PositionSnapshot.symbol == p.symbol,
                        )
                    ).scalar_one_or_none()
                    if abs(p.quantity) < 1e-9:
                        if row is not None:
                            s.delete(row)
                        continue
                    if row is None:
                        row = PositionSnapshot(mode=self.mode, symbol=p.symbol)
                        s.add(row)
                    row.quantity = p.quantity
                    row.avg_cost = p.avg_cost
                    row.last_price = p.last_price
                    row.strategy_id = self.strategy_id
        except Exception:  # noqa: BLE001
            pass
