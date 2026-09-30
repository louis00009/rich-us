"""波动率管理动量（Moreira & Muir 2017）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy
from ..frames import realized_vol
from ..registry import register


# ==================================================================
# 波动率管理动量
# ==================================================================
@register
class VolManagedMomentum(Strategy):
    key = "vol_managed_momentum"
    name = "波动率管理动量"
    category = "进阶前沿"
    description = (
        "Moreira & Muir (2017) 的核心结论：把动量仓位乘以「目标方差 / 上一期已实现方差」，"
        "即可显著提升夏普并大幅降低回撤——因为波动率具有聚集性且与未来收益负相关。"
        "这是当前学术与实务公认性价比最高的风险缩放改进之一。"
    )
    tags = ["动量", "波动率管理", "学术", "夏普提升"]
    min_bars = 300

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("mom_lookback", "动量回看(bar)", "int", 126, 10, 504, 5, group="信号"),
            ParamSpec("vol_window", "方差窗口(bar)", "int", 21, 5, 252, 5, group="风险"),
            ParamSpec("target_vol", "目标年化波动率", "float", 0.12, 0.02, 0.60, 0.01, group="风险"),
            ParamSpec("max_leverage", "杠杆上限", "float", 1.5, 0.1, 3.0, 0.1, group="风险"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 21, 1, 126, 1, group="执行"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        momo = c / c.shift(int(self.params["mom_lookback"])) - 1
        direction = np.sign(momo).fillna(0.0)
        if not self.params["allow_short"]:
            direction = direction.clip(lower=0.0)
        rv = realized_vol(c, int(self.params["vol_window"])).shift(1).replace(0, np.nan)
        scale = (float(self.params["target_vol"]) / rv).clip(upper=float(self.params["max_leverage"])).fillna(0.0)
        w = (direction * scale).clip(-float(self.params["max_leverage"]), float(self.params["max_leverage"]))
        w = w.where(c.notna(), 0.0)
        mask = np.zeros(len(w), dtype=bool)
        mask[:: int(self.params["rebalance_days"])] = True
        w.loc[~mask, :] = np.nan
        return w.ffill().fillna(0.0)
