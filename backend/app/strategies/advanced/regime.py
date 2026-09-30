"""状态自适应（趋势 / 均值回归随波动率与效率比切换）。"""
from __future__ import annotations

import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy
from ..frames import efficiency_ratio, realized_vol, sma, zscore
from ..registry import register


# ==================================================================
# 状态自适应（趋势 / 均值回归切换）
# ==================================================================
@register
class RegimeAdaptive(Strategy):
    key = "regime_adaptive"
    name = "状态自适应切换"
    category = "进阶前沿"
    description = (
        "先判定市场状态再选武器：低波动 + 高效率比 → 趋势跟随；"
        "高波动 + 低效率比 → 均值回归；波动率极端高位 → 主动降仓至防御水平。"
        "解决『一套参数打天下』的根本缺陷，也是当前多策略平台的标准做法。"
    )
    tags = ["状态识别", "自适应", "多策略", "波动率择时"]
    min_bars = 300

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("vol_window", "波动率窗口", "int", 20, 5, 120, 1, group="状态"),
            ParamSpec("vol_pct_window", "波动率分位窗口", "int", 252, 60, 756, 21, group="状态"),
            ParamSpec("high_vol_pct", "高波动分位", "float", 0.75, 0.5, 0.99, 0.01, group="状态"),
            ParamSpec("extreme_vol_pct", "极端波动分位", "float", 0.95, 0.7, 1.0, 0.01, group="状态"),
            ParamSpec("er_threshold", "效率比阈值", "float", 0.35, 0.1, 0.8, 0.05, group="状态"),
            ParamSpec("trend_fast", "趋势快线", "int", 20, 5, 100, 1, group="趋势腿"),
            ParamSpec("trend_slow", "趋势慢线", "int", 100, 20, 300, 5, group="趋势腿"),
            ParamSpec("mr_window", "回归 Z 窗口", "int", 20, 5, 100, 1, group="回归腿"),
            ParamSpec("mr_entry", "回归入场 Z", "float", 1.5, 0.5, 4.0, 0.1, group="回归腿"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        rv = realized_vol(c, int(self.params["vol_window"]))
        pctw = int(self.params["vol_pct_window"])
        vol_pct = rv.rolling(pctw, min_periods=max(20, pctw // 4)).rank(pct=True)
        er = efficiency_ratio(c, 20)
        z = zscore(c, int(self.params["mr_window"]))
        fast, slow = sma(c, int(self.params["trend_fast"])), sma(c, int(self.params["trend_slow"]))

        hi, ex = float(self.params["high_vol_pct"]), float(self.params["extreme_vol_pct"])
        eth = float(self.params["er_threshold"])
        mr_ent = float(self.params["mr_entry"])

        trend_leg = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        trend_leg[(fast > slow) & (er >= eth)] = 1.0
        if self.params["allow_short"]:
            trend_leg[(fast < slow) & (er >= eth)] = -1.0

        mr_leg = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        mr_leg[(z <= -mr_ent) & (er < eth)] = 1.0
        if self.params["allow_short"]:
            mr_leg[(z >= mr_ent) & (er < eth)] = -1.0

        w = trend_leg.where(vol_pct <= hi, mr_leg)
        w = w.where(vol_pct <= ex, 0.0)
        w = w.fillna(0.0)
        # 高波动区间整体降风险
        de_risk = (1.0 - 0.5 * ((vol_pct - hi) / max(ex - hi, 1e-6)).clip(0, 1)).fillna(1.0)
        return (w * de_risk).clip(-1, 1)
