"""yfinance 数据源（FILE_SIZE_DEBT Batch F-3 从 data_provider.py 拆出）。

含全局熔断（任一 yfinance 挂起/空返 → _YF_BREAKER_SEC 秒内跳过 yfinance 一环）。
"""
from __future__ import annotations

import threading
import time

import pandas as pd

from .common import OHLCV, _normalize


# 全局 yfinance 熔断：yfinance 内部超时不可控（cookie/crumb 挂起实测 20~45s），
# 27 标的并发首拉能把冷启动拖到分钟级。任一 yfinance 调用挂起/空返 → 全局熔断
# _YF_BREAKER_SEC 秒：增量更新与免费链的 yfinance 一环全部跳过（回旧缓存/走下链），
# 任一 yfinance 成功 → 立即解除。健康时熔断永不触发，行为与原来完全一致。
_yf_fail_at: float = 0.0
_YF_BREAKER_SEC = 120.0
_YF_INC_TIMEOUT = 8.0           # 增量更新单次等待上限（健康时 1~3s 内返回）



def _from_yfinance(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    kw: dict = {"interval": interval, "auto_adjust": True, "actions": False}
    if interval == "1d":
        kw["start"] = start
        if end:
            kw["end"] = end
    else:
        # 1m 数据 Yahoo 只给近 7 天，请求 180d 会直接报错
        kw["period"] = {"1m": "5d", "5m": "60d", "15m": "60d", "30m": "60d"}.get(interval, "180d")
    df = ticker.history(**kw)
    return _normalize(df)



def _mark_yf_fail() -> None:
    global _yf_fail_at
    _yf_fail_at = time.time()



def _mark_yf_ok() -> None:
    global _yf_fail_at
    _yf_fail_at = 0.0



def yf_breaker_active() -> bool:
    return _yf_fail_at > 0 and time.time() - _yf_fail_at < _YF_BREAKER_SEC



def _yf_incremental_bounded(symbol: str, inc_start: str, end: str | None, interval: str) -> pd.DataFrame | None:
    """有界等待的 yfinance 增量拉取：超时按失败处理（返回 None）。

    超时后残留的守护线程会等 yfinance 内部超时后自行结束，不写缓存、不再累积。
    """
    box: dict[str, pd.DataFrame | None] = {}

    def _run() -> None:
        try:
            box["df"] = _from_yfinance(symbol, inc_start, end, interval)
        except Exception:  # noqa: BLE001
            box["df"] = None

    t = threading.Thread(target=_run, daemon=True, name=f"yf-inc-{symbol}")
    t.start()
    t.join(_YF_INC_TIMEOUT)
    return box.get("df")



def v_yf(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_yfinance(symbol, start, end, interval)

