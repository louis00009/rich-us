"""
DataFrame 级指标助手 —— 列 = 标的，行 = 时间。
用于多标的策略的向量化计算（避免逐列循环）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


def sma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(int(n), min_periods=max(2, int(n) // 2)).mean()


def ema(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.ewm(span=int(n), adjust=False, min_periods=max(2, int(n) // 2)).mean()


def rsi(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    n = int(n)
    d = df.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / (dn + EPS))


def macd_hist(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(df, fast) - ema(df, slow)
    return line - ema(line, signal)


def atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / int(n), adjust=False, min_periods=int(n)).mean()


def true_range(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """真实波幅（DataFrame 版，避免 stack/unstack 在 pandas 3.x 上的语义变化）。"""
    pc = close.shift(1)
    a = (high - low).to_numpy(dtype=float)
    b = (high - pc).abs().to_numpy(dtype=float)
    c = (low - pc).abs().to_numpy(dtype=float)
    tr = np.fmax(np.fmax(a, b), c)
    return pd.DataFrame(tr, index=close.index, columns=close.columns)


def natr(high, low, close, n: int = 14) -> pd.DataFrame:
    return atr(high, low, close, n) / (close + EPS) * 100


def bollinger(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    mid = sma(df, n)
    sd = df.rolling(int(n), min_periods=max(2, int(n) // 2)).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def zscore(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    m = df.rolling(int(n), min_periods=max(3, int(n) // 2)).mean()
    sd = df.rolling(int(n), min_periods=max(3, int(n) // 2)).std(ddof=0)
    return (df - m) / (sd + EPS)


def realized_vol(df: pd.DataFrame, n: int = 20, ann: int = 252) -> pd.DataFrame:
    return np.log(df / df.shift(1)).rolling(int(n), min_periods=max(3, int(n) // 2)).std(ddof=0) * np.sqrt(ann)


def donchian(high: pd.DataFrame, low: pd.DataFrame, n: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = int(n)
    return high.rolling(n, min_periods=2).max(), low.rolling(n, min_periods=2).min()


def adx(high, low, close, n: int = 14) -> pd.DataFrame:
    n = int(n)
    up = high.diff()
    dn = -low.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    a = true_range(high, low, close).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / (a + EPS)
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / (a + EPS)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + EPS)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def efficiency_ratio(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    n = int(n)
    return ((df - df.shift(n)).abs() / (df.diff().abs().rolling(n).sum() + EPS)).clip(0, 1)


def roc(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return df / (df.shift(int(n)) + EPS) - 1


def volume_ratio(vol: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return vol / (vol.rolling(int(n), min_periods=max(2, int(n) // 2)).mean() + EPS)


def rank_norm(df: pd.DataFrame) -> pd.DataFrame:
    """逐行横截面排名归一化到 [-1, 1]。"""
    return df.rank(axis=1, pct=True) * 2 - 1


def rolling_beta(asset: pd.DataFrame, bench: pd.Series, n: int = 60) -> pd.DataFrame:
    b = bench.reindex(asset.index)
    rb = b.pct_change()
    ra = asset.pct_change()
    cov = ra.rolling(int(n), min_periods=int(n) // 2).cov(rb)
    var = rb.rolling(int(n), min_periods=int(n) // 2).var()
    return cov.div(var + EPS, axis=0)


def trend_score(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    """多周期趋势综合分：均线位置 + 斜率 + 动量，输出 [-1,1]。"""
    f, s = sma(df, fast), sma(df, slow)
    pos = np.sign(f - s)
    slope = np.sign(s - s.shift(int(slow / 4)))
    momo = np.sign(df - df.shift(int(fast / 2)))
    return ((pos + slope + momo) / 3.0).clip(-1, 1)


def apply_columnwise(fn, df: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
    return pd.concat([fn(df[c], *args, **kwargs).rename(c) for c in df.columns], axis=1)
