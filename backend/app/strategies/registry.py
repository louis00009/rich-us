"""策略注册表。"""
from __future__ import annotations

from typing import Type

from .base import Strategy, spec_to_dict

_REGISTRY: dict[str, Type[Strategy]] = {}
_CATEGORIES: dict[str, str] = {}


def register(cls: Type[Strategy]) -> Type[Strategy]:
    if not getattr(cls, "key", None) or cls.key == "base":
        raise ValueError(f"{cls.__name__} 缺少有效 key")
    if cls.key in _REGISTRY:
        raise ValueError(f"策略 key 重复: {cls.key}")
    _REGISTRY[cls.key] = cls
    _CATEGORIES.setdefault(cls.category, cls.category)
    return cls


def get_strategy_class(key: str) -> Type[Strategy]:
    if key not in _REGISTRY:
        raise KeyError(f"未知策略: {key}")
    return _REGISTRY[key]


def create_strategy(key: str, params: dict | None = None) -> Strategy:
    return get_strategy_class(key)(**(params or {}))


def list_strategies() -> list[dict]:
    out = []
    for cls in _REGISTRY.values():
        out.append(
            {
                "key": cls.key,
                "name": cls.name,
                "category": cls.category,
                "description": cls.description,
                "multi_symbol": cls.multi_symbol,
                "min_bars": cls.min_bars,
                "tags": list(cls.tags),
                "params": [spec_to_dict(p) for p in cls.param_specs()],
            }
        )
    out.sort(key=lambda x: (x["category"], x["name"]))
    return out


def categories() -> list[str]:
    return sorted({c.category for c in _REGISTRY.values()})


def registry_size() -> int:
    return len(_REGISTRY)
