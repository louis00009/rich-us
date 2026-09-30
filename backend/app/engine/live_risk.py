"""EngineTask 的风控/止损 mixin（FILE_SIZE_DEBT Batch F-4 从 live.py 拆出）。

⚠️ 铁律 3：止损状态机唯一 —— `_check_stops` 必须继续走 `StopTracker`
（risk/stops.py，回测/实盘共用），不许另写一份止损逻辑。
"""
from __future__ import annotations

import time
from typing import Any

from .. import state as appstate
from ..brokers.base import Broker
from ..risk.guardrails import RiskLimits
from ..risk.stops import StopTracker


class _LiveRiskMixin:
    """风控热加载 + 止损检查 + 交易所侧保护性委托。"""

    def _live_limits(self) -> tuple[RiskLimits, bool]:
        """每 tick 重读风控配置。

        EngineTask 构造时拷贝的 limits 是快照，若一直沿用，运行中启用熔断
        或收紧限额将完全无效——这会让「熔断」在引擎运行期间形同虚设。
        """
        try:
            row = appstate.get_risk_row()
            limits = RiskLimits.from_config(row)
            # 止损配置同步热加载：原地改字段，已存在的 StopTracker 持有同一对象引用
            self.stop_cfg.stop_type = getattr(row, "stop_type", self.stop_cfg.stop_type) or "none"
            self.stop_cfg.stop_value = float(getattr(row, "stop_value", self.stop_cfg.stop_value) or self.stop_cfg.stop_value)
            self.stop_cfg.take_profit_r = float(getattr(row, "take_profit_r", self.stop_cfg.take_profit_r) or 0.0)
            self.stop_cfg.time_stop_bars = int(getattr(row, "time_stop_bars", self.stop_cfg.time_stop_bars) or 0)
            self.limits = limits
            # 仓位算法参数同样热加载，否则「改了风控但引擎还在按旧上限下单」
            self.sizing_method = getattr(row, "sizing_method", self.sizing_method) or "weight"
            self.risk_per_trade_pct = float(getattr(row, "risk_per_trade_pct", self.risk_per_trade_pct) or 1.0)
            self.max_position_pct = limits.max_position_pct
            self.gross_pct = limits.max_gross_exposure_pct
            return limits, bool(row.kill_switch)
        except Exception:  # noqa: BLE001
            return self.limits, bool(getattr(self.limits, "kill_switch", False))

    def _check_stops(self, broker: Broker, equity: float) -> list[dict[str, Any]]:
        """对已有持仓执行止损检查（用券商或免费源的实时行情）。"""
        actions: list[dict[str, Any]] = []
        plist = broker.positions()
        if not plist:
            return actions
        qmap = self._quotes([p.symbol for p in plist])

        for p in plist:
            sym = p.symbol
            if abs(p.quantity) < 1e-9:
                continue
            # P1-7：止损离场冷却 —— 刚提交过止损市价单的标的，在券商回填新持仓前
            # 不再重复触发（exec_interval_sec 可低至 0.05s，旧实现会隔 tick 重复平仓）。
            if time.time() - self._stop_exit_at.get(sym, 0.0) < 30.0:
                continue
            q = qmap.get(sym.upper())
            if not q:
                continue
            px = float(q.get("price") or 0)
            if px <= 0:
                continue
            high = float(q.get("day_high") or px)
            low = float(q.get("day_low") or px)

            tr = self.trackers.get(sym)
            needs_takeover = tr is None or not tr.s.active
            if needs_takeover:
                # 接管引擎外已存在的持仓：用成本价建仓 + 真实 ATR 定初始止损。
                # 旧实现这里直接 continue 且从不 open()，导致 s.active 永远为 False，
                # 下一 tick 又新建一个 tracker —— 止损对这类持仓永不生效。
                if tr is None:
                    tr = StopTracker(self.stop_cfg, sym)
                    self.trackers[sym] = tr
                entry = float(p.avg_cost or px)
                # P1-1：传策略 bar 序号（_bar_seq），不是执行 tick 数
                tr.open(1 if p.quantity > 0 else -1, entry, self._bar_seq, self._atr_for(sym) or None)
                actions.append({
                    "type": "STOP_TAKEOVER", "symbol": sym, "side": "BUY" if p.quantity > 0 else "SELL",
                    "quantity": abs(p.quantity), "entry": round(entry, 4),
                    "stop_price": round(tr.current_stop(), 4), "ok": True,
                    "reason": f"接管持仓并建立止损跟踪（{self.stop_cfg.stop_type}）",
                })
                # 接管当 tick 不判定：避免用接管前的日内极值立刻误触
                continue

            cfg = self.stop_cfg
            atr_val = self._atr_for(sym) or None if cfg.stop_type in (
                "atr_fixed", "atr_trailing", "chandelier", "volatility"
            ) else None

            hit, reason, stop_px = tr.update(high, low, px, atr_val, self._bar_seq)
            if not hit:
                continue

            # 先撤掉保护性挂单，避免重复平仓
            self._cancel_protective(broker, sym)

            side = "SELL" if p.quantity > 0 else "BUY"
            self._stop_exit_at[sym] = time.time()   # P1-7：无论成败都进入冷却，防重复市价单
            res = broker.place_order(sym, side, abs(p.quantity), "MKT")
            actions.append({
                "type": "STOP_EXIT", "symbol": sym, "side": side,
                "quantity": abs(p.quantity), "reason": reason,
                "stop_price": round(stop_px, 4),
                "ok": res.ok, "message": res.message,
            })
            appstate.log(
                "stop_exit", "WARN" if res.ok else "CRITICAL",
                f"{sym} 止损离场 {side} {abs(p.quantity):.4f} @ 触发价 {stop_px:.4f}（{reason}）",
                detail=res.message,
            )
            if res.ok:
                self._persist_order(
                    sym, side, abs(p.quantity), res, stop_px,
                    order_type="MKT", reason=f"止损离场 · {reason}", broker=broker,
                )
                tr.s.reset()
        return actions

    # ------------------------------------------------------------------
    # 保护性挂单（实盘专用）：把止损/止盈挂到交易所侧，
    # 这样即使引擎进程掉线，持仓依然有保护。
    # ------------------------------------------------------------------
    def _place_protective(self, broker: Broker, sym: str, qty: float, side: str, ref_px: float) -> None:
        if not (self.place_protective and self.mode == "live"):
            return
        if sym in self.protective_orders and self.protective_orders[sym]:
            return
        tr = self.trackers.get(sym)
        stop_px = tr.current_stop() if tr and tr.s.active else 0.0
        cfg = self.stop_cfg
        opp = "SELL" if side.upper() == "BUY" else "BUY"
        placed: dict[str, str] = {}

        if cfg.stop_type != "none" and stop_px > 0:
            res = broker.place_order(sym, opp, qty, "STP", stop_price=round(stop_px, 2), tif="GTC")
            if res.ok:
                placed["stop"] = res.order_id

        if cfg.take_profit_r > 0 and tr and tr.s.active and tr.s.r_distance > 0:
            # P2-10：止盈必须锚定**实际建仓价**。旧实现用 ref_px（调用方传的是
            # res.avg_price or px），而 IBKR 异步下单时 avg_price 常为 0 →
            # 退化成用「当前价」锚定 R 距离，交易所侧止盈价随之偏移。
            # StopTracker 里的 entry_price 才是真实建仓价。
            anchor = tr.s.entry_price if tr.s.entry_price > 0 else ref_px
            tp = anchor + (1 if side.upper() == "BUY" else -1) * tr.s.r_distance * cfg.take_profit_r
            res = broker.place_order(sym, opp, qty, "LMT", limit_price=round(tp, 2), tif="GTC")
            if res.ok:
                placed["target"] = res.order_id

        if placed:
            self.protective_orders[sym] = placed
            appstate.log("protective_orders", "INFO",
                         f"已为 {sym} 挂保护性委托：{placed}（止损价 {stop_px:.2f}）")

    def _cancel_protective(self, broker: Broker, sym: str) -> None:
        ids = self.protective_orders.pop(sym, None)
        if not ids:
            return
        for kind, oid in ids.items():
            try:
                res = broker.cancel_order(oid)
                if res.ok:
                    appstate.log("protective_cancel", "INFO", f"已撤销 {sym} 的保护性委托（{kind} {oid}）")
            except Exception:  # noqa: BLE001
                continue

    def _cancel_all_protective(self, broker: Broker | None = None) -> int:
        """撤销本引擎挂出的**全部**保护性委托（P1-4）。

        引擎停止 / 进程掉线前必须清场。旧实现的 `_loop` finally 与 `stop()` 都不撤销，
        残留的 GTC STP/LMT 单在持仓已被平掉后触发会**反向开仓**
        （无持仓时 STP 成交即成裸空/裸多）—— 与「保护性委托」的设计意图相反。

        返回尝试撤销的标的数。券商不可用时**显式告警**而不是静默丢弃。
        """
        syms = list(self.protective_orders.keys())
        if not syms:
            return 0
        if broker is None:
            try:
                broker = self._broker()
            except Exception:  # noqa: BLE001
                broker = None
        if broker is None:
            appstate.log(
                "protective_cancel_failed", "CRITICAL",
                f"引擎停止时无法连接券商，{len(syms)} 个标的的保护性委托未撤销："
                f"{', '.join(syms)}（请在券商端手工撤单）",
            )
            self.protective_orders.clear()
            return 0
        for sym in syms:
            try:
                self._cancel_protective(broker, sym)
            except Exception:  # noqa: BLE001 —— 单个标的失败不影响其余
                continue
        return len(syms)
