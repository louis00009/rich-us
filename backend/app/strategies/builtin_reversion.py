"""
内置策略 —— 均值回归族
=========================
涵盖超买超卖反转、布林/Z 分数回归、Connors RSI2、IBS 日内强度、
以及机构常用的协整配对交易（统计套利）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ParamSpec, SignalContext, Strategy
from .frames import bollinger, donchian, ema, rsi, sma, zscore
from .registry import register


# ==================================================================
# 1. RSI 超卖反转
# ==================================================================
@register
class RsiMeanReversion(Strategy):
    key = "rsi_meanrev"
    name = "RSI 超卖反转"
    category = "均值回归"
    description = (
        "RSI 跌破超卖线进场、回到中轴离场；可选做空对称逻辑。"
        "胜率较高但盈亏比偏低，必须配合止损与趋势过滤，否则熊市会持续接飞刀。"
    )
    tags = ["反转", "RSI", "振荡"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("rsi_n", "RSI 周期", "int", 14, 2, 60, 1, group="信号"),
            ParamSpec("oversold", "超卖阈值", "float", 30.0, 5, 45, 1, group="信号"),
            ParamSpec("overbought", "超买阈值", "float", 70.0, 55, 95, 1, group="信号"),
            ParamSpec("exit_mid", "离场中轴", "float", 50.0, 30, 70, 1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("trend_filter", "200 日均线过滤", "bool", True,
                      group="过滤", help="仅在价格位于长期均线上方时做多，避免熊市接刀"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        r = rsi(c, int(self.params["rsi_n"]))
        size = float(self.params["size"])
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        enter_l = (r < float(self.params["oversold"])).fillna(False).to_numpy()
        exit_l = (r > float(self.params["exit_mid"])).fillna(False).to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(enter_l[i], size, cur)
            cur = np.where(exit_l[i], 0.0, cur)
            state.iloc[i] = cur
        if self.params["allow_short"]:
            enter_s = (r > float(self.params["overbought"])).fillna(False).to_numpy()
            exit_s = (r < float(self.params["exit_mid"])).fillna(False).to_numpy()
            cur = np.zeros(c.shape[1])
            for i in range(len(c)):
                cur = np.where(enter_s[i], -size, cur)
                cur = np.where(exit_s[i], 0.0, cur)
                state.iloc[i] += cur
        if self.params["trend_filter"]:
            ma = sma(c, 200)
            state = state.where(c > ma, state.clip(upper=0.0))
        return state.clip(-size, size)


# ==================================================================
# 2. 布林带均值回归
# ==================================================================
@register
class BollingerMeanReversion(Strategy):
    key = "bollinger_meanrev"
    name = "布林带均值回归"
    category = "均值回归"
    description = (
        "价格触及下轨买入、回归中轨离场。用带宽分位过滤掉『低波动死水』行情，"
        "并可选在极低 %B 时加仓（分批建仓）。"
    )
    tags = ["反转", "布林带", "振荡"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("bb_n", "布林周期", "int", 20, 5, 100, 1, group="信号"),
            ParamSpec("bb_k", "标准差倍数", "float", 2.0, 0.5, 4.0, 0.1, group="信号"),
            ParamSpec("entry_pctb", "入场 %B", "float", 0.05, 0.0, 0.4, 0.01, group="信号"),
            ParamSpec("exit_pctb", "离场 %B", "float", 0.5, 0.2, 0.9, 0.05, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("min_width_pct", "最小带宽分位", "float", 0.0, 0.0, 0.9, 0.05,
                      group="过滤", help="带宽需高于该历史分位才交易，规避无波动区间"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        upper, mid, lower = bollinger(c, int(self.params["bb_n"]), float(self.params["bb_k"]))
        pctb = (c - lower) / (upper - lower + 1e-12)
        width = (upper - lower) / (mid + 1e-12)
        size = float(self.params["size"])

        mw = float(self.params["min_width_pct"])
        width_ok = pd.DataFrame(True, index=c.index, columns=c.columns)
        if mw > 0:
            width_ok = width.rank(axis=1, pct=True) >= mw

        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        ent = ((pctb < float(self.params["entry_pctb"])) & width_ok).fillna(False).to_numpy()
        ext = (pctb > float(self.params["exit_pctb"])).fillna(False).to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(ent[i], size, cur)
            cur = np.where(ext[i], 0.0, cur)
            state.iloc[i] = cur
        if self.params["allow_short"]:
            ent_s = ((pctb > 1 - float(self.params["entry_pctb"])) & width_ok).fillna(False).to_numpy()
            ext_s = (pctb < 1 - float(self.params["exit_pctb"])).fillna(False).to_numpy()
            cur = np.zeros(c.shape[1])
            for i in range(len(c)):
                cur = np.where(ent_s[i], -size, cur)
                cur = np.where(ext_s[i], 0.0, cur)
                state.iloc[i] += cur
        return state.clip(-size, size)


# ==================================================================
# 3. Z-Score 回归
# ==================================================================
@register
class ZScoreReversion(Strategy):
    key = "zscore_reversion"
    name = "Z 分数回归"
    category = "均值回归"
    description = (
        "对价格（或价格/均线偏离）做滚动 Z 分数，|z| 超过阈值反向入场，"
        "回到阈值内离场。纯统计套利思路，适合区间震荡的宽基 ETF。"
    )
    tags = ["反转", "统计", "振荡"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("window", "滚动窗口", "int", 20, 5, 120, 1, group="信号"),
            ParamSpec("entry_z", "入场 Z 阈值", "float", 2.0, 0.5, 5.0, 0.1, group="信号"),
            ParamSpec("exit_z", "离场 Z 阈值", "float", 0.3, 0.0, 2.0, 0.1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", True, group="方向"),
            ParamSpec("use_log_price", "使用对数价格", "bool", True, group="信号"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        px = np.log(c) if self.params["use_log_price"] else c
        z = zscore(px, int(self.params["window"]))
        ez, xz = float(self.params["entry_z"]), float(self.params["exit_z"])
        size = float(self.params["size"])
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        ent_l = (z < -ez).fillna(False).to_numpy()
        ext_l = (z > -xz).fillna(False).to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(ent_l[i], size, cur)
            cur = np.where(ext_l[i], 0.0, cur)
            state.iloc[i] = cur
        if self.params["allow_short"]:
            ent_s = (z > ez).fillna(False).to_numpy()
            ext_s = (z < xz).fillna(False).to_numpy()
            cur = np.zeros(c.shape[1])
            for i in range(len(c)):
                cur = np.where(ent_s[i], -size, cur)
                cur = np.where(ext_s[i], 0.0, cur)
                state.iloc[i] += cur
        return state.clip(-size, size)


# ==================================================================
# 4. Connors RSI2（短周期极端反转）
# ==================================================================
@register
class ConnorsRsi2(Strategy):
    key = "connors_rsi2"
    name = "Connors RSI2 反转"
    category = "均值回归"
    description = (
        "Larry Connors 经典短周期策略：RSI(2) < 阈值 且价格在 200 日均线上方时买入，"
        "RSI(2) 回到高位或触及固定收益离场。持股周期短、资金周转率高。"
    )
    tags = ["反转", "短线", "高胜率"]
    min_bars = 260

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("rsi_n", "RSI 周期", "int", 2, 2, 10, 1, group="信号"),
            ParamSpec("entry_th", "入场阈值", "float", 10.0, 1, 40, 1, group="信号"),
            ParamSpec("exit_th", "离场阈值", "float", 70.0, 40, 99, 1, group="信号"),
            ParamSpec("trend_ma", "趋势均线", "int", 200, 0, 400, 10,
                      group="过滤", help="0 = 关闭均线过滤"),
            ParamSpec("max_hold", "最大持有 bar", "int", 10, 1, 90, 1, group="执行"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        r = rsi(c, int(self.params["rsi_n"]))
        ma_n = int(self.params["trend_ma"])
        ok = (c > sma(c, ma_n)) if ma_n > 0 else pd.DataFrame(True, index=c.index, columns=c.columns)
        size = float(self.params["size"])
        max_hold = int(self.params["max_hold"])

        ent = ((r < float(self.params["entry_th"])) & ok).fillna(False).to_numpy()
        ext = (r > float(self.params["exit_th"])).fillna(False).to_numpy()
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        cur = np.zeros(c.shape[1])
        held = np.zeros(c.shape[1], dtype=int)
        for i in range(len(c)):
            cur = np.where(ent[i], size, cur)
            held = np.where(cur > 0, held + 1, 0)
            hit = ext[i] | (held > max_hold)
            cur = np.where(hit, 0.0, cur)
            held = np.where(hit, 0, held)
            state.iloc[i] = cur
        return state


# ==================================================================
# 5. IBS 内部强度反转
# ==================================================================
@register
class IbsReversion(Strategy):
    key = "ibs_reversion"
    name = "IBS 日内强度反转"
    category = "均值回归"
    description = (
        "IBS = (收盘-最低)/(最高-最低)，衡量收盘在当日区间的位置。"
        "IBS 极低代表尾盘恐慌抛售，次日往往有反弹。持股 1-N 天，属典型短线均值回归。"
    )
    tags = ["反转", "短线", "日内"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("entry_ibs", "入场 IBS", "float", 0.15, 0.0, 0.5, 0.01, group="信号"),
            ParamSpec("exit_ibs", "离场 IBS", "float", 0.6, 0.3, 1.0, 0.05, group="信号"),
            ParamSpec("max_hold", "最大持有 bar", "int", 3, 1, 30, 1, group="执行"),
            ParamSpec("ma_filter", "趋势均线", "int", 0, 0, 400, 10, group="过滤"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        high, low, c = ctx.high, ctx.low, ctx.closes
        ibs = (c - low) / (high - low + 1e-12)
        ma_n = int(self.params["ma_filter"])
        ok = (c > sma(c, ma_n)) if ma_n > 0 else pd.DataFrame(True, index=c.index, columns=c.columns)
        size = float(self.params["size"])
        max_hold = int(self.params["max_hold"])
        ent = ((ibs < float(self.params["entry_ibs"])) & ok).fillna(False).to_numpy()
        ext = (ibs > float(self.params["exit_ibs"])).fillna(False).to_numpy()
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        cur = np.zeros(c.shape[1])
        held = np.zeros(c.shape[1], dtype=int)
        for i in range(len(c)):
            cur = np.where(ent[i], size, cur)
            held = np.where(cur > 0, held + 1, 0)
            hit = ext[i] | (held > max_hold)
            cur = np.where(hit, 0.0, cur)
            held = np.where(hit, 0, held)
            state.iloc[i] = cur
        return state


# ==================================================================
# 6. 协整配对交易
# ==================================================================
@register
class PairsTrading(Strategy):
    key = "pairs_trading"
    name = "协整配对交易"
    category = "均值回归"
    description = (
        "统计套利经典：取前两只标的，滚动 OLS 估计对冲比率，对价差做 Z 分数。"
        "|z| 超阈值时做空高估 / 做多低估（市场中性），回归后平仓。"
        "请务必选择基本面高度相关的两只标的（如 KO/PEP、V/MA、SPY/IVV）。"
    )
    tags = ["套利", "市场中性", "配对", "两只标的"]
    multi_symbol = True
    min_bars = 250

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("window", "滚动窗口", "int", 60, 20, 252, 5, group="信号"),
            ParamSpec("entry_z", "入场 Z 阈值", "float", 2.0, 0.5, 5.0, 0.1, group="信号"),
            ParamSpec("exit_z", "离场 Z 阈值", "float", 0.3, 0.0, 2.0, 0.1, group="信号"),
            ParamSpec("stop_z", "止损 Z 阈值", "float", 4.0, 2.0, 10.0, 0.5, group="风控"),
            ParamSpec("gross", "总敞口", "float", 1.0, 0.1, 2.0, 0.1, group="仓位"),
            ParamSpec("max_hold", "最大持有 bar", "int", 60, 5, 300, 5, group="执行"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        cols = ctx.symbols
        w = pd.DataFrame(0.0, index=ctx.closes.index, columns=cols)
        if len(cols) < 2:
            self.notes.append("配对交易需要至少 2 只标的，已退化为空仓")
            return w

        y_sym, x_sym = cols[0], cols[1]
        y = ctx.closes[y_sym]
        x = ctx.closes[x_sym]
        n = int(self.params["window"])
        cov = y.rolling(n, min_periods=n // 2).cov(x)
        var = x.rolling(n, min_periods=n // 2).var()
        beta = (cov / (var + 1e-12)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        spread = y - beta * x
        mu = spread.rolling(n, min_periods=n // 2).mean()
        sd = spread.rolling(n, min_periods=n // 2).std(ddof=0)
        z = ((spread - mu) / (sd + 1e-12)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        ez, xz, sz = float(self.params["entry_z"]), float(self.params["exit_z"]), float(self.params["stop_z"])
        gross = float(self.params["gross"])
        max_hold = int(self.params["max_hold"])

        zv = z.to_numpy(dtype=float)
        betav = beta.to_numpy(dtype=float)
        state = np.zeros((len(zv), 2))
        pos = 0            # +1: 多 y 空 x ; -1: 空 y 多 x
        held = 0
        for i in range(len(zv)):
            zi = zv[i]
            if pos == 0:
                if zi <= -ez:
                    pos, held = 1, 0
                elif zi >= ez:
                    pos, held = -1, 0
            else:
                held += 1
                flat = (abs(zi) <= xz) or (abs(zi) >= sz) or (held > max_hold)
                if flat:
                    pos, held = 0, 0
            if pos != 0:
                b = abs(betav[i]) if np.isfinite(betav[i]) else 1.0
                denom = 1.0 + b
                state[i, 0] = pos * gross / denom
                state[i, 1] = -pos * gross * b / denom
        w[y_sym] = state[:, 0]
        w[x_sym] = state[:, 1]
        return w


# ==================================================================
# 7. 肯特纳通道回归
# ==================================================================
@register
class KeltnerReversion(Strategy):
    key = "keltner_reversion"
    name = "肯特纳通道回归"
    category = "均值回归"
    description = (
        "用 EMA + ATR 构成通道代替布林带（ATR 口径对跳空更鲁棒）。"
        "价格跌破下轨买入、回到中轨离场。相比布林带，波动率突变时更稳定。"
    )
    tags = ["反转", "ATR", "通道"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("ema_n", "中轨 EMA", "int", 20, 5, 100, 1, group="信号"),
            ParamSpec("atr_n", "ATR 周期", "int", 20, 5, 60, 1, group="信号"),
            ParamSpec("mult", "ATR 倍数", "float", 2.0, 0.5, 5.0, 0.1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        from .frames import atr as atr_df

        high, low, c = ctx.high, ctx.low, ctx.closes
        mid = ema(c, int(self.params["ema_n"]))
        a = atr_df(high, low, c, int(self.params["atr_n"]))
        m = float(self.params["mult"])
        upper, lower = mid + m * a, mid - m * a
        size = float(self.params["size"])
        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        ent = (c < lower).fillna(False).to_numpy()
        ext = (c > mid).fillna(False).to_numpy()
        cur = np.zeros(c.shape[1])
        for i in range(len(c)):
            cur = np.where(ent[i], size, cur)
            cur = np.where(ext[i], 0.0, cur)
            state.iloc[i] = cur
        if self.params["allow_short"]:
            ent_s = (c > upper).fillna(False).to_numpy()
            ext_s = (c < mid).fillna(False).to_numpy()
            cur = np.zeros(c.shape[1])
            for i in range(len(c)):
                cur = np.where(ent_s[i], -size, cur)
                cur = np.where(ext_s[i], 0.0, cur)
                state.iloc[i] += cur
        return state.clip(-size, size)
