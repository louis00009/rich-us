"""策略基类与参数规格。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ParamSpec:
    key: str
    label: str
    type: str = "float"           # int | float | bool | choice | symbols
    default: Any = 0
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[Any] | None = None
    group: str = "参数"
    help: str = ""


@dataclass
class SignalContext:
    """策略输入上下文。"""
    data: dict[str, pd.DataFrame]
    symbols: list[str]
    bench: pd.Series | None = None
    timeframe: str = "1d"
    _closes: pd.DataFrame | None = field(default=None, repr=False)

    @property
    def closes(self) -> pd.DataFrame:
        if self._closes is None:
            ser = {s: df["close"] for s, df in self.data.items() if len(df)}
            self._closes = pd.DataFrame(ser).sort_index() if ser else pd.DataFrame()
        return self._closes

    @property
    def high(self) -> pd.DataFrame:
        return pd.DataFrame({s: df["high"] for s, df in self.data.items()}).sort_index()

    @property
    def low(self) -> pd.DataFrame:
        return pd.DataFrame({s: df["low"] for s, df in self.data.items()}).sort_index()

    @property
    def volume(self) -> pd.DataFrame:
        return pd.DataFrame({s: df["volume"] for s, df in self.data.items()}).sort_index()

    @property
    def n_bars(self) -> int:
        return max((len(d) for d in self.data.values()), default=0)


class Strategy(ABC):
    key: str = "base"
    name: str = "基类"
    category: str = "其他"
    description: str = ""
    tags: list[str] = []
    multi_symbol: bool = True
    min_bars: int = 60

    def __init__(self, **params: Any) -> None:
        self.params: dict[str, Any] = {**self.defaults(), **{k: v for k, v in params.items() if v is not None}}
        self.validate()
        self.notes: list[str] = []

    # ---------------- 元信息 ----------------
    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return []

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {p.key: p.default for p in cls.param_specs()}

    def validate(self) -> None:
        for p in self.param_specs():
            v = self.params.get(p.key, p.default)
            if p.type in ("int", "float"):
                try:
                    v = float(v)
                    if p.min is not None:
                        v = max(v, p.min)
                    if p.max is not None:
                        v = min(v, p.max)
                    self.params[p.key] = int(v) if p.type == "int" else float(v)
                except (TypeError, ValueError):
                    self.params[p.key] = p.default
            elif p.type == "choice" and p.choices and v not in p.choices:
                self.params[p.key] = p.default
            elif p.type == "bool":
                self.params[p.key] = bool(v)

    # ---------------- 结果规范化 ----------------
    @abstractmethod
    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        """返回 DataFrame(index=时间, columns=symbols, values=目标权重 ∈ [-1,1])。"""

    def normalize(self, raw: pd.DataFrame, ctx: SignalContext) -> pd.DataFrame:
        """对齐索引/列，裁剪权重，填充 NaN。"""
        cols = ctx.symbols
        if raw is None or len(raw) == 0:
            return pd.DataFrame(0.0, index=ctx.closes.index, columns=cols)
        out = raw.copy()
        out = out.reindex(columns=cols)
        all_dates = ctx.closes.index.union(out.index)
        out = out.reindex(all_dates).ffill().fillna(0.0)
        out = out.clip(lower=-1.0, upper=1.0)
        return out.reindex(ctx.closes.index).fillna(0.0)

    def run(self, ctx: SignalContext) -> pd.DataFrame:
        raw = self.generate(ctx)
        return self.normalize(raw, ctx)

    # ---------------- 工具 ----------------
    @staticmethod
    def cross_up(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
        return (a > b) & (a.shift(1) <= b.shift(1))

    @staticmethod
    def cross_down(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
        return (a < b) & (a.shift(1) >= b.shift(1))

    @staticmethod
    def state_weights(cond_long: pd.DataFrame, cond_short: pd.DataFrame, size: float = 1.0) -> pd.DataFrame:
        """由多/空布尔条件生成 -size..size 的目标权重。"""
        w = pd.DataFrame(0.0, index=cond_long.index, columns=cond_long.columns)
        w[cond_long] = size
        w[cond_short] = -size
        return w

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "category": self.category,
            "description": self.description, "multi_symbol": self.multi_symbol,
            "min_bars": self.min_bars, "tags": self.tags, "params": self.params,
            "notes": self.notes,
        }


def spec_to_dict(s: ParamSpec) -> dict[str, Any]:
    d = asdict(s)
    return {k: v for k, v in d.items() if v is not None}


def rank_to_weights(score: pd.DataFrame, top_n: int, long_only: bool = True, gross: float = 1.0) -> pd.DataFrame:
    """
    横截面打分 → 等权权重。
    score: index=日期, columns=symbols, 值越大越看多。逐行排名，仅持有前 top_n。
    """
    out = pd.DataFrame(0.0, index=score.index, columns=score.columns)
    arr = score.to_numpy(dtype=float)
    n = arr.shape[1]
    k = int(max(1, min(top_n, n)))
    for i in range(arr.shape[0]):
        row = arr[i]
        valid = np.where(np.isfinite(row))[0]
        if len(valid) == 0:
            continue
        idx = valid[np.argsort(-row[valid])[:k]]
        out.iloc[i, idx] = gross / k
    return out
