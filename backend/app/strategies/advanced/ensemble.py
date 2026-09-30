"""多策略集成投票（元策略）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy
from ..registry import register


# ==================================================================
# 多策略集成投票
# ==================================================================
@register
class EnsembleVote(Strategy):
    key = "ensemble_vote"
    name = "多策略集成投票"
    category = "进阶前沿"
    description = (
        "同时运行若干个子策略，取其目标仓位的（可选加权）平均。"
        "集成能显著降低单策略的参数敏感性与策略失效风险，"
        "是当前量化平台的标准生产做法。默认集成趋势、均值回归、状态自适应三条腿。"
    )
    tags = ["集成", "组合", "稳健", "元策略"]
    min_bars = 400

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("members", "子策略(逗号分隔 key)", "choice",
                      "trend_composite,rsi_meanrev,regime_adaptive",
                      choices=[
                          "trend_composite,rsi_meanrev,regime_adaptive",
                          "dual_ma_trend,bollinger_meanrev,supertrend",
                          "tsmom_vol_target,zscore_reversion,vol_managed_momentum",
                          "xs_momentum,keltner_reversion,risk_parity_alloc",
                      ],
                      group="成员"),
            ParamSpec("weights", "子策略权重(逗号分隔)", "choice", "1,1,1",
                      choices=["1,1,1", "2,1,1", "1,1,2", "1,2,1"], group="成员"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 5, 1, 60, 1, group="执行"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        from ..registry import create_strategy

        keys = [k.strip() for k in str(self.params["members"]).split(",") if k.strip()]
        try:
            wts = [float(x) for x in str(self.params["weights"]).split(",")]
        except ValueError:
            wts = [1.0] * len(keys)
        if len(wts) != len(keys):
            wts = [1.0] * len(keys)

        acc = pd.DataFrame(0.0, index=ctx.closes.index, columns=ctx.closes.columns)
        total = 0.0
        for k, wt in zip(keys, wts):
            try:
                sub = create_strategy(k, {})
                sub_w = sub.run(ctx)
                acc = acc.add(sub_w.reindex(index=ctx.closes.index, columns=ctx.closes.columns).fillna(0.0) * wt, fill_value=0.0)
                total += wt
                self.notes.append(f"成员 {k} 权重 {wt}")
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f"成员 {k} 载入失败: {exc}")
        if total > 0:
            acc = acc / total
        mask = np.zeros(len(acc), dtype=bool)
        mask[:: int(self.params["rebalance_days"])] = True
        acc.loc[~mask, :] = np.nan
        return acc.ffill().fillna(0.0).clip(-1, 1)
