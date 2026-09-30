"""providers 共享原语（FILE_SIZE_DEBT Batch F-3 从 data_provider.py 拆出）。

OHLCV 列契约 与 `_normalize` 归一化。
⚠️ 铁律：`_normalize` **非幂等** —— naive_tz 语义（默认 'UTC' / None / aware）
见 docstring，只能被调用一次的位置不能变。data_provider 对这两个符号做 re-export。
"""
from __future__ import annotations

import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame, naive_tz: str | None = "UTC") -> pd.DataFrame:
    """统一为「真实时刻的 NY naive」语义。

    naive_tz 语义（P1-1 幂等性配套）：
      * "UTC"（默认）—— naive 输入按 UTC 解释再转 NY（腾讯 m1 预转换的 UTC 序列依赖此语义）；
      * None         —— naive 输入已是 NY 墙钟时间，原样保留（幂等：重复调用不再漂移）；
      * aware 输入    —— 无论 naive_tz 取值，一律 tz_convert 到 NY 后去 tz。
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OHLCV)
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower().replace("adj close", "close") for c in df.columns]
    df = df.rename(columns={"adj_close": "close", "adjclose": "close"})
    for c in OHLCV:
        if c not in df.columns:
            if c == "volume":
                df["volume"] = 0.0
            elif c == "close":
                return pd.DataFrame(columns=OHLCV)
            else:
                df[c] = df["close"]
    df = df[OHLCV].apply(pd.to_numeric, errors="coerce")
    df.index = pd.to_datetime(df.index, utc=naive_tz is not None, errors="coerce")
    df = df[df.index.notna()]
    if naive_tz is not None:
        try:
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        except (TypeError, AttributeError):
            pass
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    df["volume"] = df["volume"].fillna(0.0)
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    return df

