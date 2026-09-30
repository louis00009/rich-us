"""IBKR 下单/回报域 mixin（FILE_SIZE_DEBT Batch F-2 从 ibkr.py 拆出）。

OCO 止盈止损、事件驱动成交确认、异步落库（写线程是 IB 事件线程的唯一出口）。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import queue
import threading
import time
from typing import Any, Callable

import pandas as pd

from ..markets import symbols as mksym
from ..markets.registry import get_market
from .base import AccountSnapshot, Broker, BrokerError, OrderResult, PositionItem, Tick
from .ibkr_common import BAR_MAP, INDEX_MAP, _ContractSpec, _silent
from .pacing import CircuitBreaker, Pacer
def _apply_status_snapshot(row: Any, snap: dict) -> None:
    """把券商回报的状态快照写入订单行（仅覆盖非空字段）。"""
    if not snap:
        return
    if snap.get("status"):
        row.status = str(snap["status"])
    if snap.get("filled") is not None:
        row.filled_qty = float(snap["filled"])
    if snap.get("avg_price"):
        row.avg_fill_price = float(snap["avg_price"])



class IbkrOrderMixin:
    def _on_order_status(self, trade: Any) -> None:
        """订单状态变化 → 更新内存 + 投递到写队列（**不在此处写数据库**）。

        注意「回调先于落库」的竞态：IBKR 可能在订单行写入数据库之前就推送状态，
        此时查不到行。这里把快照存进 `_pending_status`，由落库方回放
        （见 `order_status_snapshot` / `engine.live._persist_order`）。
        """
        t0 = time.perf_counter_ns()
        try:
            oid = str(getattr(trade.order, "orderId", ""))
            if not oid:
                return
            self._orders[oid] = trade
            snap = self._status_from_trade(trade)
            prev = self._pending_status.get(oid) or {}
            self._pending_status[oid] = snap

            # 成交进度达成 → 唤醒 place_order 的等待方（事件驱动，不再固定 sleep）
            filled = float(snap.get("filled", 0.0) or 0.0)
            status = str(snap.get("status", "") or "")
            if filled > 0 or status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                ev = self._fill_events.get(oid)
                if ev is not None:
                    ev.set()

            # 只有在「成交数量真的增加」时才投递落库任务
            if filled > float(prev.get("filled", 0.0) or 0.0):
                self._enqueue_write({"kind": "order_status", "order_id": oid, "snap": snap})
        except Exception as exc:  # noqa: BLE001
            self.stats["events_dropped"] += 1
            self._last_error = f"订单回报处理异常：{type(exc).__name__}: {exc}"
        finally:
            self._record_report_latency(t0)

    # ---------------- 成交明细 / 佣金 ----------------

    def _on_exec_details(self, trade: Any, fill: Any) -> None:
        """成交回报。回调内只做内存登记，落库交给写线程。"""
        t0 = time.perf_counter_ns()
        try:
            ex = getattr(fill, "execution", None)
            if ex is None:
                # ib_async 某些版本的签名是 (trade, fill)，fill 即 Execution
                ex = fill if getattr(fill, "execId", None) else None
            if ex is None:
                return
            exec_id = str(getattr(ex, "execId", "") or "")
            if exec_id and not self._remember_exec(exec_id):
                return      # 同一笔重复回报 → 丢弃（IB 会重放，去重是必须的）
            oid = str(getattr(ex, "orderId", "") or "")
            contract = getattr(trade, "contract", None) or getattr(fill, "contract", None)
            symbol, market, currency = (
                self.display_symbol(contract) if contract is not None else ("", "US", "USD")
            )
            snap = {
                "exec_id": exec_id,
                "order_id": oid,
                "symbol": symbol,
                "market": market,
                "currency": currency,
                "side": str(getattr(ex, "side", "") or ""),
                "shares": float(getattr(ex, "shares", 0.0) or 0.0),
                "price": float(getattr(ex, "price", 0.0) or 0.0),
                "time": str(getattr(ex, "time", "") or ""),
                "exchange": str(getattr(ex, "exchange", "") or ""),
            }
            self.stats["fills_seen"] += 1
            self._last_fill = snap
            self._enqueue_write({"kind": "exec", "snap": snap})
        except Exception as exc:  # noqa: BLE001
            self.stats["events_dropped"] += 1
            self._last_error = f"成交回报处理异常：{type(exc).__name__}: {exc}"
        finally:
            self._record_report_latency(t0)

    def _on_commission(self, trade: Any, fill: Any, report: Any) -> None:
        """佣金回报。IB 的佣金是**成交之后异步**推送的，所以本地订单行先落库、
        佣金到位后再补记。"""
        try:
            ex = getattr(fill, "execution", None) or fill
            exec_id = str(getattr(ex, "execId", "") or "")
            comm = float(getattr(report, "commission", 0.0) or 0.0)
            currency = str(getattr(report, "currency", "") or "")
            self._enqueue_write({
                "kind": "commission",
                "exec_id": exec_id,
                "order_id": str(getattr(ex, "orderId", "") or ""),
                "commission": comm,
                "currency": currency,
            })
        except Exception as exc:  # noqa: BLE001
            self.stats["events_dropped"] += 1
            self._last_error = f"佣金回报处理异常：{type(exc).__name__}: {exc}"

    def _remember_exec(self, exec_id: str) -> bool:
        """登记 execId；已见过返回 False。用列表做 FIFO 裁剪，避免集合无限增长。"""
        with self._exec_lock:
            if exec_id in self._exec_seen:
                return False
            self._exec_seen.add(exec_id)
            self._exec_seen_order.append(exec_id)
            while len(self._exec_seen_order) > 5000:
                old = self._exec_seen_order.pop(0)
                self._exec_seen.discard(old)
            return True

    # ================================================================
    # 延迟埋点（IB 回调线程内，必须极轻）
    # ================================================================

    def _record_report_latency(self, t0: int) -> None:
        """IB 回调处理耗时埋点。

        为什么必须测这一段：IB 的所有回调都跑在**同一个事件线程**上。
        回调里只要有一次卡 50ms（比如同步写 SQLite），后续所有行情与回报
        都会被排队推迟 —— 这是毫秒级目标最隐蔽的杀手。
        预算 1ms，超了就是代码在回调里干了重活。
        埋点自身必须零风险：任何异常都吞掉，绝不能因为埋点把回报链搞坏。
        """
        try:
            from ..engine import latency as _lat
            _lat.get_latency().record_ns(_lat.EXEC_REPORT, time.perf_counter_ns() - t0)
        except Exception:  # noqa: BLE001
            pass

    # ================================================================
    # 异步落库（IB 事件线程的唯一出口）
    # ================================================================

    def _ensure_writer(self) -> None:
        if self._writer and self._writer.is_alive():
            return
        self._writer_stop.clear()
        self._writer = threading.Thread(target=self._writer_loop, name="ibkr-writer", daemon=True)
        self._writer.start()

    def _enqueue_write(self, job: dict) -> None:
        self._ensure_writer()
        try:
            self._write_q.put_nowait(job)
        except queue.Full:
            # 队列满说明数据库跟不上；宁可丢回报也不能阻塞 IB 事件线程
            self.stats["events_dropped"] += 1

    def _writer_loop(self) -> None:
        while not self._writer_stop.is_set():
            try:
                job = self._write_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._apply_write(job)
            except Exception as exc:  # noqa: BLE001
                self.stats["events_dropped"] += 1
                self._last_error = f"回报落库失败：{type(exc).__name__}: {exc}"
            finally:
                try:
                    self._write_q.task_done()
                except Exception:  # noqa: BLE001
                    pass

    def _apply_write(self, job: dict) -> None:
        kind = job.get("kind")
        from ..database import session_scope
        from ..models import Fill, Order as OrderRow

        if kind == "order_status":
            # 只更新订单行状态；**成交明细由 execDetails 负责**。
            # 旧实现用「状态里的 filled 减去行里的 filled_qty」来推增量成交，
            # 一旦同一笔被多次回报（IB 会重放），就会重复记账。
            oid = job["order_id"]
            with session_scope() as s:
                row = (
                    s.query(OrderRow)
                    .filter(OrderRow.broker_order_id == oid, OrderRow.broker == "ibkr")
                    .order_by(OrderRow.id.desc())
                    .first()
                )
                if not row:
                    return          # 订单行尚未落库，等待落库后回放
                _apply_status_snapshot(row, job["snap"])
            return

        if kind == "exec":
            snap = job["snap"]
            oid = snap.get("order_id") or ""
            with session_scope() as s:
                row = (
                    s.query(OrderRow)
                    .filter(OrderRow.broker_order_id == str(oid), OrderRow.broker == "ibkr")
                    .order_by(OrderRow.id.desc())
                    .first()
                )
                if not row:
                    return
                s.add(Fill(
                    order_id=row.id,
                    quantity=float(snap.get("shares", 0.0) or 0.0),
                    price=float(snap.get("price", 0.0) or 0.0),
                    commission=0.0,
                ))
            return

        if kind == "commission":
            comm = float(job.get("commission", 0.0) or 0.0)
            if not comm:
                return
            oid = str(job.get("order_id") or "")
            with session_scope() as s:
                row = (
                    s.query(OrderRow)
                    .filter(OrderRow.broker_order_id == oid, OrderRow.broker == "ibkr")
                    .order_by(OrderRow.id.desc())
                    .first()
                )
                if not row:
                    return
                last = (
                    s.query(Fill).filter(Fill.order_id == row.id)
                    .order_by(Fill.id.desc()).first()
                )
                if last is None:
                    return
                last.commission = round(float(last.commission or 0.0) + comm, 4)
            return

    def drain_writes(self, timeout: float = 2.0) -> bool:
        """等待写队列清空（测试/关停时用）。"""
        if self._writer is None:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._write_q.empty():
                return True
            time.sleep(0.01)
        return self._write_q.empty()

    @staticmethod
    def _status_from_trade(trade: Any) -> dict[str, float | str]:
        st = getattr(trade, "orderStatus", None)
        if st is None:
            return {}
        return {
            "status": str(getattr(st, "status", "") or ""),
            "filled": float(getattr(st, "filled", 0.0) or 0.0),
            "avg_price": float(getattr(st, "avgFillPrice", 0.0) or 0.0),
            "remaining": float(getattr(st, "remaining", 0.0) or 0.0),
        }

    def order_status_snapshot(self, order_id: str) -> dict | None:
        """返回该订单在券商侧的最新状态快照（落库时回放用）。

        有活跃 trade 时取其当前状态；否则回退到最近一次回调暂存的快照。
        """
        oid = str(order_id or "")
        if not oid:
            return None
        trade = self._orders.get(oid)
        if trade is not None:
            snap = self._status_from_trade(trade)
            if snap:
                return snap
        return dict(self._pending_status.get(oid) or {}) or None

    # ================================================================
    # 合约解析
    # ================================================================

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        take_profit_price: float | None = None,
        stop_loss_price: float | None = None,
        wait_fill: bool = True,
    ) -> OrderResult:
        """下单。**不再有固定 sleep**。

        旧实现在提交后 `sleep(0.8)` 再读状态：一次 10 标的调仓就是 8 秒起步，
        与「毫秒级」完全矛盾。现在改为：
          1. `placeOrder` 返回（拿到 orderId）即为「已被 IB 受理」，立刻返回；
          2. 若 `wait_fill=True`，用 `orderStatusEvent` 事件等待成交，
             上限 `fill_timeout`（默认 2s），而不是固定阻塞；
          3. 超时不算失败 —— 后续成交由回调异步回填。

        往返耗时记入 `OrderResult.latency_ms` 与 `raw.submit_ms`，供延迟面板统计。

        多市场差异（此前一律按美股处理）：
          · 港股无原生市价单 → 自动转成「进取限价单」（买挂卖一之上 / 卖挂买一之下）
          · TIF 白名单随市场变化（港股只有 DAY / GTC）
          · 提示文案的币种符号随市场变化（HK$ / US$）
        """
        t_start = time.perf_counter()
        if self.readonly:
            return OrderResult(
                False,
                message="当前为只读模式（readonly=True），无法下单。请在「系统设置 → 券商连接」关闭只读。",
            )
        ib_async = self._import_ib()
        try:
            self._require()
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        try:
            ref = mksym.parse(symbol)
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, message=f"无法识别的标的：{symbol!r}（{exc}）")
        sym = ref.symbol
        mkt = get_market(ref.market)
        csym = mkt.currency_symbol

        side = side.upper()
        qty = abs(float(quantity))
        if qty <= 0:
            return OrderResult(False, message="数量必须大于 0")
        if order_type == "STP" and not stop_price:
            return OrderResult(False, message="止损单必须提供 stop_price")
        if order_type in ("LMT", "STP_LMT") and not limit_price:
            return OrderResult(False, message="限价单必须提供 limit_price")

        # ---- 港股：市价单 → 进取限价单 ----
        market_order_simulated = False
        eff_type = order_type
        eff_limit = limit_price
        if order_type == "MKT" and not mkt.native_market_order:
            tick = self.get_tick(sym)
            if tick is None:
                try:
                    rows = self._snapshot_once([sym], self.market_data_type)
                    tick = None if not rows else Tick(
                        symbol=sym,
                        price=float(rows[0].get("price") or 0.0),
                        bid=rows[0].get("bid"),
                        ask=rows[0].get("ask"),
                    )
                except Exception:  # noqa: BLE001
                    tick = None
            px = None
            if tick is not None:
                px = (tick.ask if side == "BUY" else tick.bid) or (tick.price or None)
            if not px or px <= 0:
                return OrderResult(
                    False,
                    message=(
                        f"{mkt.name}不支持市价单，且当前拿不到盘口价，无法构造进取限价单。"
                        f"请改用限价单并显式指定价格。"
                    ),
                )
            from ..markets.lots import round_price as _round_price

            buffer = max(px * 0.003, mkt.tick_size * 5)
            eff_limit = _round_price(
                sym, px + buffer if side == "BUY" else max(px - buffer, mkt.tick_size)
            )
            eff_type = "LMT"
            market_order_simulated = True

        # ---- TIF 白名单随市场变化 ----
        tif_u = str(tif or "DAY").upper()
        if tif_u not in mkt.allowed_tif:
            return OrderResult(
                False,
                message=f"{mkt.name}不支持 TIF={tif_u}（允许：{'、'.join(sorted(mkt.allowed_tif))}）",
            )

        try:
            contract = self._contract(sym)

            def build(side_: str, qty_: float, kind: str) -> Any:
                if kind == "MKT":
                    return ib_async.MarketOrder(side_, qty_)
                if kind == "LMT":
                    return ib_async.LimitOrder(side_, qty_, float(eff_limit))
                if kind == "STP":
                    return ib_async.StopOrder(side_, qty_, float(stop_price))
                return ib_async.StopLimitOrder(side_, qty_, float(limit_price), float(stop_price))

            parent = build(side, qty, eff_type)
            parent.tif = tif_u
            parent.outsideRth = not self.use_rth
            parent.transmit = not (take_profit_price or stop_loss_price)

            parent_trade = self._call(self._ib.placeOrder, contract, parent)
            trades: list[Any] = [parent_trade]
            oid = str(getattr(parent_trade.order, "orderId", ""))

            # 括号单：主单成交后挂出止盈与止损（OCO 互斥）
            if take_profit_price or stop_loss_price:
                opp = "SELL" if side == "BUY" else "BUY"
                tag = ref.ib_symbol.replace(" ", "")
                oca = f"QD-{tag}-{dt.datetime.now().strftime('%H%M%S%f')[:12]}"
                children: list[Any] = []
                if take_profit_price:
                    tp = ib_async.LimitOrder(opp, qty, float(take_profit_price))
                    tp.tif = "GTC"
                    tp.parentId = parent.orderId
                    tp.ocaGroup = oca
                    tp.ocaType = 1
                    tp.outsideRth = not self.use_rth
                    tp.transmit = bool(stop_loss_price)
                    children.append(self._call(self._ib.placeOrder, contract, tp))
                if stop_loss_price:
                    sl = ib_async.StopOrder(opp, qty, float(stop_loss_price))
                    sl.tif = "GTC"
                    sl.parentId = parent.orderId
                    sl.ocaGroup = oca
                    sl.ocaType = 1
                    sl.outsideRth = not self.use_rth
                    sl.transmit = True
                    children.append(self._call(self._ib.placeOrder, contract, sl))
                if not take_profit_price and stop_loss_price and children:
                    parent.transmit = True
                    self._call(self._ib.placeOrder, contract, parent)
                trades.extend(children)

            for t in trades:
                tid = str(getattr(t.order, "orderId", ""))
                if tid:
                    self._orders[tid] = t

            submitted_ms = (time.perf_counter() - t_start) * 1000.0
            # 埋点：本地构造 + 提交到 IB（不含券商撮合）。预算 5ms。
            try:
                from ..engine import latency as _lat
                _lat.get_latency().record(_lat.ORDER_SUBMIT, submitted_ms)
            except Exception:  # noqa: BLE001
                pass

            st = parent_trade.orderStatus
            status = str(getattr(st, "status", "Submitted") or "Submitted")
            filled = float(getattr(st, "filled", 0.0) or 0.0)
            avg = float(getattr(st, "avgFillPrice", 0.0) or 0.0)

            # ---- 事件驱动等待成交（替代固定 sleep(0.8)）----
            waited = False
            if wait_fill and oid and filled <= 0 and status not in ("Cancelled", "Inactive"):
                ev = self._fill_events.setdefault(oid, threading.Event())
                deadline = time.monotonic() + self.fill_timeout
                while not ev.wait(timeout=0.02):
                    if time.monotonic() >= deadline:
                        break
                waited = True
                st = parent_trade.orderStatus
                status = str(getattr(st, "status", status) or status)
                filled = float(getattr(st, "filled", 0.0) or 0.0)
                avg = float(getattr(st, "avgFillPrice", 0.0) or 0.0)

            latency_ms = (time.perf_counter() - t_start) * 1000.0
            self.stats["orders_placed"] += 1
            self._last_order_latency_ms = {
                "submit_ms": round(submitted_ms, 2),
                "total_ms": round(latency_ms, 2),
                "waited_for_fill": waited,
                "filled": filled,
            }
            if oid:
                self._fill_events.pop(oid, None)

            extras = []
            if take_profit_price:
                extras.append(f"止盈 {csym}{take_profit_price:g}")
            if stop_loss_price:
                extras.append(f"止损 {csym}{stop_loss_price:g}")
            type_txt = f"MKT→进取限价 {csym}{eff_limit:g}" if market_order_simulated else order_type
            return OrderResult(
                True, order_id=oid, status=status,
                message=(
                    f"已提交 IBKR 订单 {side} {qty:g} {sym}（{type_txt}"
                    + ("，" + "，".join(extras) if extras else "")
                    + f"）· 提交 {submitted_ms:.0f}ms / 往返 {latency_ms:.0f}ms"
                ),
                filled_qty=filled, avg_price=avg,
                latency_ms=round(latency_ms, 2),
                raw={
                    "permId": str(getattr(parent_trade.order, "permId", "")),
                    "tif": tif_u,
                    "oca": bool(extras),
                    "childOrders": len(trades) - 1,
                    "market": ref.market,
                    "currency": ref.currency,
                    "market_order_simulated": market_order_simulated,
                    "submit_ms": round(submitted_ms, 2),
                },
            )
        except BrokerError as exc:
            self.stats["orders_rejected"] += 1
            return OrderResult(False, message=str(exc))
        except Exception as exc:  # noqa: BLE001
            self.stats["orders_rejected"] += 1
            return OrderResult(False, message=f"下单失败：{type(exc).__name__}: {exc}")

    def cancel_order(self, order_id: str) -> OrderResult:
        try:
            self._require()
        except BrokerError as exc:
            return OrderResult(False, order_id=order_id, message=str(exc))
        try:
            for t in self._call(self._ib.openTrades):
                cands = {str(t.order.orderId), str(getattr(t.order, "permId", ""))}
                if str(order_id) in cands:
                    self._call(self._ib.cancelOrder, t.order)
                    return OrderResult(True, order_id=order_id, status="Cancelled", message="撤单已提交")
            return OrderResult(False, order_id=order_id, message="未找到该订单（可能已成交或已撤销）")
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, order_id=order_id, message=f"撤单失败: {exc}")

    def cancel_all(self) -> int:
        """撤销该客户端下的全部挂单。紧急情况下很有用。"""
        try:
            self._require()
            trades = self._call(self._ib.openTrades)
            n = 0
            for t in trades:
                try:
                    self._call(self._ib.cancelOrder, t.order)
                    n += 1
                except Exception:  # noqa: BLE001
                    continue
            return n
        except Exception:  # noqa: BLE001
            return 0
