"""Stooq CSV 数据源（FILE_SIZE_DEBT Batch F-3 从 data_provider.py 拆出）。"""
from __future__ import annotations

import io
from datetime import datetime

import httpx
import pandas as pd

from ..config import settings
from .common import OHLCV, _normalize


def _stooq_symbol(symbol: str) -> str:
    s = symbol.lower()
    if s.startswith("^"):
        return s
    return f"{s}.us"



def _from_stooq(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    """Stooq 免费日线 CSV。仅日线可用。"""
    d1 = start.replace("-", "")
    d2 = (end or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    # P3：symbol 来自用户输入，旧实现直接拼进 URL 查询串 —— 含 & / ? / # 时
    # 会改变查询语义（等于注入额外参数）。改用 params 让 httpx 负责编码。
    params = {"s": _stooq_symbol(symbol), "d1": d1, "d2": d2, "i": "d"}
    with httpx.Client(timeout=settings.data_timeout_sec, follow_redirects=True) as c:
        r = c.get("https://stooq.com/q/d/l/", params=params,
                  headers={"User-Agent": "Mozilla/5.0 QuantDesk"})
    if r.status_code != 200 or "Date" not in r.text[:200]:
        return pd.DataFrame(columns=OHLCV)
    df = pd.read_csv(io.StringIO(r.text))
    if "Date" not in df.columns:
        return pd.DataFrame(columns=OHLCV)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    # P1-1 配套：Stooq 的日期是「交易日」本身（无时刻语义），不应被 UTC→NY 平移
    # 成前一天 20:00。naive_tz=None 让日期原样保留，同时保证幂等。
    return _normalize(df, naive_tz=None)



def v_st(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    if interval != "1d":
        return pd.DataFrame(columns=OHLCV)
    return _from_stooq(symbol, start, end)

