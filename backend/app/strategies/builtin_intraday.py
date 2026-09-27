"""
内置策略 —— 日内与微观结构族
===============================
开盘区间突破、VWAP 回归、日内动量延续、跳空回补。
注意：这些策略在 5m/15m/30m/1h 数据上才有意义（回测时请选择相应 interval）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ParamSpec, SignalContext, Strategy
from .frames import atr, sma
from .registry import register

_BAR_MIN = {"1d": 390, "1h": 60, "30m": 30, "15m": 15, "5m": 5, "1wk": 1950}


def _bar_minutes(timeframe: str) -> int:
    return _BAR_MIN.get(timeframe, 5)


def _day_index(close: pd.DataFrame) -> pd.Series:
    idx = close.index
    if isinstance(idx, pd.DatetimeIndex):
        return pd.Series(idx.normalize(), index=idx)
    return pd.Series(pd.to_datetime(idx).normalize(), index=idx)


def _day_arrays(close: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    返回 (day_codes, pos_in_day, day_start_index)。
    用 numpy 直接计算，避免 DataFrameGroupBy.cumcount() 返回 Series 导致的维度塌缩。
    """
    idx = pd.DatetimeIndex(close.index)
    day_codes = pd.factorize(idx.normalize())[0].astype(np.int64)
    n = len(day_codes)
    pos = np.zeros(n, dtype=np.int64)
    day_start = np.zeros(n, dtype=np.int64)
    start = 0
    for i in range(n):
        if i > 0 and day_codes[i] != day_codes[i - 1]:
            start = i
        pos[i] = i - start
        day_start[i] = start
    return day_codes, pos, day_start


def _expanding_extreme(values: np.ndarray, day_codes: np.ndarray, want_max: bool) -> np.ndarray:
    """按交易日分组的累积极值（逐列）。"""
    grp = pd.DataFrame(values).groupby(day_codes)
    return (grp.cummax() if want_max else grp.cummin()).to_numpy()


