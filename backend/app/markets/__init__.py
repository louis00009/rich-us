"""市场层 —— 美股 / 港股的元数据、日历、符号、手数、费用、汇率、做空规则。

**这一层是全系统关于「市场」的唯一真源。**
不要在 `brokers/` / `risk/` / `engine/` / `data_provider.py` 里再硬编码
交易所名、币种、时段或费率 —— 一律从这里取。

| 模块 | 职责 |
|---|---|
| `registry`   | 市场定义：时区、币种、时段、TIF、订单类型 |
| `holidays`   | 节假日数据（**每年需维护**） |
| `calendar`   | 交易日判定、当前时段、下次开盘 |
| `symbols`    | 任意写法 → 明确的合约描述 |
| `lots`       | 每手股数、最小价格变动 |
| `fees`       | 分项费用（美股 SEC/TAF/FINRA；港股印花税等） |
| `fx`         | 多币种汇率换算 |
| `shortlist`  | 做空可行性 |
"""
from . import calendar, fees, fx, holidays, lots, registry, shortlist, symbols  # noqa: F401
from .calendar import MarketStatus, is_market_open, is_trading_day, market_status  # noqa: F401
from .fees import FeeBreakdown, estimate as estimate_fees, total_fee  # noqa: F401
from .fx import convert as convert_currency, get_rate, to_base  # noqa: F401
from .lots import lot_of, round_price, round_qty, tick_size  # noqa: F401
from .registry import HK, MARKETS, US, Market, all_markets, get_market, market_summary  # noqa: F401
from .shortlist import is_shortable  # noqa: F401
from .symbols import SymbolError, SymbolRef, market_of, normalize, parse  # noqa: F401

__all__ = [
    # 子模块
    "registry", "holidays", "calendar", "symbols", "lots", "fees", "fx", "shortlist",
    # 市场
    "Market", "MARKETS", "US", "HK", "get_market", "all_markets", "market_summary",
    # 日历
    "MarketStatus", "market_status", "is_trading_day", "is_market_open",
    # 符号
    "SymbolRef", "SymbolError", "parse", "normalize", "market_of",
    # 手数
    "lot_of", "round_qty", "tick_size", "round_price",
    # 费用
    "FeeBreakdown", "estimate_fees", "total_fee",
    # 汇率
    "get_rate", "convert_currency", "to_base",
    # 做空
    "is_shortable",
]
