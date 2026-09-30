"""ATR 自适应网格交易。"""
from __future__ import annotations

import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy
from ..frames import atr, sma
from ..registry import register


# ==================================================================
# 网格交易
# ==================================================================
@register
class GridTrading(Strategy):
    key = "grid_trading"
    name = "ATR 自适应网格"
    category = "进阶前沿"
    description = (
        "以锚定均线为中心、以 ATR 为间距铺设网格；价格每下跌一格加一档仓位、"
        "上涨一格减一档。震荡市收益稳定，单边下跌需设总仓位上限（本策略已内置）。"
        "锚点随长期均线漂移，避免固定价位网格在趋势市中失效。"
    )
    tags = ["网格", "震荡", "均值回归", "机械"]
    min_bars = 200

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("anchor_ma", "锚点均线", "int", 100, 20, 400, 10, group="信号"),
            ParamSpec("atr_n", "ATR 周期", "int", 20, 5, 60, 1, group="信号"),
            ParamSpec("grid_step_atr", "网格间距(ATR)", "float", 0.5, 0.1, 3.0, 0.1, group="信号"),
            ParamSpec("max_grids", "最大档数", "int", 6, 1, 20, 1, group="仓位"),
            ParamSpec("per_grid", "每档仓位", "float", 0.15, 0.02, 1.0, 0.01, group="仓位"),
            ParamSpec("stop_atr", "总体止损(ATR)", "float", 6.0, 1.0, 20.0, 0.5, group="风控"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        high, low, c = ctx.high, ctx.low, ctx.closes
        anchor = sma(c, int(self.params["anchor_ma"]))
        a = atr(high, low, c, int(self.params["atr_n"]))
        step = float(self.params["grid_step_atr"])
        mx = int(self.params["max_grids"])
        per = float(self.params["per_grid"])
        stop = float(self.params["stop_atr"])

        dev = (c - anchor) / (a * step + 1e-12)
        grids = (-dev).clip(lower=-mx, upper=0.0).abs()   # 低于锚点建仓，高于锚点空仓
        w = (grids * per).clip(upper=mx * per)
        total_dev = (c - anchor) / (a + 1e-12)
        w = w.where(total_dev > -stop, 0.0)               # 触发总止损 → 清仓
        return w.fillna(0.0)
