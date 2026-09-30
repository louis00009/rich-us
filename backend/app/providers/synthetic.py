"""合成行情（FILE_SIZE_DEBT Batch F-3 从 data_provider.py 拆出）。

⚠️ 铁律 13（诚实性）：source == 'synthetic' 的数字是**随机漫步编造的**，
不许当真实行情输出；前端必须告警。
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .common import _normalize


def _market_of(symbol: str) -> str:
    """判定标的市场（港股符号判断优先，失败回落后缀）。"""
    s = symbol.strip().upper()
    try:
        from ..markets import symbols as mksym
        return mksym.parse(s).market
    except Exception:  # noqa: BLE001
        return "HK" if s.endswith(".HK") else "US"



def _synthetic(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    """确定性合成行情：同一 symbol 永远生成同一序列，便于离线自检与演示。"""
    seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.now().normalize()
    start_ts = pd.Timestamp(start)
    freq = {"1d": "B", "1wk": "W-FRI", "1h": "h", "30m": "30min", "15m": "15min", "5m": "5min", "1m": "1min"}[interval]
    idx = pd.date_range(start_ts, end_ts, freq=freq)
    if len(idx) < 60:
        idx = pd.date_range(end_ts - pd.Timedelta(days=800), end_ts, freq=freq)
    n = len(idx)
    base = 30.0 + (seed % 400)
    drift = ((seed % 100) / 100.0 - 0.35) * 0.0004
    vol = 0.010 + (seed % 23) / 1000.0
    rets = rng.normal(drift, vol, n)
    # 叠加温和的均值回归与波动率聚集
    for i in range(1, n):
        rets[i] -= 0.06 * rets[i - 1]
    vol_series = np.abs(rng.normal(1.0, 0.25, n)).clip(0.4, 3.0)
    rets = rets * vol_series
    close = base * np.exp(np.cumsum(rets))
    intra = np.abs(rng.normal(0, vol, n)) * close
    open_ = np.concatenate([[close[0] * (1 - rets[0])], close[:-1]])
    high = np.maximum(open_, close) + intra * 0.6
    low = np.minimum(open_, close) - intra * 0.6
    volume = (rng.lognormal(15.5, 0.5, n)).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    ).pipe(_normalize)

