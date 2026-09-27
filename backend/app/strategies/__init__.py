"""策略包 —— 导入即完成内置策略注册。"""
from __future__ import annotations

from .base import ParamSpec, SignalContext, Strategy, rank_to_weights  # noqa: F401
from .registry import (  # noqa: F401
    categories,
    create_strategy,
    get_strategy_class,
    list_strategies,
    register,
    registry_size,
)

# 触发注册（顺序无关）
from . import builtin_trend  # noqa: F401,E402
from . import builtin_reversion  # noqa: F401,E402
from . import builtin_intraday  # noqa: F401,E402
from . import builtin_advanced  # noqa: F401,E402

__all__ = [
    "ParamSpec", "SignalContext", "Strategy", "rank_to_weights",
    "register", "list_strategies", "create_strategy", "get_strategy_class",
    "categories", "registry_size",
]
