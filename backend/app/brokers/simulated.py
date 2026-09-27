"""
模拟券商
=========
不接触任何真实资金，用一个持久化的虚拟账户按「实时/最新行情 + 滑点」立即撮合。
用于：新策略上线前的全链路演练（含护栏、止损、审计），以及无 TWS 环境下的演示。

账户状态持久化在 app_settings 表（key = sim_account_state），重启不丢失。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ..data_provider import get_quote
from .base import AccountSnapshot, Broker, OrderResult, PositionItem


class SimulatedBroker(Broker):
    name = "simulated"
    supports_live = False

    STATE_KEY = "sim_account_state"
    INITIAL_CASH = 100_000.0
    SLIPPAGE_BPS = 2.0
    COMMISSION_PER_SHARE = 0.0035
    COMMISSION_MIN = 0.35

    def __init__(self, mode: str = "paper") -> None:
        super().__init__(mode="paper")   # 模拟盘恒为 paper
        self._connected = False

    # ---------------- 状态持久化 ----------------
    def _load(self) -> dict:
        from ..database import session_scope
        from ..models import AppSetting

        with session_scope() as s:
            row = s.get(AppSetting, self.STATE_KEY)
            if row and row.value:
                try:
                    state = json.loads(row.value)
                    state.setdefault("positions", {})
                    return state
                except json.JSONDecodeError:
                    pass
            state = {
                "cash": self.INITIAL_CASH,
                "initial_cash": self.INITIAL_CASH,
                "realized_pnl": 0.0,
                "positions": {},
                "day_start_equity": self.INITIAL_CASH,
                "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "history": [],
            }
            s.add(AppSetting(key=self.STATE_KEY, value=json.dumps(state)))
            return state

    def _save(self, state: dict) -> None:
        from ..database import session_scope
        from ..models import AppSetting

        with session_scope() as s:
            row = s.get(AppSetting, self.STATE_KEY)
            payload = json.dumps(state)
            if row:
                row.value = payload
            else:
                s.add(AppSetting(key=self.STATE_KEY, value=payload))

    def reset(self, cash: float | None = None) -> dict:
        state = {
            "cash": float(cash or self.INITIAL_CASH),
            "initial_cash": float(cash or self.INITIAL_CASH),
            "realized_pnl": 0.0,
            "positions": {},
            "day_start_equity": float(cash or self.INITIAL_CASH),
            "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "history": [],
        }
        self._save(state)
        return state

    # ---------------- 连接 ----------------
    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> tuple[bool, str]:
        self._connected = True
        return True, "模拟券商已就绪（不涉及真实资金）"

    def disconnect(self) -> None:
        self._connected = False

    # ---------------- 账户 ----------------
    def _price(self, symbol: str) -> float:
        try:
            q = get_quote(symbol)
            return float(q.get("price") or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def account(self) -> AccountSnapshot:
        state = self._load()
        positions = state.get("positions", {})
        mv = 0.0
        unreal = 0.0
        for sym, p in positions.items():
            px = self._price(sym)
            mv += p["qty"] * px
            unreal += (px - p["avg_cost"]) * p["qty"]
        equity = state["cash"] + mv

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if state.get("day") != today:
            state["day"] = today
            state["day_start_equity"] = equity
            self._save(state)

        day_start = float(state.get("day_start_equity") or state.get("initial_cash") or self.INITIAL_CASH)
        day_pnl = equity - day_start
        return AccountSnapshot(
            broker=self.name,
            mode="paper",
            connected=self._connected,
            account_id="SIMULATED",
            currency="USD",
            equity=round(equity, 2),
            cash=round(state["cash"], 2),
            buying_power=round(max(state["cash"], 0.0) * 2, 2),
            gross_position_value=round(mv, 2),
            unrealized_pnl=round(unreal, 2),
            realized_pnl=round(float(state.get("realized_pnl", 0.0)), 2),
            day_pnl=round(day_pnl, 2),
            day_pnl_pct=round(day_pnl / day_start * 100, 3) if day_start else 0.0,
            margin_used=round(max(mv - state["cash"], 0.0), 2),
            message="模拟盘：成交按最新价 + 滑点即时撮合",
        )

    def positions(self) -> list[PositionItem]:
        state = self._load()
        acc = self.account()
        out: list[PositionItem] = []
        for sym, p in state.get("positions", {}).items():
            px = self._price(sym)
            qty = float(p["qty"])
            if abs(qty) < 1e-9:
                continue
            mv = qty * px
            upl = (px - p["avg_cost"]) * qty
            out.append(PositionItem(
                symbol=sym, quantity=round(qty, 4), avg_cost=round(p["avg_cost"], 4),
                last_price=round(px, 4), market_value=round(mv, 2),
                unrealized_pnl=round(upl, 2),
                unrealized_pct=round((px / p["avg_cost"] - 1) * 100, 3) if p["avg_cost"] else 0.0,
                weight=round(abs(mv) / acc.equity * 100, 2) if acc.equity else 0.0,
                strategy_id=p.get("strategy_id"),
                stop_price=p.get("stop_price"),
            ))
        out.sort(key=lambda x: -abs(x.market_value))
        return out

    # ---------------- 下单 ----------------
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
    ) -> OrderResult:
        symbol = symbol.strip().upper()
        side = side.upper()
        qty = float(quantity)
        if qty <= 0:
            return OrderResult(False, message="数量必须大于 0")
        market = self._price(symbol)
        if market <= 0:
            return OrderResult(False, message=f"无法获取 {symbol} 的行情价格")
        if order_type == "LMT" and not limit_price:
            return OrderResult(False, message="限价单必须提供价格")

        base_px = float(limit_price) if (order_type == "LMT" and limit_price) else market
        slip = base_px * self.SLIPPAGE_BPS / 10_000.0
        fill_px = base_px + slip if side == "BUY" else base_px - slip
        signed = qty if side == "BUY" else -qty

        state = self._load()
        positions = state.get("positions", {})
        p = positions.get(symbol, {"qty": 0.0, "avg_cost": 0.0})
        old_qty = float(p["qty"])

        notional = abs(signed * fill_px)
        commission = max(notional * 0.00005, self.COMMISSION_PER_SHARE * qty, self.COMMISSION_MIN)
        cash_delta = -signed * fill_px - commission

        # 实现盈亏（FIFO 简化：按均价法）
        realized = 0.0
        new_qty = old_qty + signed
        # 名义金额小于 1 美元视为已清仓，避免四舍五入留下微量残仓
        if abs(new_qty) * max(fill_px, 1.0) < 1.0:
            new_qty = 0.0
        if old_qty != 0 and (signed * old_qty < 0):
            closed = min(abs(signed), abs(old_qty))
            realized = (fill_px - p["avg_cost"]) * closed * (1 if old_qty > 0 else -1)
            state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + realized

        if abs(new_qty) < 1e-9:
            positions.pop(symbol, None)
        else:
            if old_qty == 0 or signed * old_qty > 0:
                total = abs(old_qty) + abs(signed)
                avg = (p["avg_cost"] * abs(old_qty) + fill_px * abs(signed)) / max(total, 1e-9)
            else:
                avg = p["avg_cost"] if new_qty * old_qty > 0 else fill_px
            positions[symbol] = {
                "qty": new_qty,
                "avg_cost": round(float(avg), 6),
                "stop_price": stop_loss_price if stop_loss_price else (p.get("stop_price") if new_qty != 0 else None),
                "strategy_id": p.get("strategy_id"),
            }
        state["positions"] = positions
        state["cash"] = float(state["cash"]) + cash_delta
        hist = state.get("history", [])
        hist.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol, "side": side, "qty": qty, "price": round(fill_px, 4),
            "commission": round(commission, 4), "realized": round(realized, 2),
        })
        state["history"] = hist[-500:]
        self._save(state)

        return OrderResult(
            True, order_id=f"SIM-{uuid.uuid4().hex[:12].upper()}", status="FILLED",
            message=f"模拟成交 {qty:g} 股 @ ${fill_px:,.2f}（含滑点 {self.SLIPPAGE_BPS}bp）",
            filled_qty=qty, avg_price=round(fill_px, 4), commission=round(commission, 4),
            raw={"notional": round(notional, 2), "realized": round(realized, 2),
                 "cash_after": round(state["cash"], 2)},
        )

    def cancel_order(self, order_id: str) -> OrderResult:
        return OrderResult(True, order_id=order_id, status="CANCELLED",
                           message="模拟券商订单为即时成交，无需撤单")

    def quote(self, symbol: str) -> dict:
        return get_quote(symbol)
