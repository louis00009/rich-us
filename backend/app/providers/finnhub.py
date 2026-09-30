"""Finnhub 数据源（FILE_SIZE_DEBT Batch F-3 从 data_provider.py 拆出）。"""
from __future__ import annotations

from datetime import datetime

import httpx
import pandas as pd

from ..config import settings
from .common import OHLCV, _normalize
from .synthetic import _market_of


def _from_finnhub(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    """Finnhub 美股日线备援（需要 key；免费档失败时返回空，让降级链继续）。"""
    from ..config import settings as _s

    if interval != "1d" or _market_of(symbol) != "US" or not _s.finnhub_api_key:
        return pd.DataFrame(columns=OHLCV)
    d1 = start.replace("-", "")
    d2 = (end or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    url = (
        f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}"
        f"&from={d1}&to={d2}&resolution=D&token={_s.finnhub_api_key}"
    )
    try:
        with httpx.Client(timeout=settings.data_timeout_sec) as c:
            r = c.get(url)
        r.raise_for_status()
        data = r.json()
        if data.get("s") != "ok":
            return pd.DataFrame(columns=OHLCV)
        df = pd.DataFrame({
            "date": pd.to_datetime(data["t"], unit="s"),
            "open": data["o"], "high": data["h"],
            "low": data["l"], "close": data["c"], "volume": data["v"],
        }).set_index("date")
        return _normalize(df)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=OHLCV)



def v_fh(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_finnhub(symbol, start, end, interval)

