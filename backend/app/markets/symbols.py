"""跨市场符号解析 —— 把用户/策略给出的任意写法规范成一个明确的合约描述。

重构前的行为（`brokers/ibkr.py::_spec`）是：
    "0700.HK" → "0700 HK" → Stock("0700 HK", "SMART", "USD")
交易所 SMART、币种 USD —— 既不是港交所，也不是港币，注定解析不到合约。

本模块输出的 `SymbolRef` 是**唯一**的合约描述来源，IBKR 适配层、数据源、
手数规则、费用模型全部从这里取值，不再各自硬编码。

支持写法
--------
| 输入            | 市场 | IB symbol | 说明                          |
|-----------------|------|-----------|-------------------------------|
| AAPL            | US   | AAPL      | 普通美股                      |
| BRK-B / BRK.B   | US   | BRK B     | IB 用空格代替连字符/点        |
| ^GSPC / ^SPX    | US   | SPX       | 美股指数（CBOE）              |
| 0700.HK         | HK   | 700       | 港股，带后缀                  |
| 00700.HK        | HK   | 700       | 港股，5 位写法                |
| 0700 / 700      | HK   | 700       | 纯数字 → 默认港股             |
| 09988           | HK   | 9988      | 阿里港股                      |
| ^HSI / ^HSCEI   | HK   | HSI       | 港股指数（HKFE）              |
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .registry import HK, US, get_market

# ======================================================================
# 指数映射：(市场, 交易所, IB symbol, 展示名)
# ======================================================================
US_INDEX: dict[str, tuple[str, str]] = {
    "^GSPC": ("SPX", "CBOE"),
    "^SPX": ("SPX", "CBOE"),
    "^NDX": ("NDX", "NASDAQ"),
    "^IXIC": ("COMP", "NASDAQ"),
    "^DJI": ("INDU", "CBOE"),
    "^RUT": ("RUT", "CBOE"),
    "^VIX": ("VIX", "CBOE"),
    "^TNX": ("TNX", "CBOE"),
    "^TYX": ("TYX", "CBOE"),
    "^SOX": ("SOX", "CBOE"),
    "^XAU": ("XAUUSD", "SMART"),
}

HK_INDEX: dict[str, tuple[str, str]] = {
    "^HSI": ("HSI", "HKFE"),
    "^HSCE": ("HSCEI", "HKFE"),
    "^HSCEI": ("HSCEI", "HKFE"),
    "^HSTECH": ("HSTECH", "HKFE"),
    "^HSCCI": ("HSCCI", "HKFE"),
}

# 美股常见标的的 primaryExchange —— 仅收录确有歧义或需要明确的，
# 其余交给 IB 的 SMART 路由自行解析（多写反而容易写错）。
US_PRIMARY: dict[str, str] = {
    "SPY": "ARCA", "QQQ": "NASDAQ", "IWM": "ARCA", "DIA": "ARCA",
    "GLD": "ARCA", "SLV": "ARCA", "TLT": "NASDAQ", "IEF": "NASDAQ",
    "AGG": "ARCA", "EEM": "ARCA", "EFA": "ARCA", "VTI": "ARCA",
    "VNQ": "ARCA", "DBC": "ARCA", "UUP": "ARCA", "XLF": "ARCA",
    "XLK": "ARCA", "XLE": "ARCA", "XLV": "ARCA", "XLI": "ARCA",
    "AAPL": "NASDAQ", "MSFT": "NASDAQ", "NVDA": "NASDAQ", "GOOGL": "NASDAQ",
    "GOOG": "NASDAQ", "AMZN": "NASDAQ", "META": "NASDAQ", "TSLA": "NASDAQ",
    "AVGO": "NASDAQ", "NFLX": "NASDAQ", "AMD": "NASDAQ", "INTC": "NASDAQ",
    "BABA": "NYSE", "PDD": "NASDAQ", "JD": "NASDAQ", "NIO": "NYSE",
    "TSM": "NYSE", "V": "NYSE", "MA": "NYSE", "JPM": "NYSE",
    "BRK B": "NYSE", "UNH": "NYSE", "XOM": "NYSE", "JNJ": "NYSE",
}

_NUMERIC = re.compile(r"^\d{1,5}$")
_TICKER = re.compile(r"^[\^A-Z][A-Z0-9.\-]{0,14}$")


class SymbolError(ValueError):
    """符号无法解析。"""


@dataclass(frozen=True)
class SymbolRef:
    raw: str              # 用户原始输入
    symbol: str           # 规范化展示代码（AAPL / 0700.HK / ^HSI）
    market: str           # US | HK
    ib_symbol: str        # 传给 ib_async 的 symbol
    sec_type: str         # STK | IND
    exchange: str         # SMART | CBOE | SEHK | HKFE
    primary_exchange: str | None
    currency: str
    is_index: bool

    @property
    def is_hk(self) -> bool:
        return self.market == "HK"

    @property
    def market_obj(self):
        return get_market(self.market)

    def as_dict(self) -> dict:
        return {
            "raw": self.raw, "symbol": self.symbol, "market": self.market,
            "ib_symbol": self.ib_symbol, "sec_type": self.sec_type,
            "exchange": self.exchange, "primary_exchange": self.primary_exchange,
            "currency": self.currency, "is_index": self.is_index,
        }


def _hk_ib_symbol(digits: str) -> str:
    """港股 IB symbol 去掉前导零：0700→700，09988→9988，0005→5。"""
    stripped = digits.lstrip("0")
    return stripped or "0"


def canonical_hk(digits: str) -> str:
    """港股规范展示代码：补齐到 4 位 + .HK（0005.HK / 0700.HK / 9988.HK）。"""
    s = digits.lstrip("0") or "0"
    if len(s) <= 4:
        s = s.zfill(4)
    return f"{s}.HK"


def parse(symbol: str) -> SymbolRef:
    """解析任意写法 → SymbolRef。无法解析时抛 SymbolError。"""
    raw = str(symbol or "").strip()
    if not raw:
        raise SymbolError("符号为空")

    s = raw.upper().replace(" ", "")

    # ---------- 指数 ----------
    if s.startswith("^"):
        if s in HK_INDEX:
            ib, exch = HK_INDEX[s]
            return SymbolRef(raw, s, "HK", ib, "IND", exch, "HKFE", HK.currency, True)
        if s in US_INDEX:
            ib, exch = US_INDEX[s]
            return SymbolRef(raw, s, "US", ib, "IND", exch, exch, US.currency, True)
        # 未知 ^XXX：按美股指数走 CBOE，交给 IB 判定
        return SymbolRef(raw, s, "US", s[1:], "IND", "CBOE", "CBOE", US.currency, True)

    # ---------- 带后缀 ----------
    if "." in s:
        head, _, tail = s.rpartition(".")
        if tail in ("HK", "HKG"):
            if not _NUMERIC.match(head):
                raise SymbolError(f"港股代码应为数字：{raw!r}")
            ib = _hk_ib_symbol(head)
            return SymbolRef(raw, canonical_hk(head), "HK", ib, "STK", "SEHK", "SEHK", HK.currency, False)
        if tail in ("US", "O", "N", "A", "P"):
            # .O/.N 等交易所后缀统一归美股
            pass
        else:
            # 未被识别的后缀（如 BRK.B）→ 当作美股内部点号处理
            pass
        # 美股：点号换空格（BRK.B → BRK B）
        ib = head.replace(".", " ") if tail in ("US", "O", "N", "A", "P") else s.replace(".", " ")
        ib = ib.replace("-", " ")
        return SymbolRef(raw, ib, "US", ib, "STK", "SMART", US_PRIMARY.get(ib), US.currency, False)

    # ---------- 连字符（美股优先，BRK-B）----------
    if "-" in s and not _NUMERIC.match(s):
        ib = s.replace("-", " ")
        return SymbolRef(raw, ib, "US", ib, "STK", "SMART", US_PRIMARY.get(ib), US.currency, False)

    # ---------- 纯数字 → 港股 ----------
    if _NUMERIC.match(s):
        ib = _hk_ib_symbol(s)
        return SymbolRef(raw, canonical_hk(s), "HK", ib, "STK", "SEHK", "SEHK", HK.currency, False)

    # ---------- 普通美股 ----------
    if not _TICKER.match(s):
        raise SymbolError(f"无法识别的符号：{raw!r}")
    return SymbolRef(raw, s, "US", s, "STK", "SMART", US_PRIMARY.get(s), US.currency, False)


def parse_many(symbols) -> list[SymbolRef]:
    out: list[SymbolRef] = []
    seen: set[str] = set()
    for x in symbols or []:
        try:
            ref = parse(x)
        except SymbolError:
            continue
        if ref.symbol not in seen:
            seen.add(ref.symbol)
            out.append(ref)
    return out


def normalize(symbol: str) -> str:
    """规范化展示代码；无法解析时原样返回（不抛异常，便于展示层容错）。"""
    try:
        return parse(symbol).symbol
    except SymbolError:
        return str(symbol or "").strip().upper()


def market_of(symbol: str) -> str | None:
    try:
        return parse(symbol).market
    except SymbolError:
        return None


def group_by_market(symbols) -> dict[str, list[SymbolRef]]:
    """按市场分组 —— 下单/行情按市场批处理时需要。"""
    out: dict[str, list[SymbolRef]] = {}
    for ref in parse_many(symbols):
        out.setdefault(ref.market, []).append(ref)
    return out


__all__ = [
    "SymbolRef", "SymbolError", "parse", "parse_many", "normalize",
    "market_of", "group_by_market", "canonical_hk",
    "US_INDEX", "HK_INDEX", "US_PRIMARY",
]
