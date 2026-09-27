"""
内置策略 —— 趋势与动量族
===========================
覆盖 2026 年主流机构化做法：时序动量 + 波动率目标、横截面动量轮动、
双动量（绝对+相对）、ATR 通道突破、Supertrend、均线带打分、ADX 过滤趋势。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ParamSpec, SignalContext, Strategy, rank_to_weights
from .frames import (
    adx,
    atr,
    donchian,
    ema,
    rank_norm,
    realized_vol,
    sma,
    trend_score,
)
from .registry import register


def _rebalance_hold(w: pd.DataFrame, every_n: int) -> pd.DataFrame:
    """每 N 根 bar 才更新一次仓位，其余时间持有（降低换手）。"""
    every_n = int(every_n)
    if every_n <= 1:
        return w
    out = w.copy()
    mask = np.zeros(len(w), dtype=bool)
    mask[::every_n] = True
    out.loc[~mask, :] = np.nan
    return out.ffill().fillna(0.0)


# ==================================================================
# 1. 双均线趋势跟踪
# ==================================================================
@register
class DualMaTrend(Strategy):
    key = "dual_ma_trend"
    name = "双均线趋势跟踪"
    category = "趋势动量"
    description = (
        "快线在慢线之上做多、之下离场（可开启做空）。经典趋势骨架，"
        "在单边行情中表现最好；可用 ADX 辅助过滤震荡区。"
    )
    tags = ["趋势", "经典", "低频"]
    min_bars = 260

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("fast", "快线周期", "int", 20, 2, 200, 1, group="均线"),
            ParamSpec("slow", "慢线周期", "int", 100, 5, 400, 1, group="均线"),
            ParamSpec("ma_type", "均线类型", "choice", "ema", choices=["ema", "sma"], group="均线"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        f = self.params["fast"]
        s = self.params["slow"]
        if s <= f:
            s = f * 2
            self.notes.append(f"慢线周期已自动修正为 {s}")
        fn = ema if self.params["ma_type"] == "ema" else sma
        fast, slow = fn(c, f), fn(c, s)
        size = float(self.params["size"])
        long_ = fast > slow
        w = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        w[long_] = size
        if self.params["allow_short"]:
            w[fast < slow] = -size
        return w


# ==================================================================
# 2. 时序动量 + 波动率目标（TSMOM）
# ==================================================================
@register
class TsmomVolTarget(Strategy):
    key = "tsmom_vol_target"
    name = "时序动量 · 波动率目标"
    category = "趋势动量"
    description = (
        "学术与 CTA 主流的 TSMOM 变体：按 N 日收益方向定多空，"
        "仓位 = 目标波动率 / 已实现波动率（上限 100%）。自带风险平价属性，"
        "组合波动率长期锚定在 target_vol 附近。"
    )
    tags = ["动量", "波动率目标", "CTA", "低相关"]
    min_bars = 300

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("lookback", "动量回看(bar)", "int", 252, 20, 504, 5, group="信号"),
            ParamSpec("vol_window", "波动率窗口", "int", 60, 10, 252, 5, group="风险"),
            ParamSpec("target_vol", "目标年化波动率", "float", 0.12, 0.02, 0.60, 0.01, group="风险"),
            ParamSpec("max_leverage", "单标的杠杆上限", "float", 1.0, 0.1, 2.0, 0.1, group="风险"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 21, 1, 126, 1, group="执行"),
            ParamSpec("allow_short", "允许做空", "bool", True, group="方向"),
            ParamSpec("vol_scale_cap", "仓位缩放上限", "float", 2.0, 0.5, 3.0, 0.1, group="风险"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        momo = c / c.shift(int(self.params["lookback"])) - 1
        rv = realized_vol(c, int(self.params["vol_window"])).replace(0, np.nan)
        target = float(self.params["target_vol"])
        scale = (target / rv).clip(upper=float(self.params["vol_scale_cap"])).fillna(0.0)
        direction = np.sign(momo).fillna(0.0)
        if not self.params["allow_short"]:
            direction = direction.clip(lower=0)
        w = direction * scale
        w = w.clip(lower=-float(self.params["max_leverage"]), upper=float(self.params["max_leverage"]))
        return _rebalance_hold(w, int(self.params["rebalance_days"]))


# ==================================================================
# 3. 双动量轮动
# ==================================================================
@register
class DualMomentum(Strategy):
    key = "dual_momentum"
    name = "双动量轮动"
    category = "趋势动量"
    description = (
        "Antonacci 双动量：先在候选池中做相对动量排序取 top_n，"
        "再做绝对动量过滤（收益 < 0 则空仓或转持防御资产）。"
        "适合 ETF 轮动，在 2022 式熊市中可显著降低回撤。"
    )
    tags = ["动量", "轮动", "ETF", "防御"]
    multi_symbol = True
    min_bars = 280

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("lookback", "动量回看(bar)", "int", 126, 10, 504, 5, group="信号"),
            ParamSpec("top_n", "持仓数量", "int", 2, 1, 10, 1, group="组合"),
            ParamSpec("abs_filter", "绝对动量过滤", "bool", True, group="信号"),
            ParamSpec("defensive", "防御资产代码", "choice", "", choices=["", "SPY", "TLT", "GLD", "BIL"], group="组合",
                      help="绝对动量为负时切换持有该资产；留空则持有现金"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 21, 1, 126, 1, group="执行"),
            ParamSpec("use_vol_adj", "波动率调整打分", "bool", False, group="信号"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        lb = int(self.params["lookback"])
        score = c / c.shift(lb) - 1
        if self.params["use_vol_adj"]:
            score = score / (realized_vol(c, 60) + 1e-6)
        w = rank_to_weights(score, int(self.params["top_n"]), long_only=True, gross=1.0)
        w = _rebalance_hold(w, int(self.params["rebalance_days"]))
        if self.params["abs_filter"]:
            abs_ok = (c / c.shift(lb) - 1) > 0
            w = w.where(abs_ok, 0.0)
        return w


# ==================================================================
# 4. 横截面动量轮动（风险调整）
# ==================================================================
@register
class CrossSectionalMomentum(Strategy):
    key = "xs_momentum"
    name = "横截面动量轮动"
    category = "趋势动量"
    description = (
        "对候选池逐期做风险调整动量打分（动量 / 波动率），排名归一化后"
        "做多最强、可选做空最弱，权重按分数加权。机构 Smart Beta 常驻策略。"
    )
    tags = ["动量", "横截面", "多空", "SmartBeta"]
    min_bars = 280

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("lookback", "动量回看(bar)", "int", 126, 10, 504, 5, group="信号"),
            ParamSpec("vol_window", "波动率窗口", "int", 60, 10, 252, 5, group="信号"),
            ParamSpec("top_n", "多头数量", "int", 3, 1, 15, 1, group="组合"),
            ParamSpec("bottom_n", "空头数量", "int", 0, 0, 15, 1, group="组合"),
            ParamSpec("gross", "总敞口", "float", 1.0, 0.1, 2.0, 0.1, group="仓位"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 21, 1, 126, 1, group="执行"),
            ParamSpec("min_score", "最低入选分数", "float", -1.0, -1.0, 1.0, 0.05, group="信号"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        score = (c / c.shift(int(self.params["lookback"])) - 1) / (realized_vol(c, int(self.params["vol_window"])) + 1e-6)
        score = score.replace([np.inf, -np.inf], np.nan)
        rk = rank_norm(score)
        rk = rk.where(rk >= float(self.params["min_score"]), np.nan)
        top_n = int(self.params["top_n"])
        bottom_n = int(self.params["bottom_n"])
        gross = float(self.params["gross"])

        rank_df = rk.rank(axis=1, ascending=False)          # 1 = 最强
        valid_cnt = rk.notna().sum(axis=1).to_numpy()
        long_mask = (rank_df <= top_n).fillna(False).to_numpy()
        long_cnt = np.maximum(long_mask.sum(axis=1, keepdims=True), 1)
        weights = np.where(long_mask, gross / long_cnt, 0.0)

        if bottom_n > 0:
            weak_rank = valid_cnt[:, None] - rank_df.to_numpy()   # 0 = 最弱
            short_mask = np.nan_to_num(weak_rank, nan=-1.0) < bottom_n
            short_cnt = np.maximum(short_mask.sum(axis=1, keepdims=True), 1)
            weights = np.where(short_mask, -gross / short_cnt, weights)

        out = pd.DataFrame(weights, index=c.index, columns=c.columns)
        out = out.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return _rebalance_hold(out, int(self.params["rebalance_days"]))


# ==================================================================
# 5. 唐奇安通道突破（海龟型）
# ==================================================================
@register
class DonchianBreakout(Strategy):
    key = "donchian_breakout"
    name = "唐奇安通道突破"
    category = "趋势动量"
    description = (
        "价格突破 N 日最高价开多，跌破 M 日最低价平仓/反手（海龟法则内核）。"
        "突破类策略通常有正偏度，胜率低但盈亏比高，务必配合 ATR 止损。"
    )
    tags = ["突破", "海龟", "趋势"]
    min_bars = 200

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("entry_n", "入场通道周期", "int", 20, 5, 200, 1, group="信号"),
            ParamSpec("exit_n", "离场通道周期", "int", 10, 3, 200, 1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
            ParamSpec("confirm_bars", "突破确认 bar 数", "int", 0, 0, 5, 1, group="信号"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        high, low, c = ctx.high, ctx.low, ctx.closes
        en, xn = int(self.params["entry_n"]), int(self.params["exit_n"])
        cb = int(self.params["confirm_bars"])
        # 全部使用 shift(1)，确保只用「昨日已知」的通道值，杜绝未来函数
        up_entry = donchian(high, low, en)[0].shift(1)
        dn_exit = donchian(high, low, xn)[1].shift(1)
        dn_entry = donchian(high, low, en)[1].shift(1)
        up_exit = donchian(high, low, xn)[0].shift(1)

        long_enter = c > up_entry
        long_exit = c < dn_exit
        if cb > 0:
            long_enter = long_enter.rolling(cb + 1, min_periods=cb + 1).sum() >= (cb + 1)

        size = float(self.params["size"])
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        en_f = long_enter.fillna(False).to_numpy()
        ex_f = long_exit.fillna(False).to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(en_f[i], size, cur)
            cur = np.where(ex_f[i], 0.0, cur)
            state.iloc[i] = cur

        if self.params["allow_short"]:
            short_enter = (c < dn_entry).fillna(False).to_numpy()
            short_exit = (c > up_exit).fillna(False).to_numpy()
            cur = np.zeros(c.shape[1])
            for i in range(len(c)):
                cur = np.where(short_enter[i], -size, cur)
                cur = np.where(short_exit[i], 0.0, cur)
                state.iloc[i] += cur
        return state.clip(-size, size)


# ==================================================================
# 6. Supertrend（ATR 通道趋势）
# ==================================================================
@register
class Supertrend(Strategy):
    key = "supertrend"
    name = "Supertrend 超级趋势"
    category = "趋势动量"
    description = (
        "基于 ATR 的动态跟踪通道：收盘价上穿上轨翻多、下破下轨翻空。"
        "响应比均线快，适合波段；在震荡市易被反复打脸，建议叠加 ADX 或效率比过滤。"
    )
    tags = ["趋势", "ATR", "波段"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("atr_n", "ATR 周期", "int", 10, 3, 60, 1, group="信号"),
            ParamSpec("mult", "ATR 倍数", "float", 3.0, 0.5, 8.0, 0.1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", True, group="方向"),
            ParamSpec("er_filter", "效率比过滤阈值", "float", 0.0, 0.0, 0.9, 0.05, group="过滤"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        from .frames import efficiency_ratio

        high, low, c = ctx.high, ctx.low, ctx.closes
        a = atr(high, low, c, int(self.params["atr_n"])).shift(1)
        hl2 = (high + low) / 2
        mult = float(self.params["mult"])
        upper_basic = (hl2 + mult * a).to_numpy()
        lower_basic = (hl2 - mult * a).to_numpy()
        close = c.to_numpy()
        n, m = close.shape
        final_up = np.full((n, m), np.nan)
        final_dn = np.full((n, m), np.nan)
        trend = np.zeros((n, m))
        for j in range(m):
            fu = np.nan
            fl = np.nan
            for i in range(1, n):
                if np.isnan(upper_basic[i, j]) or np.isnan(lower_basic[i, j]):
                    continue
                fu = upper_basic[i, j] if (np.isnan(fu) or upper_basic[i, j] < fu or close[i - 1, j] > fu) else fu
                fl = lower_basic[i, j] if (np.isnan(fl) or lower_basic[i, j] > fl or close[i - 1, j] < fl) else fl
                final_up[i, j], final_dn[i, j] = fu, fl
                if np.isnan(close[i, j]):
                    trend[i, j] = trend[i - 1, j]
                elif close[i, j] > fu:
                    trend[i, j] = 1.0
                elif close[i, j] < fl:
                    trend[i, j] = -1.0
                else:
                    trend[i, j] = trend[i - 1, j]
        w = pd.DataFrame(trend, index=c.index, columns=c.columns)
        if not self.params["allow_short"]:
            w = w.clip(lower=0.0)
        er_th = float(self.params["er_filter"])
        if er_th > 0:
            er = efficiency_ratio(c, 20)
            w = w.where(er >= er_th, 0.0)
        return w * float(self.params["size"])


# ==================================================================
# 7. 均线多头排列打分
# ==================================================================
@register
class MaRibbon(Strategy):
    key = "ma_ribbon"
    name = "均线带多头排列"
    category = "趋势动量"
    description = (
        "对 10/20/50/100/200 均线排列打分：完全多头排列得满分，逐级衰减。"
        "仓位随分数连续变化（趋势越顺仓位越重），比 0/1 信号更平滑。"
    )
    tags = ["趋势", "均线", "连续仓位"]
    min_bars = 260

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("periods", "均线周期组", "choice", "10,20,50,100,200",
                      choices=["5,10,20,60", "10,20,50,100,200", "20,60,120,250"], group="均线"),
            ParamSpec("min_score", "最低开仓分数", "float", 0.4, 0.0, 1.0, 0.05, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("smooth", "仓位平滑窗口", "int", 1, 1, 20, 1, group="执行"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        periods = [int(x) for x in str(self.params["periods"]).split(",")]
        mas = [sma(c, p) for p in periods]
        score = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        pairs = len(periods) - 1
        for i in range(pairs):
            score += np.sign(mas[i] - mas[i + 1])
        score = score / max(pairs, 1)
        w = score.copy()
        w[w < float(self.params["min_score"])] = 0.0
        if not self.params["allow_short"]:
            w = w.clip(lower=0.0)
        sm = int(self.params["smooth"])
        return w.rolling(sm, min_periods=1).mean() if sm > 1 else w


# ==================================================================
# 8. ADX 过滤趋势跟随
# ==================================================================
@register
class AdxTrendRider(Strategy):
    key = "adx_trend_rider"
    name = "ADX 趋势骑手"
    category = "趋势动量"
    description = (
        "仅当 ADX > 阈值（趋势明确）且 +DI/-DI 给出方向时持仓，"
        "ADX 回落到退出线以下即空仓。用趋势强度过滤掉大部分震荡磨损。"
    )
    tags = ["趋势", "ADX", "过滤"]
    min_bars = 160

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("adx_n", "ADX 周期", "int", 14, 5, 60, 1, group="信号"),
            ParamSpec("entry_th", "入场阈值", "float", 25.0, 5, 60, 1, group="信号"),
            ParamSpec("exit_th", "离场阈值", "float", 18.0, 0, 55, 1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("use_trend_ma", "叠加 200 日均线过滤", "bool", True, group="过滤"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        high, low, c = ctx.high, ctx.low, ctx.closes
        n = int(self.params["adx_n"])
        a = adx(high, low, c, n)
        pc = c.shift(1)
        up = high.diff()
        dn = -low.diff()
        plus = up.where((up > dn) & (up > 0), 0.0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        minus = dn.where((dn > up) & (dn > 0), 0.0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        bull = (plus > minus)
        adx_prev = a.shift(1)
        enter = (adx_prev > float(self.params["entry_th"])) & bull
        exit_ = (a.shift(1) < float(self.params["exit_th"])) | (~bull)
        size = float(self.params["size"])
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        en = enter.fillna(False).to_numpy()
        ex = exit_.fillna(False).to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(en[i], size, cur)
            cur = np.where(ex[i], 0.0, cur)
            state.iloc[i] = cur
        if self.params["allow_short"]:
            bear = minus > plus
            en_s = ((adx_prev > float(self.params["entry_th"])) & bear).fillna(False).to_numpy()
            ex_s = ((a.shift(1) < float(self.params["exit_th"])) | (~bear)).fillna(False).to_numpy()
            cur = np.zeros(c.shape[1])
            for i in range(len(c)):
                cur = np.where(en_s[i], -size, cur)
                cur = np.where(ex_s[i], 0.0, cur)
                state.iloc[i] += cur
        if self.params["use_trend_ma"]:
            state = state.where(c > sma(c, 200), state.clip(upper=0.0))
        return state.clip(-size, size)


# ==================================================================
# 9. 趋势综合分（多因子趋势）
# ==================================================================
@register
class TrendComposite(Strategy):
    key = "trend_composite"
    name = "趋势综合评分"
    category = "趋势动量"
    description = (
        "融合三条独立趋势证据：均线相对位置、慢线斜率、中期动量方向，"
        "取平均得到 -1~1 的连续仓位。信号更稳健、换手更低。"
    )
    tags = ["趋势", "多因子", "稳健"]
    min_bars = 260

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("fast", "快线", "int", 50, 5, 200, 5, group="信号"),
            ParamSpec("slow", "慢线", "int", 200, 20, 400, 5, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("gross", "总敞口", "float", 1.0, 0.1, 2.0, 0.1, group="仓位"),
            ParamSpec("rebalance_days", "调仓间隔(bar)", "int", 5, 1, 60, 1, group="执行"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        w = trend_score(ctx.closes, int(self.params["fast"]), int(self.params["slow"]))
        if not self.params["allow_short"]:
            w = w.clip(lower=0.0)
        w = w * float(self.params["gross"])
        return _rebalance_hold(w, int(self.params["rebalance_days"]))
