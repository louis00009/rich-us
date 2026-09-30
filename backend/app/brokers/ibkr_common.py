"""IBKR 适配层共享 helper（FILE_SIZE_DEBT Batch F-2 从 ibkr.py 拆出）。

_silent / _ContractSpec / BAR_MAP / INDEX_MAP：被多个域 mixin 引用的模块级定义。
ibkr.py 对它们做 re-export，旧 import 路径保持可用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _silent(exc: BaseException, where: str) -> None:
    """记录「几乎必然是代码缺陷」的异常（审查新-3）。

    本文件有十余处 `except Exception: pass/continue` —— 对券商 API 而言这是合理的
    容错策略（超时、限流、字段缺失都可能发生）。但它们会**连带吞掉代码缺陷**：
    项目历史上就因此漏掉过 `_from_yf` 的 NameError（静默、零输出、极难排查）。

    这里只对下面几类「基本只可能是 bug」的异常发声；网络/超时/业务异常保持静默，
    避免把日志刷成噪声。
    """
    if isinstance(exc, (NameError, UnboundLocalError, TypeError, AttributeError)):
        import logging

        logging.getLogger("quantdesk.ibkr").warning(
            "[ibkr] %s 吞掉疑似代码缺陷：%s: %s", where, type(exc).__name__, exc
        )



# ------------------------------------------------------------------
# 周期映射：我们的 interval → (IB barSize, 单次请求最大时长, 天数)
# IB 对「单次请求可覆盖的时长」有硬限制，超限会报错，因此需要分页拉取。
# ------------------------------------------------------------------
BAR_MAP: dict[str, tuple[str, str, int]] = {
    "1m": ("1 min", "1 D", 1),
    "2m": ("2 mins", "2 D", 2),
    "5m": ("5 mins", "1 W", 7),
    "15m": ("15 mins", "1 M", 30),
    "30m": ("30 mins", "1 M", 30),
    "1h": ("1 hour", "1 Y", 365),
    "1d": ("1 day", "1 Y", 365),
    "1wk": ("1 week", "1 Y", 365),
}

# 指数的 IB 合约标识（兼容旧的硬编码表；新代码走 markets.symbols）
INDEX_MAP: dict[str, tuple[str, str]] = {
    "^GSPC": ("SPX", "CBOE"),
    "^SPX": ("SPX", "CBOE"),
    "^NDX": ("NDX", "NASDAQ"),
    "^DJI": ("INDU", "CBOE"),
    "^VIX": ("VIX", "CBOE"),
    "^TNX": ("TNX", "CBOE"),
    "^RUT": ("RUT", "CBOE"),
}



@dataclass
class _ContractSpec:
    symbol: str
    sec_type: str
    exchange: str
    currency: str = "USD"
    primary_exchange: str | None = None
    market: str = "US"

