"""多因子打分选股（透明量价因子，逐因子开关 / 方向 / 权重）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy, rank_to_weights
from ..frames import efficiency_ratio, rank_norm, realized_vol, zscore
from ..registry import register


# ==================================================================
# 多因子打分选股
# ==================================================================
@register
class MultiFactorScore(Strategy):
    key = "multi_factor_score"
    name = "多因子打分选股"
    category = "进阶前沿"
    description = (
        "经典横截面多因子模型（透明版）：动量、低波动、52 周高点位置、均值回归 Z、"
        "效率比、流动性六个量价因子各自打分，加权合成后持有综合分最高的 top_n 只。"
        "每个因子可独立开关（权重 0 = 关闭）、反向（invert）与调权，天然支持网格寻优。"
        "全部因子只用 t 日收盘前的 OHLCV，t+1 开盘成交，无未来函数。"
    )
    tags = ["多因子", "横截面", "量价因子", "可解释"]
    multi_symbol = True
    min_bars = 300

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("mom_lookback", "动量回看(bar)", "int", 126, 10, 504, 21, group="动量"),
            ParamSpec("mom_weight", "动量权重", "float", 1.0, 0.0, 3.0, 0.1, group="动量"),
            ParamSpec("mom_invert", "动量反转(做多输家)", "bool", False, group="动量"),
            ParamSpec("lowvol_lookback", "波动率窗口(bar)", "int", 63, 10, 252, 21, group="低波动"),
            ParamSpec("lowvol_weight", "低波动权重", "float", 0.5, 0.0, 3.0, 0.1, group="低波动"),
            ParamSpec("lowvol_invert", "偏好高波动", "bool", False, group="低波动"),
            ParamSpec("w52_lookback", "52周高点窗口(bar)", "int", 252, 60, 504, 21, group="价格结构"),
            ParamSpec("w52_weight", "52周位置权重", "float", 0.5, 0.0, 3.0, 0.1, group="价格结构"),
            ParamSpec("w52_invert", "偏好远离高点", "bool", False, group="价格结构"),
            ParamSpec("mr_lookback", "回归Z窗口(bar)", "int", 20, 5, 120, 5, group="价格结构"),
            ParamSpec("mr_weight", "回归Z权重", "float", 0.0, 0.0, 3.0, 0.1, group="价格结构"),
            ParamSpec("mr_invert", "Z动量方向(追涨)", "bool", False, group="价格结构"),
            ParamSpec("er_lookback", "效率比窗口(bar)", "int", 20, 5, 120, 5, group="价格结构"),
            ParamSpec("er_weight", "效率比权重", "float", 0.0, 0.0, 3.0, 0.1, group="价格结构"),
            ParamSpec("er_invert", "偏好低效率比", "bool", False, group="价格结构"),
            ParamSpec("liq_weight", "流动性权重", "float", 0.0, 0.0, 3.0, 0.1, group="流动性"),
            ParamSpec("liq_invert", "偏好低流动性", "bool", False, group="流动性"),
            ParamSpec("top_n", "持仓数量", "int", 3, 1, 20, 1, group="组合"),
            ParamSpec("gross", "总敞口", "float", 1.0, 0.1, 2.0, 0.1, group="组合"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 21, 1, 126, 1, group="执行"),
        ]

    def _factor_weight(self, key: str) -> float:
        try:
            return float(self.params.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _active_factors(self, ctx: SignalContext) -> list[tuple[str, float, bool, pd.DataFrame]]:
        """返回 (因子名, 权重, 是否反向, 原始因子值) 列表；权重 0 的因子不计算。"""
        c = ctx.closes
        p = self.params
        out: list[tuple[str, float, bool, pd.DataFrame]] = []
        if self._factor_weight("mom_weight") > 0:
            mom = c / c.shift(int(p["mom_lookback"])) - 1
            out.append(("动量", self._factor_weight("mom_weight"), bool(p["mom_invert"]), mom))
        if self._factor_weight("lowvol_weight") > 0:
            vol = realized_vol(c, int(p["lowvol_lookback"]))
            out.append(("低波动", self._factor_weight("lowvol_weight"), bool(p["lowvol_invert"]), vol))
        if self._factor_weight("w52_weight") > 0:
            pos = c / c.rolling(int(p["w52_lookback"])).max()
            out.append(("52周位置", self._factor_weight("w52_weight"), bool(p["w52_invert"]), pos))
        if self._factor_weight("mr_weight") > 0:
            z = zscore(c, int(p["mr_lookback"]))
            # 默认均值回归方向：Z 越低（超跌）打分越高；invert = 追涨动量
            out.append(("回归Z", self._factor_weight("mr_weight"), not bool(p["mr_invert"]), z))
        if self._factor_weight("er_weight") > 0:
            er = efficiency_ratio(c, int(p["er_lookback"]))
            out.append(("效率比", self._factor_weight("er_weight"), bool(p["er_invert"]), er))
        if self._factor_weight("liq_weight") > 0:
            amt = (ctx.volume * c).rolling(20, min_periods=10).mean()
            out.append(("流动性", self._factor_weight("liq_weight"), bool(p["liq_invert"]), amt))
        return out

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        factors = self._active_factors(ctx)
        if not factors:
            self.notes.append("所有因子权重均为 0，策略空仓")
            return pd.DataFrame(0.0, index=c.index, columns=c.columns)

        self.notes.append("启用因子: " + ", ".join(n for n, w, _, _ in factors if w > 0))
        total_w = sum(w for _, w, _, _ in factors)
        score = pd.DataFrame(0.0, index=c.index, columns=c.columns)

        # 预热期：最长因子窗口未走满之前置 NaN → rank_to_weights 对 NaN 行输出 0 权重，
        # 避免窗口未满时因子全 0 也会「随机」排进 top_n 持仓。
        p = self.params
        warmups = []
        if self._factor_weight("mom_weight") > 0:
            warmups.append(int(p["mom_lookback"]))
        if self._factor_weight("lowvol_weight") > 0:
            warmups.append(int(p["lowvol_lookback"]))
        if self._factor_weight("w52_weight") > 0:
            warmups.append(int(p["w52_lookback"]))
        if self._factor_weight("mr_weight") > 0:
            warmups.append(int(p["mr_lookback"]))
        if self._factor_weight("er_weight") > 0:
            warmups.append(int(p["er_lookback"]))
        if self._factor_weight("liq_weight") > 0:
            warmups.append(20)
        warmup = max(warmups) if warmups else 0

        if len(c.columns) > 1:
            # 横截面：逐日排名归一化到 [-1, 1] 后按权重加总，rank_to_weights 取 top_n
            for _name, w, inv, f in factors:
                s = rank_norm(f) * (-1.0 if inv else 1.0)
                score = score.add(s.fillna(0.0) * (w / total_w), fill_value=0.0)
            if warmup > 0:
                score.iloc[:warmup] = np.nan
            w_df = rank_to_weights(
                score, int(self.params["top_n"]), long_only=True, gross=float(self.params["gross"])
            )
        else:
            # 单标的：时间序列 z 分数加权合成，仓位 = clip(综合分, -1, 1) * gross
            for _name, w, inv, f in factors:
                mu = f.rolling(252, min_periods=60).mean()
                sd = f.rolling(252, min_periods=60).std(ddof=0) + 1e-9
                s = ((f - mu) / sd).clip(-2, 2) / 2.0 * (-1.0 if inv else 1.0)
                score = score.add(s.fillna(0.0) * (w / total_w), fill_value=0.0)
            w_df = score.clip(-1.0, 1.0).mul(float(self.params["gross"])).to_frame(c.columns[0])

        w_df = w_df.reindex(index=c.index, columns=c.columns)
        rd = int(self.params["rebalance_days"])
        mask = np.zeros(len(w_df), dtype=bool)
        mask[::rd] = True
        w_df.loc[~mask, :] = np.nan
        return w_df.ffill().fillna(0.0)
