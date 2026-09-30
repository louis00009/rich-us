"""风险平价配置（inverse-vol，可选动量过滤）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy
from ..frames import realized_vol
from ..registry import register


# ==================================================================
# 风险平价配置
# ==================================================================
@register
class RiskParityAlloc(Strategy):
    key = "risk_parity_alloc"
    name = "风险平价配置"
    category = "进阶前沿"
    description = (
        "按各标的已实现波动率倒数分配权重，使每个标的对组合的风险贡献大致相等。"
        "可选叠加动量过滤（仅配置趋势向上的标的）。作为长期底仓配置层非常稳健，"
        "也是当前主流『全天候』组合的构建方式。"
    )
    tags = ["配置", "风险平价", "稳健", "低回撤"]
    min_bars = 260

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("vol_window", "波动率窗口", "int", 60, 10, 252, 5, group="风险"),
            ParamSpec("trend_filter", "动量过滤", "bool", True, group="过滤"),
            ParamSpec("trend_lookback", "动量回看", "int", 126, 10, 504, 5, group="过滤"),
            ParamSpec("gross", "总敞口", "float", 1.0, 0.1, 2.0, 0.05, group="仓位"),
            ParamSpec("max_weight", "单标的上限", "float", 0.4, 0.05, 1.0, 0.05, group="仓位"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 21, 1, 126, 1, group="执行"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        rv = realized_vol(c, int(self.params["vol_window"])).replace(0, np.nan)
        inv = 1.0 / rv
        w = inv.div(inv.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
        if self.params["trend_filter"]:
            ok = (c / c.shift(int(self.params["trend_lookback"])) - 1) > 0
            w = w.where(ok, 0.0)
            s = w.sum(axis=1).replace(0, np.nan)
            w = w.div(s, axis=0).fillna(0.0)
        w = w.clip(upper=float(self.params["max_weight"]))
        w = w * float(self.params["gross"])
        mask = np.zeros(len(w), dtype=bool)
        mask[:: int(self.params["rebalance_days"])] = True
        w.loc[~mask, :] = np.nan
        return w.ffill().fillna(0.0)
