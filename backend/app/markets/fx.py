"""汇率换算 —— 多币种账户的基础。

持仓里有 HKD 资产、账户权益按 USD 计，如果直接相加就是**错的**：
系统会以为 100 万港币的持仓值 100 万美元，虚增 7.8 倍敞口。

降级链（与行情同构）
--------------------
1. 券商实时汇率（IBKR `reqTickers("HKD.USD")` 或 accountSummary 的 ExchangeRate）
2. 免费数据源（yfinance `HKDUSD=X`）
3. **兜底常量**（联系汇率 7.75~7.85 区间内取值）—— 结果会带 `estimated=True`，
   上层**必须**把这一标记透出给用户，不能让估算汇率被当成真实汇率使用。

缓存：默认 10 分钟 TTL。联系汇率波动极小，不需要更高频率。
"""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass
from typing import Callable

from .registry import get_market

# 兜底汇率（仅用于拿不到真实汇率时，且必须带 estimated 标记）
FALLBACK_RATES: dict[tuple[str, str], float] = {
    ("USD", "HKD"): 7.80,
    ("HKD", "USD"): 1.0 / 7.80,
    ("USD", "USD"): 1.0,
    ("HKD", "HKD"): 1.0,
}

DEFAULT_BASE = "USD"
_TTL_SEC = 600

_lock = threading.RLock()
_cache: dict[tuple[str, str], tuple[float, dt.datetime, str]] = {}

# 外部汇率提供者：register_fx_provider(fn)，fn(from_ccy, to_ccy) -> float | None
_providers: list[Callable[[str, str], float | None]] = []


@dataclass(frozen=True)
class FXRate:
    base: str
    quote: str
    rate: float
    source: str          # ibkr | yfinance | fallback | identity
    ts: dt.datetime
    estimated: bool = False

    def as_dict(self) -> dict:
        return {
            "base": self.base, "quote": self.quote, "rate": self.rate,
            "source": self.source, "ts": self.ts.isoformat(), "estimated": self.estimated,
        }


def register_fx_provider(fn: Callable[[str, str], float | None]) -> None:
    with _lock:
        if fn not in _providers:
            _providers.append(fn)


def _normalize(ccy: str) -> str:
    return str(ccy or "").strip().upper()


def get_rate(base: str, quote: str, *, force: bool = False) -> FXRate:
    """取 1 单位 base 折合多少 quote。"""
    b, q = _normalize(base), _normalize(quote)
    now = dt.datetime.now(dt.timezone.utc)
    if b == q:
        return FXRate(b, q, 1.0, "identity", now, estimated=False)

    key = (b, q)
    with _lock:
        hit = _cache.get(key)
        if hit and not force:
            rate, ts, src = hit
            if (now - ts).total_seconds() < _TTL_SEC:
                return FXRate(b, q, rate, src, ts, estimated=(src == "fallback"))

    # 1) 外部提供者（券商优先）
    for fn in list(_providers):
        try:
            v = fn(b, q)
        except Exception:  # noqa: BLE001
            continue
        if v and float(v) > 0:
            with _lock:
                _cache[key] = (float(v), now, "ibkr")
            return FXRate(b, q, float(v), "ibkr", now, estimated=False)

    # 2) 免费源
    try:
        v = _from_yfinance(b, q)
        if v and v > 0:
            with _lock:
                _cache[key] = (v, now, "yfinance")
            return FXRate(b, q, v, "yfinance", now, estimated=False)
    except Exception:  # noqa: BLE001
        pass

    # 3) 兜底（并尝试反推）
    direct = FALLBACK_RATES.get((b, q))
    if direct:
        with _lock:
            _cache[key] = (direct, now, "fallback")
        return FXRate(b, q, direct, "fallback", now, estimated=True)
    inv = FALLBACK_RATES.get((q, b))
    if inv:
        v = 1.0 / inv
        with _lock:
            _cache[key] = (v, now, "fallback")
        return FXRate(b, q, v, "fallback", now, estimated=True)

    # 完全不认识的币种对：返回 0 让上层显式失败，而不是猜一个数
    return FXRate(b, q, 0.0, "unknown", now, estimated=True)


def _from_yfinance(base: str, quote: str) -> float | None:
    try:
        import yfinance as yf
    except Exception:  # noqa: BLE001
        return None
    try:
        t = yf.Ticker(f"{base}{quote}=X")
        hist = t.history(period="5d", interval="1d")
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:  # noqa: BLE001
        return None


def convert(amount: float, frm: str, to: str) -> tuple[float, bool]:
    """换算金额。返回 (结果, 是否使用了估算汇率)。"""
    r = get_rate(frm, to)
    if r.rate <= 0:
        raise ValueError(f"无法取得 {frm}→{to} 汇率")
    return float(amount) * r.rate, r.estimated


def to_base(amount: float, currency: str, base: str = DEFAULT_BASE) -> float:
    return convert(amount, currency, base)[0]


def currency_of_market(market: str) -> str:
    return get_market(market).currency


def symbol_currency(symbol: str) -> str:
    from .symbols import market_of

    mk = market_of(symbol)
    return currency_of_market(mk) if mk else DEFAULT_BASE


def rates_snapshot(currencies: list[str] | None = None, base: str = DEFAULT_BASE) -> dict:
    """给前端展示的汇率快照。"""
    ccys = currencies or ["USD", "HKD"]
    out = []
    for c in ccys:
        c = _normalize(c)
        if c == base:
            continue
        out.append(get_rate(base, c).as_dict())
    return {"base": base, "rates": out, "fallback_table": {
        f"{b}/{q}": v for (b, q), v in FALLBACK_RATES.items() if b != q
    }}


def clear_cache() -> None:
    with _lock:
        _cache.clear()


__all__ = [
    "FXRate", "get_rate", "convert", "to_base", "register_fx_provider",
    "currency_of_market", "symbol_currency", "rates_snapshot", "clear_cache",
    "DEFAULT_BASE", "FALLBACK_RATES",
]
