"""
技术指标库 —— 纯 pandas/numpy 实现，无 TA-Lib 依赖。
所有函数输入 Series/DataFrame，输出同索引 Series/DataFrame，不引入未来函数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


# ------------------------------------------------------------------
# 均线族
# ------------------------------------------------------------------
def sma(s: pd.Series, n: int = 20) -> pd.Series:
    return s.rolling(int(n), min_periods=max(2, int(n) // 2)).mean()


def ema(s: pd.Series, n: int = 20) -> pd.Series:
    return s.ewm(span=int(n), adjust=False, min_periods=max(2, int(n) // 2)).mean()


def wma(s: pd.Series, n: int = 20) -> pd.Series:
    n = int(n)
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=max(2, n // 2)).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)


def hma(s: pd.Series, n: int = 20) -> pd.Series:
    """Hull MA —— 低滞后趋势线。"""
    n = int(n)
    return wma(2 * wma(s, max(1, n // 2)) - wma(s, n), max(1, int(np.sqrt(n))))


def dema(s: pd.Series, n: int = 20) -> pd.Series:
    e1 = ema(s, n)
    return 2 * e1 - ema(e1, n)


def kama(s: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman 自适应均线。"""
    n = int(n)
    change = (s - s.shift(n)).abs()
    vol = s.diff().abs().rolling(n).sum()
    er = (change / (vol + EPS)).clip(0, 1)
    sc = (er * (2 / (fast + 1) - 2 / (slow + 1)) + 2 / (slow + 1)) ** 2
    out = np.full(len(s), np.nan)
    vals = s.to_numpy(dtype=float)
    scv = sc.to_numpy(dtype=float)
    start = n
    if len(s) <= start:
        return pd.Series(np.nan, index=s.index)
    out[start] = vals[start]
    for i in range(start + 1, len(s)):
        prev = out[i - 1] if not np.isnan(out[i - 1]) else vals[i - 1]
        out[i] = prev + scv[i] * (vals[i] - prev)
    return pd.Series(out, index=s.index)