# ==================================================================
# 1. 开盘区间突破 (ORB)
# ==================================================================
@register
class OpeningRangeBreakout(Strategy):
    key = "orb_breakout"
    name = "开盘区间突破 ORB"
    category = "日内微观"
    description = (
        "取开盘后 N 分钟的最高/最低价构成区间，向上突破做多、向下突破做空，"
        "收盘前平仓（不留隔夜）。ORB 是近年日内系统化交易中夏普最稳定的族类之一，"
        "务必使用 5m/15m 数据回测。"
    )
    tags = ["日内", "突破", "ORB", "不留隔夜"]
    min_bars = 200

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("range_minutes", "开盘区间时长(分钟)", "int", 30, 5, 120, 5, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", True, group="方向"),
            ParamSpec("buffer_bps", "突破缓冲(bp)", "float", 0.0, 0.0, 50.0, 1.0, group="信号"),
            ParamSpec("flat_at_close", "收盘前平仓", "bool", True, group="执行"),
            ParamSpec("min_range_pct", "区间最小幅度 %", "float", 0.0, 0.0, 3.0, 0.05,
                      group="过滤", help="开盘区间过窄时跳过，规避无波动日"),
            ParamSpec("daily_fallback", "日线自动退化", "bool", True, group="执行",
                      help="日线数据时自动改用「前一日区间」突破（真正的 ORB 需要 5m/15m 数据）"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        high, low, c = ctx.high, ctx.low, ctx.closes
        H, L, C = high.to_numpy(dtype=float), low.to_numpy(dtype=float), c.to_numpy(dtype=float)
        n, m = C.shape
        buf = float(self.params["buffer_bps"]) / 10_000.0
        size = float(self.params["size"])
        min_rng = float(self.params["min_range_pct"])

        # ---------- 日线/周线退化：使用「前一日」高低点作为区间 ----------
        if ctx.timeframe in ("1d", "1wk"):
            if not self.params["daily_fallback"]:
                self.notes.append("当前为日线数据，且未启用日线退化，ORB 无法产生信号")
                return pd.DataFrame(0.0, index=c.index, columns=c.columns)
            self.notes.append(
                "当前为日线数据，ORB 已自动退化为「前一日区间突破」；"
                "真正的开盘区间突破请切换到 5m / 15m 周期回测"
            )
            or_h = np.vstack([np.full((1, m), np.nan), H[:-1]])
            or_l = np.vstack([np.full((1, m), np.nan), L[:-1]])
            rng_pct = np.where(np.isfinite(or_l) & (or_l > 0), (or_h - or_l) / (or_l + 1e-12) * 100.0, 0.0)
            valid = np.isfinite(or_h) & np.isfinite(or_l) & (rng_pct >= min_rng)
            lg = valid & (C > or_h * (1 + buf))
            sg = valid & (C < or_l * (1 - buf))
            cur = np.zeros(m)
            state = np.zeros((n, m))
            for i in range(n):
                cur = np.where(lg[i], size, cur)
                if self.params["allow_short"]:
                    cur = np.where(sg[i], -size, cur)
                state[i] = cur
            return pd.DataFrame(state, index=c.index, columns=c.columns)

        # ---------- 日内真 ORB ----------
        bm = _bar_minutes(ctx.timeframe)
        bars = max(1, int(self.params["range_minutes"]) // max(1, bm))
        day_codes, pos, _ = _day_arrays(c)

        # 开盘区间：仅取当日前 bars 根 bar 的极值，累积极值在窗口结束后即为常量
        in_range = (pos < bars)[:, None]
        or_h = _expanding_extreme(np.where(in_range, H, np.nan), day_codes, True)
        or_l = _expanding_extreme(np.where(in_range, L, np.nan), day_codes, False)

        after_range = (pos >= bars)[:, None]
        rng_pct = np.where(np.isfinite(or_l) & (or_l > 0), (or_h - or_l) / (or_l + 1e-12) * 100.0, 0.0)
        rng_ok = rng_pct >= min_rng

        buf = float(self.params["buffer_bps"]) / 10_000.0
        valid = after_range & rng_ok & np.isfinite(or_h) & np.isfinite(or_l)
        lg = valid & (C > or_h * (1 + buf))
        sg = valid & (C < or_l * (1 - buf))

        cur = np.zeros(m)
        state = np.zeros((n, m))
        for i in range(n):
            cur = np.where(lg[i], size, cur)
            if self.params["allow_short"]:
                cur = np.where(sg[i], -size, cur)
            state[i] = cur

        if self.params["flat_at_close"]:
            is_last = np.zeros(n, dtype=bool)
            is_last[:-1] = day_codes[1:] != day_codes[:-1]
            is_last[-1] = True
            state[is_last] = 0.0
        return pd.DataFrame(state, index=c.index, columns=c.columns)


# ==================================================================
# 2. VWAP 回归
# ==================================================================
@register
class VwapReversion(Strategy):
    key = "vwap_reversion"
    name = "VWAP 回归"
    category = "日内微观"
    description = (
        "价格显著偏离成交量加权均价时反向入场，回归 VWAP 平仓。"
        "本质是日内做市逻辑的散户版，适合高流动性 ETF；务必设置硬止损，"
        "因为趋势日会一路偏离。"
    )
    tags = ["日内", "VWAP", "反转"]
    min_bars = 200

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("vwap_n", "VWAP 窗口(bar)", "int", 20, 3, 120, 1, group="信号"),
            ParamSpec("entry_atr", "入场偏离(ATR 倍数)", "float", 1.5, 0.3, 5.0, 0.1, group="信号"),
            ParamSpec("exit_atr", "离场偏离(ATR 倍数)", "float", 0.2, 0.0, 2.0, 0.05, group="信号"),
            ParamSpec("atr_n", "ATR 周期", "int", 14, 5, 60, 1, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", True, group="方向"),
            ParamSpec("max_bars_hold", "最大持有 bar", "int", 20, 1, 200, 1, group="执行"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        from .indicators import rolling_vwap

        high, low, c, vol = ctx.high, ctx.low, ctx.closes, ctx.volume
        vwap = pd.DataFrame(
            {s: rolling_vwap(high[s], low[s], c[s], vol[s], int(self.params["vwap_n"])) for s in c.columns}
        )
        a = atr(high, low, c, int(self.params["atr_n"]))
        dev = (c - vwap) / (a + 1e-12)
        ea, xa = float(self.params["entry_atr"]), float(self.params["exit_atr"])
        size = float(self.params["size"])
        mh = int(self.params["max_bars_hold"])

        ent_l = (dev < -ea).fillna(False).to_numpy()
        ext_l = (dev > -xa).fillna(False).to_numpy()
        ent_s = (dev > ea).fillna(False).to_numpy()
        ext_s = (dev < xa).fillna(False).to_numpy()

        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        cur = np.zeros(c.shape[1])
        held = np.zeros(c.shape[1], dtype=int)
        for i in range(len(c)):
            cur = np.where(ent_l[i], size, cur)
            if self.params["allow_short"]:
                cur = np.where(ent_s[i], -size, cur)
            held = np.where(cur != 0, held + 1, 0)
            hit_long = (cur > 0) & (ext_l[i] | (held > mh))
            hit_short = (cur < 0) & (ext_s[i] | (held > mh))
            cur = np.where(hit_long | hit_short, 0.0, cur)
            held = np.where(hit_long | hit_short, 0, held)
            state.iloc[i] = cur
        return state


# ==================================================================
# 3. 日内动量延续
# ==================================================================
@register
class IntradayMomentum(Strategy):
    key = "intraday_momentum"
    name = "日内动量延续"
    category = "日内微观"
    description = (
        "开盘后前 N 根 bar 的方向若与长期趋势一致，则顺势持仓到收盘。"
        "基于『开盘动量延续』效应（近年日内学术研究热点），胜率中等但盈亏比尚可。"
    )
    tags = ["日内", "动量", "开盘"]
    min_bars = 260

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("signal_bars", "信号 bar 数", "int", 6, 1, 24, 1, group="信号"),
            ParamSpec("trend_ma", "趋势均线(日)", "int", 200, 0, 400, 10, group="过滤"),
            ParamSpec("min_move_pct", "最小开盘涨跌幅 %", "float", 0.3, 0.0, 3.0, 0.05, group="信号"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        sb = int(self.params["signal_bars"])
        th = float(self.params["min_move_pct"])
        size = float(self.params["size"])
        ma_n = int(self.params["trend_ma"])

        # ---------- 日线退化：用「昨日 开盘→收盘」的方向交易今日（隔夜动量效应）----------
        if ctx.timeframe in ("1d", "1wk"):
            self.notes.append(
                "当前为日线数据，日内动量延续已退化为「隔夜动量」："
                "以昨日开盘→收盘方向决定今日持仓。真日内版本请切换到 5m / 15m 周期"
            )
            open_ = pd.DataFrame({s: d["open"] for s, d in ctx.data.items()}).reindex(
                index=c.index, columns=c.columns
            )
            O, C = open_.to_numpy(dtype=float), c.to_numpy(dtype=float)
            prev_move = np.full_like(C, 0.0)
            prev_move[1:] = np.where(O[:-1] > 0, (C[:-1] / O[:-1] - 1) * 100.0, 0.0)
            trend = (c > sma(c, ma_n)).to_numpy() if ma_n > 0 else np.ones_like(C, dtype=bool)
            lg = (prev_move >= th) & trend
            sg = (prev_move <= -th) & (~trend)
            n, m = C.shape
            state = np.zeros((n, m))
            cur = np.zeros(m)
            for i in range(n):
                cur = np.where(lg[i], size, cur)
                if self.params["allow_short"]:
                    cur = np.where(sg[i], -size, cur)
                state[i] = cur
            return pd.DataFrame(state, index=c.index, columns=c.columns)

        day_codes, pos, day_start = _day_arrays(c)
        C = c.to_numpy(dtype=float)
        n, m = C.shape

        day_open = C[day_start]                                  # 每个交易日的第一根 bar 开盘价
        move = np.where(day_open > 0, (C / day_open - 1) * 100.0, 0.0)

        trend = (c > sma(c, ma_n)).to_numpy() if ma_n > 0 else np.ones((n, m), dtype=bool)

        at_signal = pos == sb
        lg = at_signal[:, None] & (move >= th) & trend
        sg = at_signal[:, None] & (move <= -th) & (~trend)

        cur = np.zeros(m)
        state = np.zeros((n, m))
        for i in range(n):
            cur = np.where(lg[i], size, cur)
            if self.params["allow_short"]:
                cur = np.where(sg[i], -size, cur)
            state[i] = cur

        is_last = np.zeros(n, dtype=bool)
        is_last[:-1] = day_codes[1:] != day_codes[:-1]
        is_last[-1] = True
        state[is_last] = 0.0
        return pd.DataFrame(state, index=c.index, columns=c.columns)


# ==================================================================
# 4. 跳空回补
# ==================================================================
@register
class GapFade(Strategy):
    key = "gap_fade"
    name = "跳空回补"
    category = "日内微观"
    description = (
        "显著低开（或高开）后，若前一日波动率不支持该幅度，则反向做多（做空）博取回补，"
        "持有 N 天平仓。是波动率均值回归的直接应用，黑天鹅行情需严格止损。"
    )
    tags = ["日内", "跳空", "反转"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("min_gap_atr", "最小跳空(ATR 倍数)", "float", 1.0, 0.2, 5.0, 0.1, group="信号"),
            ParamSpec("atr_n", "ATR 周期", "int", 14, 5, 60, 1, group="信号"),
            ParamSpec("hold_days", "持有 bar 数", "int", 3, 1, 30, 1, group="执行"),
            ParamSpec("allow_short", "允许做空(高开回补)", "bool", True, group="方向"),
            ParamSpec("trend_filter", "趋势方向过滤", "bool", False,
                      group="过滤", help="仅在趋势向上时低头、向下时高头"),
            ParamSpec("size", "目标仓位", "float", 1.0, 0.05, 1.0, 0.05, group="仓位"),
        ]

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        open_ = pd.DataFrame({s: d["open"] for s, d in ctx.data.items()}).sort_index()
        high, low, c = ctx.high, ctx.low, ctx.closes
        open_ = open_.reindex(index=c.index, columns=c.columns)
        a = atr(high, low, c, int(self.params["atr_n"]))
        prev_close = c.shift(1)
        gap = (open_ - prev_close) / (a + 1e-12)
        th = float(self.params["min_gap_atr"])
        size = float(self.params["size"])
        hold = int(self.params["hold_days"])

        ent_l = (gap <= -th).fillna(False).to_numpy()
        ent_s = (gap >= th).fillna(False).to_numpy()
        if self.params["trend_filter"]:
            up = (c > sma(c, 200)).to_numpy()
            ent_l = ent_l & up
            ent_s = ent_s & (~up)

        state = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        cur = np.zeros(c.shape[1])
        held = np.zeros(c.shape[1], dtype=int)
        for i in range(len(c)):
            cur = np.where(ent_l[i], size, cur)
            if self.params["allow_short"]:
                cur = np.where(ent_s[i], -size, cur)
            held = np.where(cur != 0, held + 1, 0)
            out = held > hold
            cur = np.where(out, 0.0, cur)
            held = np.where(out, 0, held)
            state.iloc[i] = cur
        return state
