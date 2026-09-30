"""IBKR 账户/持仓域 mixin（FILE_SIZE_DEBT Batch F-2 从 ibkr.py 拆出）。

ib.portfolio() 取真实市价/浮盈/已实现盈亏（多币种折算）。
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


class IbkrAccountMixin:
    def _summary(self) -> dict[str, float]:
        self._require()
        try:
            rows = self._await(
                self._ib.accountSummaryAsync(self.account_id or ""),
                timeout=max(self.call_timeout, 6.0),
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"账户摘要获取失败：{type(exc).__name__}: {exc}"
            return {}
        out: dict[str, float] = {}
        for r in rows:
            try:
                out[str(r.tag)] = float(r.value)
            except (TypeError, ValueError):
                continue

        # 账户基准币种：从本地缓存读 BaseCurrency（accountValues 是纯缓存读取，
        # 不发消息，因此不会占用 pacing 配额）。
        try:
            for v in self._call(self._ib.accountValues, timeout=2.0):
                if str(getattr(v, "tag", "")) == "BaseCurrency":
                    cur = str(getattr(v, "value", "") or "")
                    if cur:
                        self._base_currency = cur
                    break
        except Exception:  # noqa: BLE001
            pass
        return out

    def account(self) -> AccountSnapshot:
        try:
            self._require()
        except BrokerError as exc:
            return AccountSnapshot(
                broker=self.name, mode=self.mode, connected=False,
                account_id=self.account_id, message=str(exc),
            )
        s = self._summary()
        self._summary_cache = s

        equity = s.get("NetLiquidation", 0.0)
        cash = s.get("TotalCashValue", 0.0)
        unreal = s.get("UnrealizedPnL", 0.0)
        realized = s.get("RealizedPnL", 0.0)
        fx_est = bool(getattr(self, "_positions_fx_estimated", False))
        return AccountSnapshot(
            broker=self.name,
            mode=self.mode,
            connected=True,
            account_id=self.account_id or "IBKR",
            currency=self._base_currency,
            equity=round(equity, 2),
            cash=round(cash, 2),
            buying_power=round(s.get("BuyingPower", 0.0), 2),
            gross_position_value=round(s.get("GrossPositionValue", 0.0), 2),
            unrealized_pnl=round(unreal, 2),
            realized_pnl=round(realized, 2),
            day_pnl=round(unreal, 2),
            day_pnl_pct=round(unreal / equity * 100, 3) if equity else 0.0,
            margin_used=round(s.get("MaintMarginReq", 0.0), 2),
            fx_estimated=fx_est,
            message=(
                f"{'实盘' if self.mode == 'live' else '纸面'}账户 · {self.host}:{self.port}"
                f" · 行情类型 {self._md_type_verified or self.market_data_type}"
                + ("　· 含估算汇率" if fx_est else "")
            ),
        )

    def positions(self) -> list[PositionItem]:
        """使用 portfolio() 取真实市价与浮盈（而不是把成本当现价）。

        多市场处理：IB 返回的港股 symbol 是 "700"、币种 HKD，市场价值是**港币**。
        旧实现直接把港币市值当美元计入权重，港股仓位权重会被放大 7.8 倍。
        这里统一用 `display_symbol()` 还原代码，并折算到账户基准币种。
        """
        try:
            self._require()
        except BrokerError:
            return []
        try:
            rows = (
                self._call(self._ib.portfolio, self.account_id)
                if self.account_id
                else self._call(self._ib.portfolio)
            )
        except Exception:  # noqa: BLE001
            return []

        from ..markets.fx import convert
        from ..markets.lots import lot_of

        equity = self._summary_cache.get("NetLiquidation") or 0.0
        out: list[PositionItem] = []
        fx_estimated_any = False
        for p in rows:
            try:
                qty = float(p.position)
                if abs(qty) < 1e-9:
                    continue
                contract = p.contract
                symbol, market, currency = self.display_symbol(contract)
                avg = float(getattr(p, "averageCost", 0.0) or 0.0)
                px = float(getattr(p, "marketPrice", 0.0) or 0.0)
                if px <= 0:
                    px = avg
                mv = float(getattr(p, "marketValue", 0.0) or 0.0) or qty * px
                upl = float(getattr(p, "unrealizedPNL", 0.0) or 0.0)
                cost_basis = abs(avg * qty)
                mv_base, estimated = convert(mv, currency, "USD")
                fx_estimated_any = fx_estimated_any or estimated
                try:
                    lot = lot_of(symbol).lot
                except Exception:  # noqa: BLE001
                    lot = 1
                out.append(PositionItem(
                    symbol=symbol,
                    quantity=qty,
                    avg_cost=round(avg, 4),
                    last_price=round(px, 4),
                    market_value=round(mv, 2),
                    unrealized_pnl=round(upl, 2),
                    unrealized_pct=round(upl / cost_basis * 100, 3) if cost_basis else 0.0,
                    weight=round(abs(mv_base) / equity * 100, 2) if equity else 0.0,
                    sec_type=str(getattr(contract, "secType", "STK")),
                    currency=currency,
                    market=market,
                    market_value_base=round(mv_base, 2),
                    lot=lot,
                ))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda x: -abs(x.market_value_base or x.market_value))
        self._positions_fx_estimated = fx_estimated_any
        return out

    # ================================================================
    # 下单（支持 OCO 止盈止损）
    # ================================================================

    def open_orders(self) -> list[dict[str, Any]]:
        try:
            self._require()
            out: list[dict[str, Any]] = []
            for t in self._call(self._ib.openTrades):
                st = t.orderStatus
                symbol, market, currency = self.display_symbol(t.contract)
                out.append({
                    "order_id": str(t.order.orderId),
                    "perm_id": str(getattr(t.order, "permId", "")),
                    "symbol": symbol,
                    "market": market,
                    "currency": currency,
                    "action": str(t.order.action),
                    "quantity": float(t.order.totalQuantity),
                    "type": str(t.order.orderType),
                    "lmt_price": float(getattr(t.order, "lmtPrice", 0.0) or 0.0),
                    "aux_price": float(getattr(t.order, "auxPrice", 0.0) or 0.0),
                    "status": str(st.status),
                    "filled": float(st.filled or 0.0),
                    "remaining": float(st.remaining or 0.0),
                    "oca_group": str(getattr(t.order, "ocaGroup", "") or ""),
                })
            return out
        except Exception:  # noqa: BLE001
            return []

    def today_fills(self) -> list[dict[str, Any]]:
        """今日成交回报（用于与本地订单表对账）。"""
        try:
            self._require()
            out = []
            for f in self._call(self._ib.fills):
                ex = f.execution
                symbol, market, currency = self.display_symbol(f.contract)
                out.append({
                    "exec_id": str(ex.execId),
                    "order_id": str(ex.orderId),
                    "perm_id": str(getattr(ex, "permId", "")),
                    "symbol": symbol,
                    "market": market,
                    "currency": currency,
                    "side": str(ex.side),
                    "shares": float(ex.shares),
                    "price": float(ex.price),
                    "time": str(getattr(ex, "time", "")),
                    "commission": float(getattr(f.commissionReport, "commission", 0.0) or 0.0)
                    if getattr(f, "commissionReport", None) else 0.0,
                })
            return out
        except Exception:  # noqa: BLE001
            return []

    # ================================================================

    def status(self) -> dict[str, Any]:
        md_labels = {1: "实时", 2: "冻结", 3: "延迟", 4: "延迟冻结"}
        md = self._md_type_verified or self.market_data_type
        stream = self.stream_status()
        return {
            "broker": self.name,
            "mode": self.mode,
            "connected": self.connected,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "account": self.account_id,
            "base_currency": self._base_currency,
            "readonly": self.readonly,
            "market_data_type": md,
            "market_data_label": md_labels.get(md, "未知"),
            "use_rth": self.use_rth,
            "contracts_cached": len(self._contracts),
            "historical_requests": self._hist_calls,
            # ---- 流式行情 ----
            "supports_streaming": self.supports_streaming,
            "stream_method": "reqMktData",
            "streamed_symbols": stream["stream_count"],
            "tick_cache": stream["tick_cache"],
            "stream_sample": stream["streaming"][:12],
            # ---- 延迟 / 限流 / 熔断 ----
            "call_timeout_sec": self.call_timeout,
            "fill_timeout_sec": self.fill_timeout,
            "pacing": self._pacer.snapshot(),
            "breaker": self._breaker.snapshot(),
            "event_handlers": list(self._registered),
            "last_order_latency_ms": dict(self._last_order_latency_ms),
            "stats": dict(self.stats),
            "last_error": self._last_error,
            "last_error_code": self._last_error_code,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
