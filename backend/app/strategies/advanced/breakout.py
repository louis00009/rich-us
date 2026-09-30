"""突破族：Dual Thrust 区间突破 + VCP 波动收缩突破。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy
from ..frames import atr, sma, volume_ratio
from ..registry import register


# ==================================================================
# Dual Thrust 区间突破
# ==================================================================
@register
class DualThrust(Strategy):
    key = "dual_thrust"
    name = "Dual Thrust 区间突破"
    category = "进阶前沿"
    description = (
        "以 N 日内的 HH-LC 与 HC-LL 构造对称/非对称突破轨道，"
        "突破上轨做多、下轨做空，对参数不敏感、跨品种稳健，是 CTA 日内经典框架。"
    )
    tags = ["突破", "CTA", "日内", "参数稳健"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("n", "区间窗口", "int", 20, 3, 120, 1, group="信号"),
            ParamSpec("k_up", "上轨系数", "float", 0.5, 0.05, 3.0, 0.05, group="信号"),
            ParamSpec("k_dn", "下轨系数", "float", 0.5, 0.05, 3.0, 0.05, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", True, group="方向"),
            ParamSpec("atr_stop_mult", "ATR 止损倍数", "float", 2.0, 0.5, 6.0, 0.1, group="风控"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        open_ = pd.DataFrame({s: d["open"] for s, d in ctx.data.items()}).sort_index()
        open_ = open_.reindex(index=ctx.closes.index, columns=ctx.closes.columns)
        high, low, c = ctx.high, ctx.low, ctx.closes
        n = int(self.params["n"])
        hh = high.rolling(n, min_periods=2).max().shift(1)
        lc = c.rolling(n, min_periods=2).min().shift(1)
        hc = c.rolling(n, min_periods=2).max().shift(1)
        ll = low.rolling(n, min_periods=2).min().shift(1)
        rng = np.maximum(hh - lc, hc - ll)
        up_line = open_ + float(self.params["k_up"]) * rng
        dn_line = open_ - float(self.params["k_dn"]) * rng

        a = atr(high, low, c, 14)
        stop_mult = float(self.params["atr_stop_mult"])
        size = float(self.params["size"])

        lg = (c > up_line).fillna(False).to_numpy()
        sg = (c < dn_line).fillna(False).to_numpy()
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        cur = np.zeros(c.shape[1])
        entry = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(lg[i], size, cur)
            if self.params["allow_short"]:
                cur = np.where(sg[i], -size, cur)
            entry = np.where((cur != 0) & (entry == 0) & np.roll(entry, 0).astype(bool), c.to_numpy()[i], entry)
            # ATR 跟踪止损
            av = a.to_numpy()[i]
            close_i = c.to_numpy()[i]
            stop_long = close_i < (np.where(np.isnan(av), np.inf, close_i - stop_mult * av))
            stop_short = close_i > (np.where(np.isnan(av), -np.inf, close_i + stop_mult * av))
            hit = ((cur > 0) & stop_long) | ((cur < 0) & stop_short)
            cur = np.where(hit, 0.0, cur)
            state.iloc[i] = cur
        return state


# ==================================================================
# VCP 波动收缩突破
# ==================================================================
@register
class VcpBreakout(Strategy):
    key = "vcp_breakout"
    name = "VCP 波动收缩突破"
    category = "进阶前沿"
    description = (
        "Mark Minervini 的 VCP 形态量化：要求（1）价格接近 52 周高点（强势）"
        "（2）ATR 相对 3 个月前显著收缩（波动收敛）（3）成交量萎缩后放量突破。"
        "突破枢轴买入，跌破收缩区间下沿止损。擅长捕捉主升浪起点。"
    )
    tags = ["形态", "成长股", "突破", "VCP"]
    min_bars = 300

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("high_lookback", "52周高点窗口", "int", 252, 60, 504, 21, group="形态"),
            ParamSpec("near_high_pct", "距高点容忍 %", "float", 8.0, 1.0, 40.0, 1.0, group="形态"),
            ParamSpec("contraction", "ATR 收缩比例", "float", 0.72, 0.3, 0.99, 0.02,
                      group="形态", help="当前 ATR / 3个月前 ATR 需低于该值"),
            ParamSpec("pivot_n", "枢轴窗口", "int", 20, 5, 120, 1, group="信号"),
            ParamSpec("vol_confirm", "放量确认倍数", "float", 1.3, 1.0, 4.0, 0.1, group="信号"),
            ParamSpec("trend_ma", "长期趋势均线", "int", 200, 50, 400, 10, group="过滤"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        high, low, c, vol = ctx.high, ctx.low, ctx.closes, ctx.volume
        hl = int(self.params["high_lookback"])
        hh = high.rolling(hl, min_periods=hl // 3).max()
        near = c >= hh * (1 - float(self.params["near_high_pct"]) / 100.0)

        a = atr(high, low, c, 14)
        a_prev = a.shift(63)
        contraction = (a / (a_prev + 1e-12)) <= float(self.params["contraction"])

        piv = int(self.params["pivot_n"])
        pivot_level = high.rolling(piv, min_periods=2).max().shift(1)
        vr = volume_ratio(vol, 50)
        breakout = (c > pivot_level) & (vr >= float(self.params["vol_confirm"]))
        trend_ok = c > sma(c, int(self.params["trend_ma"]))

        setup = (near & contraction & trend_ok).fillna(False)
        go = (breakout & setup.shift(1).fillna(False)).fillna(False)
        size = float(self.params["size"])
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        go_np = go.to_numpy()
        trail_ok = (c > sma(c, 50)).to_numpy()
        low_stop = low.rolling(10, min_periods=2).min().shift(1).to_numpy()
        close_np = c.to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(go_np[i], size, cur)
            cut = (~trail_ok[i]) | (close_np[i] < low_stop[i])
            cur = np.where(cut, 0.0, cur)
            state.iloc[i] = cur
        return state
