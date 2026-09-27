"""市场元数据层 —— 全系统「什么是某个市场」的唯一真源。

在此之前，交易所、币种、时区、交易时段、TIF 规则全部硬编码散落在
`brokers/ibkr.py` / `risk/guardrails.py` / `data_provider.py` 里，
且一律假设美股。要支持港股，第一件事就是把这些常量收拢到一层。

设计原则
--------
1. **只读元数据**：本模块不做任何 IO、不依赖数据库、不依赖券商连接。
   交易日历（有节假日表）在 `calendar.py`，费用在 `fees.py`，手数在 `lots.py`，
   符号解析在 `symbols.py` —— 它们都从本模块取市场定义。
2. **不为不存在的市场编造规则**：拿不准的字段宁可标 `None` 并加注释，
   也不要把美股规则套到港股上（这正是重构前的问题）。
3. **时段用本地时间表达**：`Session` 里的 time 一律是该市场**本地时间**，
   调用方负责先用市场时区把 datetime 本地化。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# ======================================================================
# 时段
# ======================================================================
@dataclass(frozen=True)
class Session:
    """一个连续交易时段（该市场本地时间）。"""

    start: dt.time
    end: dt.time
    label: str

    def contains(self, t: dt.time) -> bool:
        return self.start <= t < self.end

    def __str__(self) -> str:  # pragma: no cover - 仅用于展示
        return f"{self.label} {self.start:%H:%M}-{self.end:%H:%M}"


# ======================================================================
# 市场定义
# ======================================================================
@dataclass(frozen=True)
class Market:
    code: str                      # "US" | "HK"
    name: str                      # 中文名
    timezone: str                  # IANA 时区
    currency: str                  # 结算币种
    currency_symbol: str           # 展示用符号
    ib_exchange: str               # IB 合约的 exchange
    ib_primary: str | None         # IB 合约的 primaryExchange（用来消歧义）
    regular: tuple[Session, ...]   # 常规连续交易时段（可多段，如港股上午/下午）
    extended: tuple[Session, ...]  # 常规时段之外可交易的时段（美股盘前盘后）
    auction: tuple[Session, ...]   # 集合竞价时段
    allowed_tif: frozenset[str]    # 该市场合法的 Time In Force
    allowed_order_types: frozenset[str]
    native_market_order: bool      # 交易所是否原生支持市价单
    lot_rule: str                  # "integer"（1 股）| "board_lot"（每手股数）
    default_lot: int               # lot_rule=board_lot 时的兜底每手股数
    tick_size: float               # 最小价格变动
    fee_model: str                 # fees.py 中的模型键
    settlement_days: int           # T+N
    half_day_close: dt.time | None  # 半日市提前收盘时间
    notes: tuple[str, ...] = field(default_factory=tuple)

    # ---------- 便捷判定 ----------
    def localize(self, when: dt.datetime | None = None) -> dt.datetime:
        """把任意 aware/naive datetime 转成本市场本地 aware datetime。"""
        tz = _tz(self.timezone)
        if when is None:
            return dt.datetime.now(tz)
        if when.tzinfo is None:
            return when.replace(tzinfo=tz)
        return when.astimezone(tz)

    def session_of(self, when: dt.datetime | None = None) -> str:
        """返回 'regular' | 'extended' | 'auction' | 'closed'（**不看日历**）。

        要看节假日请用 `markets.calendar.market_status()`。
        """
        t = self.localize(when).time()
        for s in self.regular:
            if s.contains(t):
                return "regular"
        for s in self.auction:
            if s.contains(t):
                return "auction"
        for s in self.extended:
            if s.contains(t):
                return "extended"
        return "closed"

    def is_regular_open(self, when: dt.datetime | None = None) -> bool:
        return self.session_of(when) == "regular"

    def label_of_session(self, kind: str) -> str:
        return {
            "regular": "常规交易时段",
            "extended": "盘前/盘后",
            "auction": "集合竞价",
            "closed": "休市",
        }.get(kind, kind)

    def describe_sessions(self) -> str:
        return "、".join(str(s) for s in self.regular)


# ----------------------------------------------------------------------
# 美股
# ----------------------------------------------------------------------
US = Market(
    code="US",
    name="美股",
    timezone="America/New_York",
    currency="USD",
    currency_symbol="US$",
    ib_exchange="SMART",
    ib_primary=None,          # 由 symbols.py 按标的补（AAPL→NASDAQ, SPY→ARCA）
    regular=(Session(dt.time(9, 30), dt.time(16, 0), "常规盘"),),
    extended=(
        Session(dt.time(4, 0), dt.time(9, 30), "盘前"),
        Session(dt.time(16, 0), dt.time(20, 0), "盘后"),
    ),
    auction=(Session(dt.time(9, 28), dt.time(9, 30), "开盘竞价"),),
    allowed_tif=frozenset({"DAY", "GTC", "GTD", "IOC", "FOK", "OPG", "DAY+"}),
    allowed_order_types=frozenset({"MKT", "LMT", "STP", "STP_LMT", "TRAIL", "MOC", "LOC"}),
    native_market_order=True,
    lot_rule="integer",
    default_lot=1,
    tick_size=0.01,
    fee_model="us",
    settlement_days=1,        # 2024-05-28 起美股改为 T+1
    half_day_close=dt.time(13, 0),
    notes=(
        "美股已于 2024-05-28 由 T+2 改为 T+1 结算。",
        "盘前 04:00-09:30、盘后 16:00-20:00 需券商支持且流动性显著低于常规盘。",
        "做空受 Regulation SHO 约束，标的处于 SSR 时卖出价需高于当日最高买价。",
    ),
)


# ----------------------------------------------------------------------
# 港股
# ----------------------------------------------------------------------
HK = Market(
    code="HK",
    name="港股",
    timezone="Asia/Hong_Kong",
    currency="HKD",
    currency_symbol="HK$",
    ib_exchange="SEHK",
    ib_primary="SEHK",
    regular=(
        Session(dt.time(9, 30), dt.time(12, 0), "早盘"),
        Session(dt.time(13, 0), dt.time(16, 0), "午盘"),
    ),
    extended=(),              # 港股没有盘前盘后连续交易
    auction=(
        Session(dt.time(9, 0), dt.time(9, 30), "开市前竞价"),
        Session(dt.time(16, 0), dt.time(16, 10), "收市竞价"),
    ),
    # 港交所现货市场没有 IOC / FOK；GTC 需券商侧中转，IBKR 可支持
    allowed_tif=frozenset({"DAY", "GTC"}),
    allowed_order_types=frozenset({"LMT", "MKT", "STP", "STP_LMT"}),
    native_market_order=False,   # HKEX 无真正市价单，IBKR 以进取限价模拟
    lot_rule="board_lot",
    default_lot=100,
    tick_size=0.001,             # 实际按价格档位分档，见 lots.py
    fee_model="hk",
    settlement_days=2,           # T+2
    half_day_close=dt.time(12, 0),
    notes=(
        "港股必须按「每手股数」整手交易，碎股只能通过碎股市场卖出，不能买入。",
        "交易时段分为早盘 09:30-12:00 与午盘 13:00-16:00，中间 12:00-13:00 休市。",
        "12:00-13:00 之间的订单不会被拒绝但不会立即成交，需注意下单时点。",
        "每手股数因标的而异（腾讯 100 股、汇丰 400 股），下单数量必须为每手整数倍。",
        "仅有港交所指定的「可进行卖空的指定证券名单」可以做空，且需要借券。",
        "HKEX 不提供原生市价单，IBKR 会以进取限价单模拟，极端行情下可能不成交。",
        "交易成本显著高于美股：双边印花税 0.1% 是最大单项。",
    ),
)


MARKETS: dict[str, Market] = {US.code: US, HK.code: HK}

# 币种 → 市场（用于从账户/持仓反查市场）
_CURRENCY_TO_MARKET: dict[str, str] = {m.currency: m.code for m in MARKETS.values()}


class UnknownMarket(KeyError):
    """请求了未注册的市场。"""


def get_market(code: str) -> Market:
    key = str(code or "").strip().upper()
    if key in MARKETS:
        return MARKETS[key]
    raise UnknownMarket(f"未注册的市场：{code!r}（可用：{', '.join(MARKETS)}）")


def market_of_currency(currency: str | None) -> Market | None:
    return MARKETS.get(_CURRENCY_TO_MARKET.get(str(currency or "").upper(), ""))


def all_markets() -> list[Market]:
    return list(MARKETS.values())


def _tz(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # pragma: no cover - 无 tzdata 的极端环境
        return dt.timezone.utc


def market_summary() -> list[dict]:
    """给 API/前端用的市场元数据快照。"""
    out = []
    for m in MARKETS.values():
        out.append({
            "code": m.code,
            "name": m.name,
            "timezone": m.timezone,
            "currency": m.currency,
            "currency_symbol": m.currency_symbol,
            "ib_exchange": m.ib_exchange,
            "ib_primary": m.ib_primary,
            "sessions": [
                {"start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"), "label": s.label}
                for s in m.regular
            ],
            "extended": [
                {"start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"), "label": s.label}
                for s in m.extended
            ],
            "auction": [
                {"start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"), "label": s.label}
                for s in m.auction
            ],
            "allowed_tif": sorted(m.allowed_tif),
            "allowed_order_types": sorted(m.allowed_order_types),
            "native_market_order": m.native_market_order,
            "lot_rule": m.lot_rule,
            "default_lot": m.default_lot,
            "settlement_days": m.settlement_days,
            "half_day_close": m.half_day_close.strftime("%H:%M") if m.half_day_close else None,
            "describe_sessions": m.describe_sessions(),
            "notes": list(m.notes),
        })
    return out


__all__ = [
    "Session", "Market", "MARKETS", "US", "HK",
    "get_market", "market_of_currency", "all_markets", "market_summary",
    "UnknownMarket",
]