# ------------------------------------------------------------------
# 动量 / 振荡
# ------------------------------------------------------------------
def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    n = int(n)
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / (dn + EPS)
    return 100 - 100 / (1 + rs)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(s, fast) - ema(s, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def stoch(
    high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3, smooth: int = 3
) -> pd.DataFrame:
    ll = low.rolling(int(k), min_periods=2).min()
    hh = high.rolling(int(k), min_periods=2).max()
    raw = 100 * (close - ll) / (hh - ll + EPS)
    kk = raw.rolling(int(smooth), min_periods=1).mean()
    return pd.DataFrame({"k": kk, "d": kk.rolling(int(d), min_periods=1).mean()})


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    hh = high.rolling(int(n), min_periods=2).max()
    ll = low.rolling(int(n), min_periods=2).min()
    return -100 * (hh - close) / (hh - ll + EPS)


def cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    ma = tp.rolling(int(n), min_periods=2).mean()
    md = (tp - ma).abs().rolling(int(n), min_periods=2).mean()
    return (tp - ma) / (0.015 * md + EPS)


def roc(s: pd.Series, n: int = 20) -> pd.Series:
    return s.pct_change(int(n)) * 100


def mom(s: pd.Series, n: int = 20) -> pd.Series:
    return s.diff(int(n))


# ------------------------------------------------------------------
# 波动率 / 通道
# ------------------------------------------------------------------
def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    pc = close.shift(1)
    return pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(alpha=1 / int(n), adjust=False, min_periods=int(n)).mean()


def natr(high, low, close, n: int = 14) -> pd.Series:
    return atr(high, low, close, n) / (close + EPS) * 100


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(s, n)
    sd = s.rolling(int(n), min_periods=max(2, int(n) // 2)).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    pctb = (s - lower) / (upper - lower + EPS)
    width = (upper - lower) / (mid + EPS)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "pctb": pctb, "width": width})


def keltner(high, low, close, n: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = ema(close, n)
    a = atr(high, low, close, n)
    return pd.DataFrame({"mid": mid, "upper": mid + mult * a, "lower": mid - mult * a})


def donchian(high: pd.Series, low: pd.Series, n: int = 20) -> pd.DataFrame:
    n = int(n)
    up = high.rolling(n, min_periods=2).max()
    dn = low.rolling(n, min_periods=2).min()
    return pd.DataFrame({"upper": up, "lower": dn, "mid": (up + dn) / 2})


def realized_vol(close: pd.Series, n: int = 20, ann: int = 252) -> pd.Series:
    return np.log(close / close.shift(1)).rolling(int(n), min_periods=max(3, int(n) // 2)).std(ddof=0) * np.sqrt(ann)


def zscore(s: pd.Series, n: int = 20) -> pd.Series:
    m = s.rolling(int(n), min_periods=max(3, int(n) // 2)).mean()
    sd = s.rolling(int(n), min_periods=max(3, int(n) // 2)).std(ddof=0)
    return (s - m) / (sd + EPS)


def atr_zscore(high, low, close, n: int = 20) -> pd.Series:
    a = atr(high, low, close, 14)
    return zscore(a, n)


# ------------------------------------------------------------------
# 趋势强度
# ------------------------------------------------------------------
def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.DataFrame:
    n = int(n)
    up = high.diff()
    dn = -low.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / (atr_ + EPS)
    mdi = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / (atr_ + EPS)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + EPS)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(), "plus_di": pdi, "minus_di": mdi})


def efficiency_ratio(close: pd.Series, n: int = 20) -> pd.Series:
    """Kaufman 效率比：>0.5 趋势市，<0.3 震荡市。"""
    n = int(n)
    return ((close - close.shift(n)).abs() / (close.diff().abs().rolling(n).sum() + EPS)).clip(0, 1)


def hurst(close: pd.Series, n: int = 128) -> float:
    """简化 Hurst 指数：>0.5 趋势持续，<0.5 均值回归。"""
    s = close.dropna().to_numpy(dtype=float)[-int(n):]
    if len(s) < 64:
        return 0.5
    lags = np.array([2, 4, 8, 16, 32, 64])
    lags = lags[lags < len(s) // 2]
    tau = [np.std(s[lag:] - s[:-lag]) for lag in lags]
    tau = np.array(tau)
    ok = tau > 0
    if ok.sum() < 3:
        return 0.5
    poly = np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)
    return float(np.clip(poly[0], 0.0, 1.0))


# ------------------------------------------------------------------
# 量能
# ------------------------------------------------------------------
def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def volume_ratio(volume: pd.Series, n: int = 20) -> pd.Series:
    return volume / (volume.rolling(int(n), min_periods=max(2, int(n) // 2)).mean() + EPS)


def mfi(high, low, close, volume, n: int = 14) -> pd.Series:
    tp = (high + low + close) / 3
    mf = tp * volume
    pos = mf.where(tp.diff() > 0, 0.0).rolling(int(n), min_periods=2).sum()
    neg = mf.where(tp.diff() < 0, 0.0).rolling(int(n), min_periods=2).sum()
    return 100 - 100 / (1 + pos / (neg + EPS))


def cmf(high, low, close, volume, n: int = 20) -> pd.Series:
    """蔡金资金流 —— 机构吸筹/派发。"""
    mfm = ((close - low) - (high - close)) / (high - low + EPS)
    return (mfm * volume).rolling(int(n), min_periods=2).sum() / (volume.rolling(int(n), min_periods=2).sum() + EPS)


# ------------------------------------------------------------------
# 日内
# ------------------------------------------------------------------
def vwap_session(high, low, close, volume) -> pd.Series:
    """按交易日锚定的 VWAP。"""
    tp = (high + low + close) / 3
    idx = close.index
    day = pd.Series(idx.normalize() if hasattr(idx, "normalize") else idx.date, index=idx)
    pv = (tp * volume).groupby(day).cumsum()
    vv = volume.groupby(day).cumsum()
    return pv / (vv + EPS)


def rolling_vwap(high, low, close, volume, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    return (tp * volume).rolling(int(n), min_periods=2).sum() / (volume.rolling(int(n), min_periods=2).sum() + EPS)


def opening_range(high: pd.Series, low: pd.Series, minutes: int = 30, bar_minutes: int = 5) -> pd.DataFrame:
    """开盘区间高低点（按日重置，只使用当日已完成的 bar）。"""
    bars = max(1, int(minutes) // max(1, int(bar_minutes)))
    idx = high.index
    day = pd.Series(idx.normalize() if hasattr(idx, "normalize") else idx.date, index=idx)
    pos = high.groupby(day).cumcount()
    mask = pos < bars
    hi = high.where(mask).groupby(day).cummax()
    lo = low.where(mask).groupby(day).cummin()
    return pd.DataFrame({"or_high": hi.groupby(day).ffill(), "or_low": lo.groupby(day).ffill()})

def _unused() -> None:  # pragma: no cover
    return None


# ------------------------------------------------------------------
# 统计 / 研究工具
# ------------------------------------------------------------------
def adf_test(series: pd.Series, max_lag: int | None = None) -> dict:
    """
    Augmented Dickey-Fuller 单位根检验（自实现，无需 statsmodels）。
    返回 t 统计量与近似临界值；t < 临界值 → 拒绝单位根（序列平稳）。
    """
    s = pd.Series(series).dropna().to_numpy(dtype=float)
    if len(s) < 30:
        return {"t_stat": 0.0, "stationary": False, "n": len(s)}
    y = np.diff(s)
    lag = max_lag if max_lag is not None else int(np.floor(12 * (len(s) / 100) ** 0.25))
    lag = max(1, min(lag, len(y) // 4))
    y_t = y[lag:]
    X = [np.ones(len(y_t)), s[lag:-1]]
    for i in range(1, lag + 1):
        X.append(y[lag - i: -i])
    Xm = np.column_stack(X)
    try:
        beta, *_ = np.linalg.lstsq(Xm, y_t, rcond=None)
        resid = y_t - Xm @ beta
        dof = max(1, len(y_t) - Xm.shape[1])
        sigma2 = float(resid @ resid) / dof
        cov = sigma2 * np.linalg.pinv(Xm.T @ Xm)
        se = float(np.sqrt(max(cov[1, 1], 1e-18)))
        t_stat = float(beta[1] / se)
    except np.linalg.LinAlgError:
        return {"t_stat": 0.0, "stationary": False, "n": len(s)}
    # MacKinnon 近似临界值（含常数项）
    crit = {"1%": -3.43, "5%": -2.86, "10%": -2.57}
    return {
        "t_stat": round(t_stat, 4),
        "crit": crit,
        "stationary": t_stat < crit["5%"],
        "lag": lag,
        "n": len(s),
    }


def half_life(series: pd.Series) -> float:
    """Ornstein-Uhlenbeck 半衰期（均值回归速度），单位：bar。"""
    s = pd.Series(series).dropna()
    if len(s) < 30:
        return float("nan")
    y = s.diff().dropna()
    x = s.shift(1).dropna()
    x, y = x.align(y, join="inner")
    xm = np.column_stack([np.ones(len(x)), x.to_numpy(float)])
    try:
        beta, *_ = np.linalg.lstsq(xm, y.to_numpy(float), rcond=None)
    except np.linalg.LinAlgError:
        return float("nan")
    lam = beta[1]
    if lam >= 0:
        return float("inf")
    return float(-np.log(2) / lam)


def hedge_ratio(y: pd.Series, x: pd.Series) -> float:
    """OLS 对冲比率 y = beta * x + alpha。"""
    a, b = x.align(y, join="inner")
    xm = np.column_stack([np.ones(len(a)), a.to_numpy(float)])
    try:
        beta, *_ = np.linalg.lstsq(xm, b.to_numpy(float), rcond=None)
        return float(beta[1])
    except np.linalg.LinAlgError:
        return 1.0


def rolling_beta(asset: pd.Series, bench: pd.Series, n: int = 60) -> pd.Series:
    ra, rb = asset.pct_change(), bench.pct_change()
    cov = ra.rolling(int(n), min_periods=int(n) // 2).cov(rb)
    var = rb.rolling(int(n), min_periods=int(n) // 2).var()
    return cov / (var + EPS)


def correlation_matrix(data: dict[str, pd.DataFrame], n: int = 120) -> pd.DataFrame:
    ser = {k: v["close"].pct_change() for k, v in data.items() if len(v) > 5}
    if not ser:
        return pd.DataFrame()
    return pd.DataFrame(ser).tail(int(n)).corr()


def feature_frame(df: pd.DataFrame, bench: pd.Series | None = None) -> pd.DataFrame:
    """为 ML alpha 构造特征矩阵（全部基于当期及历史，无未来函数）。"""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    out = pd.DataFrame(index=df.index)
    out["ret1"] = c.pct_change(1)
    out["ret5"] = c.pct_change(5)
    out["ret10"] = c.pct_change(10)
    out["ret20"] = c.pct_change(20)
    out["ret60"] = c.pct_change(60)
    out["rsi14"] = rsi(c, 14) / 100.0
    out["rsi2"] = rsi(c, 2) / 100.0
    out["macd_hist"] = macd(c)["hist"] / (c + EPS)
    out["z20"] = zscore(c, 20)
    out["z60"] = zscore(c, 60)
    out["vol20"] = realized_vol(c, 20)
    out["vol_ratio"] = volume_ratio(v, 20)
    out["atr_pct"] = natr(h, l, c, 14) / 100.0
    ad = adx(h, l, c, 14)
    out["adx"] = ad["adx"] / 100.0
    out["di_spread"] = (ad["plus_di"] - ad["minus_di"]) / 100.0
    bb = bollinger(c, 20, 2)
    out["bb_pctb"] = bb["pctb"]
    out["bb_width"] = bb["width"]
    out["dist_sma50"] = c / (sma(c, 50) + EPS) - 1
    out["dist_sma200"] = c / (sma(c, 200) + EPS) - 1
    out["cmf20"] = cmf(h, l, c, v, 20)
    out["er20"] = efficiency_ratio(c, 20)
    out["dow"] = out.index.dayofweek
    out["month"] = out.index.month
    if bench is not None:
        b = bench.reindex(df.index)
        out["rel_ret20"] = c.pct_change(20) - b.pct_change(20)
        out["rel_ret60"] = c.pct_change(60) - b.pct_change(60)
        out["beta60"] = rolling_beta(c, b, 60)
    return out.replace([np.inf, -np.inf], np.nan)


INDICATOR_CATALOG: list[dict] = [
    {"key": "close", "label": "收盘价", "group": "价格"},
    {"key": "open", "label": "开盘价", "group": "价格"},
    {"key": "high", "label": "最高价", "group": "价格"},
    {"key": "low", "label": "最低价", "group": "价格"},
    {"key": "volume", "label": "成交量", "group": "价格"},
    {"key": "sma", "label": "简单均线 SMA", "group": "均线", "param": "period"},
    {"key": "ema", "label": "指数均线 EMA", "group": "均线", "param": "period"},
    {"key": "hma", "label": "Hull 均线 HMA", "group": "均线", "param": "period"},
    {"key": "kama", "label": "自适应均线 KAMA", "group": "均线", "param": "period"},
    {"key": "rsi", "label": "相对强弱 RSI", "group": "振荡", "param": "period"},
    {"key": "macd_hist", "label": "MACD 柱", "group": "振荡"},
    {"key": "macd", "label": "MACD 线", "group": "振荡"},
    {"key": "stoch_k", "label": "随机指标 %K", "group": "振荡", "param": "period"},
    {"key": "cci", "label": "顺势指标 CCI", "group": "振荡", "param": "period"},
    {"key": "williams_r", "label": "威廉指标 %R", "group": "振荡", "param": "period"},
    {"key": "mfi", "label": "资金流量 MFI", "group": "量能", "param": "period"},
    {"key": "atr", "label": "真实波幅 ATR", "group": "波动", "param": "period"},
    {"key": "natr", "label": "ATR 占比 %", "group": "波动", "param": "period"},
    {"key": "bb_pctb", "label": "布林 %B", "group": "波动"},
    {"key": "bb_width", "label": "布林带宽", "group": "波动"},
    {"key": "bb_upper", "label": "布林上轨", "group": "波动"},
    {"key": "bb_lower", "label": "布林下轨", "group": "波动"},
    {"key": "adx", "label": "趋势强度 ADX", "group": "趋势", "param": "period"},
    {"key": "plus_di", "label": "+DI", "group": "趋势", "param": "period"},
    {"key": "minus_di", "label": "-DI", "group": "趋势", "param": "period"},
    {"key": "zscore", "label": "Z 分数", "group": "统计", "param": "period"},
    {"key": "roc", "label": "变动率 ROC", "group": "动量", "param": "period"},
    {"key": "vol_ratio", "label": "量比", "group": "量能", "param": "period"},
    {"key": "obv", "label": "能量潮 OBV", "group": "量能"},
    {"key": "cmf", "label": "蔡金资金流 CMF", "group": "量能", "param": "period"},
    {"key": "realized_vol", "label": "已实现波动率", "group": "波动", "param": "period"},
    {"key": "efficiency_ratio", "label": "效率比 ER", "group": "趋势", "param": "period"},
    {"key": "donchian_upper", "label": "唐奇安上轨", "group": "通道", "param": "period"},
    {"key": "donchian_lower", "label": "唐奇安下轨", "group": "通道", "param": "period"},
    {"key": "vwap", "label": "滚动 VWAP", "group": "日内", "param": "period"},
    {"key": "dist_sma50", "label": "距 SMA50 偏离", "group": "趋势"},
    {"key": "dist_sma200", "label": "距 SMA200 偏离", "group": "趋势"},
]


def compute_indicator(df: pd.DataFrame, key: str, period: int = 14) -> pd.Series:
    """按 key 计算单个指标序列 —— 供规则 DSL / 前端图表使用。"""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    k = key.lower()
    simple = {
        "close": lambda: c, "open": lambda: df["open"], "high": h, "low": l, "volume": v,
        "sma": lambda: sma(c, period), "ema": lambda: ema(c, period),
        "hma": lambda: hma(c, period), "kama": lambda: kama(c, period),
        "rsi": lambda: rsi(c, period), "cci": lambda: cci(h, l, c, period),
        "williams_r": lambda: williams_r(h, l, c, period),
        "mfi": lambda: mfi(h, l, c, v, period), "atr": lambda: atr(h, l, c, period),
        "natr": lambda: natr(h, l, c, period), "zscore": lambda: zscore(c, period),
        "roc": lambda: roc(c, period), "vol_ratio": lambda: volume_ratio(v, period),
        "obv": lambda: obv(c, v), "cmf": lambda: cmf(h, l, c, v, period),
        "realized_vol": lambda: realized_vol(c, period),
        "efficiency_ratio": lambda: efficiency_ratio(c, period),
        "donchian_upper": lambda: donchian(h, l, period)["upper"],
        "donchian_lower": lambda: donchian(h, l, period)["lower"],
        "vwap": lambda: rolling_vwap(h, l, c, v, period),
        "bb_upper": lambda: bollinger(c, period, 2)["upper"],
        "bb_lower": lambda: bollinger(c, period, 2)["lower"],
        "bb_pctb": lambda: bollinger(c, period, 2)["pctb"],
        "bb_width": lambda: bollinger(c, period, 2)["width"],
        "atr_zscore": lambda: atr_zscore(h, l, c, period),
    }
    if k in simple:
        return simple[k]()
    if k == "macd":
        return macd(c)["macd"]
    if k == "macd_hist":
        return macd(c)["hist"]
    if k == "macd_signal":
        return macd(c)["signal"]
    if k in ("stoch_k", "stoch_d"):
        return stoch(h, l, c)[k.split("_")[1]]
    if k in ("adx", "plus_di", "minus_di"):
        return adx(h, l, c, period)[k]
    if k == "dist_sma50":
        return c / (sma(c, 50) + EPS) - 1
    if k == "dist_sma200":
        return c / (sma(c, 200) + EPS) - 1
    raise KeyError(f"未知指标: {key}")
