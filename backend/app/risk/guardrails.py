"""
交易护栏（Guardrails）
========================
每一笔订单在下发前必须通过全部检查。任何一条不通过 → 拒绝 + 审计。
这是资金安全最关键的一层：策略可以出错，护栏不能。

市场感知
--------
本模块不再硬编码"美股 09:30-16:00"。开市判定委托给 `markets.calendar`，
按**标的自带的所属市场**判断（0700.HK 走港股日历，AAPL 走美股日历），
同时支持盘前盘后（`allow_extended_hours`）。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from ..markets import calendar as mkcal
from ..markets.registry import get_market
from ..markets.symbols import SymbolError, market_of


@dataclass
class RiskLimits:
    max_position_pct: float = 20.0
    max_gross_exposure_pct: float = 100.0
    max_open_positions: int = 10
    min_order_notional: float = 200.0
    max_order_notional: float = 50_000.0
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 15.0
    trading_hours_only: bool = True
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)
    kill_switch: bool = False
    # --- 市场感知（C1）---
    allow_extended_hours: bool = False       # 是否允许盘前/盘后下单
    hk_max_gross_exposure_pct: float = 100.0  # 港股单独的总敞口上限
    max_daily_orders: int = 0                 # 0 = 不限制；防 IBKR pacing 违规
    max_orders_per_minute: int = 0            # 0 = 不限制；IBKR 硬限 50 msg/s
    allow_short: bool = False                 # T-113：是否允许做空（裸卖/卖超持仓）

    @classmethod
    def from_config(cls, cfg: Any) -> "RiskLimits":
        return cls(
            max_position_pct=float(getattr(cfg, "max_position_pct", 20.0)),
            max_gross_exposure_pct=float(getattr(cfg, "max_gross_exposure_pct", 100.0)),
            max_open_positions=int(getattr(cfg, "max_open_positions", 10)),
            min_order_notional=float(getattr(cfg, "min_order_notional", 200.0)),
            max_order_notional=float(getattr(cfg, "max_order_notional", 50_000.0)),
            max_daily_loss_pct=float(getattr(cfg, "max_daily_loss_pct", 3.0)),
            max_drawdown_pct=float(getattr(cfg, "max_drawdown_pct", 15.0)),
            trading_hours_only=bool(getattr(cfg, "trading_hours_only", True)),
            whitelist=[s.strip().upper() for s in str(getattr(cfg, "whitelist", "") or "").split(",") if s.strip()],
            blacklist=[s.strip().upper() for s in str(getattr(cfg, "blacklist", "") or "").split(",") if s.strip()],
            kill_switch=bool(getattr(cfg, "kill_switch", False)),
            allow_extended_hours=bool(getattr(cfg, "allow_extended_hours", False)),
            hk_max_gross_exposure_pct=float(getattr(cfg, "hk_max_gross_exposure_pct", 100.0)),
            allow_short=bool(getattr(cfg, "allow_short", False)),
            max_daily_orders=int(getattr(cfg, "max_daily_orders", 0) or 0),
            max_orders_per_minute=int(getattr(cfg, "max_orders_per_minute", 0) or 0),
        )


@dataclass
class GuardContext:
    equity: float
    day_start_equity: float
    peak_equity: float
    open_positions: dict[str, float]      # symbol -> 当前持仓市值（含方向，base currency）
    gross_exposure: float = 0.0
    now: dt.datetime | None = None
    is_live: bool = False
    market_exposure: dict[str, float] = field(default_factory=dict)  # market -> 敞口
    orders_today: int = 0
    orders_last_minute: int = 0


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    code: str = ""
    adjusted_qty: float | None = None
    warnings: list[str] = field(default_factory=list)


# -------- 兼容旧常量（仅展示用，判定一律走 markets.calendar）--------
US_MARKET_OPEN = dt.time(9, 30)
US_MARKET_CLOSE = dt.time(16, 0)


def is_market_open(now: dt.datetime | None = None, market: str = "US") -> bool:
    """是否处于常规交易时段（含节假日判断）。"""
    return mkcal.market_status(market, now).session == "regular"


def market_state(symbol: str, now: dt.datetime | None = None) -> tuple[str, str]:
    """返回 (市场代码, 时段)。标的无法解析时按美股处理。"""
    mk = market_of(symbol) or "US"
    return mk, mkcal.market_status(mk, now).session


def check_order(
    *,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    limits: RiskLimits,
    ctx: GuardContext,
) -> GuardResult:
    """
    单笔订单护栏检查。
    side: BUY / SELL；quantity: 股数（正数）；price: 参考价格（**该标的的计价币种**）。
    返回 ok=False 时直接拒绝；若可自动缩减则给 adjusted_qty。
    """
    symbol = symbol.strip().upper()
    warnings: list[str] = []

    if limits.kill_switch:
        return GuardResult(False, "熔断开关已启用，禁止任何下单", "KILL_SWITCH")

    if not symbol or quantity <= 0 or price <= 0:
        return GuardResult(False, "非法订单参数（标的/数量/价格）", "BAD_PARAMS")

    # ---------------- 市场识别 ----------------
    try:
        mk = market_of(symbol) or "US"
    except SymbolError:
        mk = "US"
    mkt = get_market(mk)
    csym = mkt.currency_symbol
    st = mkcal.market_status(mk, ctx.now)

    if limits.blacklist and symbol in limits.blacklist:
        return GuardResult(False, f"{symbol} 在黑名单中", "BLACKLIST")
    if limits.whitelist and symbol not in limits.whitelist:
        return GuardResult(False, f"{symbol} 不在白名单中", "NOT_WHITELISTED")

    # ---------------- 交易时段 ----------------
    if limits.trading_hours_only:
        allowed_sessions = {"regular", "extended"} if limits.allow_extended_hours else {"regular"}
        if st.session not in allowed_sessions:
            if limits.allow_extended_hours:
                return GuardResult(False, f"{st.reason}，当前不允许下单", "CLOSED_MARKET")
            return GuardResult(
                False,
                f"{st.reason}（可开启「允许盘前盘后」以延长可交易时段）",
                "CLOSED_MARKET",
            )
        if st.session == "extended":
            warnings.append(f"{mkt.name}盘前/盘后时段，流动性低、价差宽，建议使用限价单")
        if st.is_half_day:
            warnings.append(f"今日为半日市（{st.early_close}），提前至 {mkt.half_day_close:%H:%M} 收盘")

    # ---------------- 下单频率（防 IBKR pacing 违规）----------------
    if limits.max_daily_orders and ctx.orders_today >= limits.max_daily_orders:
        return GuardResult(
            False,
            f"今日下单笔数已达上限 {limits.max_daily_orders}（防止触发券商限流导致账户被限制）",
            "DAILY_ORDER_LIMIT",
        )
    if limits.max_orders_per_minute and ctx.orders_last_minute >= limits.max_orders_per_minute:
        return GuardResult(
            False,
            f"最近一分钟下单 {ctx.orders_last_minute} 笔，已达上限 {limits.max_orders_per_minute}",
            "ORDER_RATE_LIMIT",
        )

    # ---------------- 金额 ----------------
    notional = abs(quantity * price)
    if notional < limits.min_order_notional:
        return GuardResult(
            False,
            f"订单金额 {csym}{notional:,.0f} 低于最小下单额 {csym}{limits.min_order_notional:,.0f}",
            "TOO_SMALL",
        )

    adjusted: float | None = None
    if notional > limits.max_order_notional:
        adjusted = limits.max_order_notional / price
        warnings.append(
            f"订单金额 {csym}{notional:,.0f} 超过单笔上限，已自动缩减至 {csym}{limits.max_order_notional:,.0f}"
        )
        notional = limits.max_order_notional

    # ---------------- 减仓判定（提前计算：熔断必须放行减仓单）----------------
    held_qty = float(ctx.open_positions.get(symbol, 0.0))   # market_value 带符号（base currency）
    is_reducing = (side == "SELL" and held_qty > 0) or (side == "BUY" and held_qty < 0)

    # ---------------- 做空校验（T-113）----------------
    # 默认 allow_short=False：无持仓不可卖出；卖超持仓缩减为平仓；回补超空头同样缩减。
    if side == "SELL" and held_qty <= 0 and not limits.allow_short:
        return GuardResult(
            False,
            f"当前禁止做空（风控 allow_short=false），{symbol} 无多头持仓不可卖出",
            "SHORT_FORBIDDEN",
        )
    if side == "SELL" and held_qty > 0 and quantity > held_qty / max(price, 1e-9) and not limits.allow_short:
        adjusted = held_qty / price
        warnings.append(
            f"{symbol} 仅允许减仓：卖出 {quantity:g} 超过持仓市值 {csym}{held_qty:,.0f}，已缩减为全部平仓"
        )
    if side == "BUY" and held_qty < 0 and not limits.allow_short:
        cover_qty = abs(held_qty) / price
        if quantity > cover_qty:
            adjusted = cover_qty
            warnings.append(f"{symbol} 仅允许回补空头：买入 {quantity:g} 超过空头 {cover_qty:g}，已缩减为全部回补")

    # ---------------- 港股每手股数对齐（T-114）----------------
    if mk == "HK" and not is_reducing:
        try:
            from ..markets.lots import round_qty

            base_qty = adjusted if adjusted is not None else quantity
            aligned, lot, note = round_qty(symbol, base_qty, side=side)
            if aligned != base_qty:
                adjusted = aligned
                warnings.append(f"港股每手 {lot} 股：数量已对齐为 {aligned:g}（{note or '手数规则'}）")
        except Exception:  # noqa: BLE001 —— 手数表缺失时不阻塞下单
            pass

    # ---------------- 日亏损保护（P0-6：减仓单放行）----------------
    # 熔断的目的是停止风险扩张，而不是把持仓锁死在亏损里 —— 减仓/止损单必须放行，
    # 否则触发熔断后既不能止损也不能按信号离场，与保护资金的设计意图相反。
    if not is_reducing and ctx.day_start_equity > 0:
        day_pnl_pct = (ctx.equity - ctx.day_start_equity) / ctx.day_start_equity * 100.0
        if day_pnl_pct <= -limits.max_daily_loss_pct:
            return GuardResult(
                False,
                f"当日亏损 {day_pnl_pct:.2f}% 已达上限 {limits.max_daily_loss_pct:.2f}%，当日禁止继续开仓",
                "DAILY_LOSS_LIMIT",
            )
        if day_pnl_pct <= -limits.max_daily_loss_pct * 0.7:
            warnings.append(f"当日已亏损 {day_pnl_pct:.2f}%，接近日内上限，建议降低仓位")

    # ---------------- 回撤熔断（P0-6：减仓单放行）----------------
    if not is_reducing and ctx.peak_equity > 0:
        dd_pct = (ctx.equity - ctx.peak_equity) / ctx.peak_equity * 100.0
        if dd_pct <= -limits.max_drawdown_pct:
            return GuardResult(
                False,
                f"账户回撤 {dd_pct:.2f}% 已触及熔断线 {limits.max_drawdown_pct:.2f}%，全部禁止开仓",
                "MAX_DRAWDOWN",
            )
        if dd_pct <= -limits.max_drawdown_pct * 0.75:
            warnings.append(f"回撤已达 {dd_pct:.2f}%，距熔断线不足 25%")

    # ---------------- 单标的集中度 ----------------
    current = abs(ctx.open_positions.get(symbol, 0.0))
    if not is_reducing and ctx.equity > 0:
        cap = ctx.equity * limits.max_position_pct / 100.0
        if current + notional > cap:
            allowed = max(cap - current, 0.0)
            if allowed <= 0:
                return GuardResult(
                    False,
                    f"{symbol} 持仓 {csym}{current:,.0f} 已达单标的上限 {limits.max_position_pct:.1f}%",
                    "POSITION_CAP",
                )
            adjusted = min(adjusted, allowed / price) if adjusted else allowed / price
            warnings.append(f"{symbol} 触及单标的上限，订单缩减至 {csym}{allowed:,.0f}")

    # ---------------- 总敞口（全局 + 分市场）----------------
    if ctx.equity > 0 and not is_reducing:
        gross_cap = ctx.equity * limits.max_gross_exposure_pct / 100.0
        projected = ctx.gross_exposure + notional
        if projected > gross_cap:
            return GuardResult(
                False,
                f"新增后总敞口 {csym}{projected:,.0f} 超过上限 {csym}{gross_cap:,.0f}（{limits.max_gross_exposure_pct:.0f}%）",
                "GROSS_EXPOSURE",
            )
        if mk == "HK":
            hk_cap = ctx.equity * limits.hk_max_gross_exposure_pct / 100.0
            hk_now = ctx.market_exposure.get("HK", 0.0)
            if hk_now + notional > hk_cap:
                return GuardResult(
                    False,
                    f"港股新增后敞口 {csym}{hk_now + notional:,.0f} 超过港股上限 {csym}{hk_cap:,.0f}"
                    f"（{limits.hk_max_gross_exposure_pct:.0f}%）",
                    "MARKET_EXPOSURE",
                )

    # ---------------- 持仓数量 ----------------
    if not is_reducing and symbol not in ctx.open_positions:
        if len(ctx.open_positions) >= limits.max_open_positions:
            return GuardResult(
                False,
                f"持仓数量已达上限 {limits.max_open_positions} 个",
                "MAX_POSITIONS",
            )

    if adjusted is not None and adjusted <= 0:
        return GuardResult(False, "按风控上限缩减后订单数量为 0", "ADJUSTED_TO_ZERO")

    if adjusted is not None and adjusted * price < limits.min_order_notional:
        return GuardResult(False, "缩减后低于最小下单额", "TOO_SMALL_AFTER_ADJUST")

    return GuardResult(True, "通过", "OK", adjusted_qty=adjusted, warnings=warnings)


def summarize_limits(limits: RiskLimits) -> list[dict[str, Any]]:
    return [
        {"key": "单标的持仓上限", "value": f"{limits.max_position_pct:.1f}% 权益"},
        {"key": "总敞口上限", "value": f"{limits.max_gross_exposure_pct:.0f}% 权益"},
        {"key": "港股敞口上限", "value": f"{limits.hk_max_gross_exposure_pct:.0f}% 权益"},
        {"key": "最大持仓数量", "value": f"{limits.max_open_positions} 个"},
        {"key": "单笔下单金额", "value": f"{limits.min_order_notional:,.0f} ~ {limits.max_order_notional:,.0f}"},
        {"key": "单日最大亏损", "value": f"{limits.max_daily_loss_pct:.2f}%"},
        {"key": "最大回撤熔断", "value": f"{limits.max_drawdown_pct:.2f}%"},
        {"key": "仅交易时段下单", "value": "是" if limits.trading_hours_only else "否"},
        {"key": "允许盘前盘后", "value": "是" if limits.allow_extended_hours else "否"},
        {"key": "日内下单笔数上限", "value": str(limits.max_daily_orders) if limits.max_daily_orders else "不限制"},
        {"key": "每分钟下单上限", "value": str(limits.max_orders_per_minute) if limits.max_orders_per_minute else "不限制"},
        {"key": "白名单", "value": ", ".join(limits.whitelist) or "未设置"},
        {"key": "黑名单", "value": ", ".join(limits.blacklist) or "未设置"},
        {"key": "熔断开关", "value": "已启用 🔴" if limits.kill_switch else "正常 🟢"},
    ]
