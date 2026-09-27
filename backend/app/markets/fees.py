"""分项费用模型（美股 / 港股）。

为什么必须分项
--------------
重构前全系统只有 `commission_bps = 1.0` 一个参数。这在港股上是**严重低估**：

    港股买入 100 股腾讯 @ 300 HKD（成交额 30,000 HKD）
      佣金       0.015%          ≈ 4.50
      印花税     0.1%（向上取整到元）  = 30.00   ← 最大单项
      交易费     0.00565%        ≈ 1.70
      交易征费   0.0027%         ≈ 0.81
      FRC 征费   0.00015%        ≈ 0.05
      CCASS      0.002%（min 2）  ≈ 0.60
      ─────────────────────────────────────
      合计 ≈ 37.66 HKD ≈ 12.6 bps（单边）

而模型里写的是 1.0 bps。**低估 12 倍**，会让任何高频/短线港股策略的回测
看起来极其漂亮、实盘一跑就亏。所以这里必须做真分项。

数据来源与时点
--------------
各费率是**公开发布的监管费率**，会调整。`RATES_AS_OF` 记录本表核对时点；
券商自有佣金（IBKR tiered/fixed）因套餐而异，做成可配置项，默认值仅作参考。
**上线实盘前请到券商与交易所官网核对本文件。**
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .registry import get_market
from .symbols import SymbolRef, parse

# 本表核对时点
RATES_AS_OF = "2026-09"

# ======================================================================
# 美股
# ======================================================================
# IBKR Tiered 美股：每股 $0.0035，最低 $0.35，最高为成交额的 1%
US_COMMISSION_PER_SHARE = 0.0035
US_COMMISSION_MIN = 0.35
US_COMMISSION_MAX_PCT = 0.01

# SEC Section 31 Fee：仅卖出收取，按成交额计。FY2024-2026 为 $27.80 / 百万美元
SEC_SECTION_31_RATE = 27.80 / 1_000_000
# FINRA Trading Activity Fee：仅卖出，按股计，有上限
FINRA_TAF_PER_SHARE = 0.000166
FINRA_TAF_MAX = 8.30
# CAT（Consolidated Audit Trail）费：按股计，极低
CAT_PER_SHARE = 0.0000035

# ======================================================================
# 港股（监管费率为官方公布值）
# ======================================================================
HK_STAMP_DUTY_RATE = 0.001        # 印花税 0.1%，买卖双边，向上取整到 1 元
HK_TRADING_FEE_RATE = 0.0000565   # 港交所交易费 0.00565%
HK_SFC_LEVY_RATE = 0.000027       # 证监会交易征费 0.0027%
HK_FRC_LEVY_RATE = 0.0000015      # 会计及财务汇报局交易征费 0.00015%
HK_CCASS_RATE = 0.00002           # HKSCC 结算费 0.002%
HK_CCASS_MIN = 2.0
HK_CCASS_MAX = 100.0

# 券商佣金（可配置）。IBKR 港股 tiered 约 0.015%–0.03%，最低 HKD 3
HK_COMMISSION_RATE = 0.00015
HK_COMMISSION_MIN = 3.0
HK_COMMISSION_MAX_PCT = 0.01


# ======================================================================
@dataclass
class FeeItem:
    name: str
    amount: float
    note: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "amount": round(self.amount, 4), "note": self.note}


@dataclass
class FeeBreakdown:
    symbol: str
    market: str
    currency: str
    side: str
    qty: float
    price: float
    notional: float
    items: list[FeeItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rates_as_of: str = RATES_AS_OF

    @property
    def total(self) -> float:
        return sum(i.amount for i in self.items)

    @property
    def bps(self) -> float:
        return (self.total / self.notional * 10_000.0) if self.notional > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "market": self.market, "currency": self.currency,
            "side": self.side, "qty": self.qty, "price": self.price,
            "notional": round(self.notional, 4),
            "items": [i.as_dict() for i in self.items],
            "total": round(self.total, 4),
            "bps": round(self.bps, 3),
            "warnings": list(self.warnings),
            "rates_as_of": self.rates_as_of,
        }


# ======================================================================
def _us_fees(ref: SymbolRef, side: str, qty: float, price: float) -> FeeBreakdown:
    notional = abs(qty * price)
    b = FeeBreakdown(ref.symbol, "US", ref.currency, side, qty, price, notional)

    comm = min(max(qty * US_COMMISSION_PER_SHARE, US_COMMISSION_MIN), notional * US_COMMISSION_MAX_PCT)
    b.items.append(FeeItem("券商佣金", comm, f"${US_COMMISSION_PER_SHARE}/股，最低 ${US_COMMISSION_MIN}"))

    if side.upper() == "SELL":
        sec = notional * SEC_SECTION_31_RATE
        b.items.append(FeeItem("SEC 交易费", sec, "仅卖出，成交额 × 万分之 0.278"))
        taf = min(qty * FINRA_TAF_PER_SHARE, FINRA_TAF_MAX)
        b.items.append(FeeItem("FINRA TAF", taf, f"仅卖出，${FINRA_TAF_PER_SHARE}/股，上限 ${FINRA_TAF_MAX}"))
    else:
        b.items.append(FeeItem("SEC 交易费", 0.0, "仅卖出收取"))
        b.items.append(FeeItem("FINRA TAF", 0.0, "仅卖出收取"))

    b.items.append(FeeItem("CAT 监管费", qty * CAT_PER_SHARE, "全美审计追踪系统费用"))
    b.warnings.append("美股交易所路由费（NASDAQ/NYSE 取消费）因路由而异，未计入；实际以成交回报为准")
    return b


def _hk_fees(ref: SymbolRef, side: str, qty: float, price: float) -> FeeBreakdown:
    notional = abs(qty * price)
    b = FeeBreakdown(ref.symbol, "HK", ref.currency, side, qty, price, notional)

    comm = min(max(notional * HK_COMMISSION_RATE, HK_COMMISSION_MIN), notional * HK_COMMISSION_MAX_PCT)
    b.items.append(FeeItem("券商佣金", comm, f"{HK_COMMISSION_RATE:.4%}，最低 HK${HK_COMMISSION_MIN:.0f}（可配置）"))

    duty = math.ceil(notional * HK_STAMP_DUTY_RATE)
    b.items.append(FeeItem("印花税", duty, "0.1% 买卖双边，向上取整至 HK$1（最大单项）"))

    b.items.append(FeeItem("交易费", notional * HK_TRADING_FEE_RATE, "港交所 0.00565%"))
    b.items.append(FeeItem("交易征费", notional * HK_SFC_LEVY_RATE, "证监会 0.0027%"))
    b.items.append(FeeItem("FRC 征费", notional * HK_FRC_LEVY_RATE, "会计及财务汇报局 0.00015%"))

    ccass = min(max(notional * HK_CCASS_RATE, HK_CCASS_MIN), HK_CCASS_MAX)
    b.items.append(FeeItem("CCASS 结算费", ccass, f"0.002%，HK${HK_CCASS_MIN:.0f}~HK${HK_CCASS_MAX:.0f}"))

    if ref.currency != "HKD":
        b.warnings.append("港股标的币种非 HKD，请确认合约解析是否正确")
    return b


def estimate(
    symbol: str | SymbolRef,
    side: str,
    qty: float,
    price: float,
) -> FeeBreakdown:
    """估算单笔订单的全部分项费用。"""
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    if qty <= 0 or price <= 0:
        return FeeBreakdown(ref.symbol, ref.market, ref.currency, side, qty, price, 0.0,
                            warnings=["数量或价格非正，费用按 0 计"])
    return _us_fees(ref, side, qty, price) if ref.market == "US" else _hk_fees(ref, side, qty, price)


def total_fee(symbol: str | SymbolRef, side: str, qty: float, price: float) -> float:
    """只要合计金额（回测热路径用，避免构造完整明细的开销）。"""
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    if qty <= 0 or price <= 0:
        return 0.0
    notional = abs(qty * price)
    if ref.market == "US":
        fee = min(max(qty * US_COMMISSION_PER_SHARE, US_COMMISSION_MIN), notional * US_COMMISSION_MAX_PCT)
        fee += qty * CAT_PER_SHARE
        if side.upper() == "SELL":
            fee += notional * SEC_SECTION_31_RATE
            fee += min(qty * FINRA_TAF_PER_SHARE, FINRA_TAF_MAX)
        return fee
    fee = min(max(notional * HK_COMMISSION_RATE, HK_COMMISSION_MIN), notional * HK_COMMISSION_MAX_PCT)
    fee += math.ceil(notional * HK_STAMP_DUTY_RATE)
    fee += notional * (HK_TRADING_FEE_RATE + HK_SFC_LEVY_RATE + HK_FRC_LEVY_RATE)
    fee += min(max(notional * HK_CCASS_RATE, HK_CCASS_MIN), HK_CCASS_MAX)
    return fee


def round_trip_bps(symbol: str | SymbolRef, price: float = 100.0) -> float:
    """往返交易成本（bps）。港股 ≈ 25 bps，美股 ≈ 3 bps —— 数量级差距。

    用于快速判断「这个市场的策略需要多高的毛收益才能覆盖成本」。
    """
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    qty = max(1.0, 10_000.0 / max(price, 0.01))
    buy = total_fee(ref, "BUY", qty, price)
    sell = total_fee(ref, "SELL", qty, price)
    notional = qty * price
    return (buy + sell) / notional * 10_000.0 if notional else 0.0


def schedule_summary() -> list[dict]:
    """给前端/文档展示的费率表。"""
    return [
        {
            "market": "US", "market_name": "美股", "currency": "USD",
            "items": [
                {"name": "券商佣金", "value": f"${US_COMMISSION_PER_SHARE}/股（min ${US_COMMISSION_MIN}）"},
                {"name": "SEC 交易费", "value": f"卖出 成交额 × {SEC_SECTION_31_RATE*1e6:.2f}/百万"},
                {"name": "FINRA TAF", "value": f"卖出 ${FINRA_TAF_PER_SHARE}/股（上限 ${FINRA_TAF_MAX}）"},
                {"name": "CAT 费", "value": f"${CAT_PER_SHARE}/股"},
            ],
            "round_trip_bps": round(round_trip_bps("SPY", 500.0), 2),
        },
        {
            "market": "HK", "market_name": "港股", "currency": "HKD",
            "items": [
                {"name": "券商佣金", "value": f"{HK_COMMISSION_RATE:.4%}（min HK${HK_COMMISSION_MIN:.0f}，可配置）"},
                {"name": "印花税", "value": f"{HK_STAMP_DUTY_RATE:.1%} 双边，进位至 HK$1"},
                {"name": "交易费", "value": f"{HK_TRADING_FEE_RATE:.5%}"},
                {"name": "交易征费", "value": f"{HK_SFC_LEVY_RATE:.4%}"},
                {"name": "FRC 征费", "value": f"{HK_FRC_LEVY_RATE:.5%}"},
                {"name": "CCASS 结算费", "value": f"{HK_CCASS_RATE:.3%}（HK${HK_CCASS_MIN:.0f}~{HK_CCASS_MAX:.0f}）"},
            ],
            "round_trip_bps": round(round_trip_bps("0700.HK", 300.0), 2),
        },
    ]


__all__ = [
    "FeeItem", "FeeBreakdown", "estimate", "total_fee", "round_trip_bps",
    "schedule_summary", "RATES_AS_OF",
    "US_COMMISSION_PER_SHARE", "US_COMMISSION_MIN",
    "SEC_SECTION_31_RATE", "FINRA_TAF_PER_SHARE", "FINRA_TAF_MAX",
    "HK_STAMP_DUTY_RATE", "HK_TRADING_FEE_RATE", "HK_SFC_LEVY_RATE",
    "HK_FRC_LEVY_RATE", "HK_CCASS_RATE", "HK_COMMISSION_RATE",
]
