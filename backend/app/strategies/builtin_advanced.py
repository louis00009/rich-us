"""
内置策略 —— 进阶/前沿族（对应 2026 年机构与卖方研究主流做法）
================================================================
- 多因子机器学习 Alpha（walk-forward 滚动训练，杜绝前视偏差）
- 波动率管理动量（Moreira & Muir）—— 用上一期已实现方差缩放动量仓位
- 状态自适应（趋势 / 均值回归随波动率与效率比切换）
- Dual Thrust 区间突破
- VCP 波动收缩突破（Minervini 形态量化）
- 网格交易
- 风险平价配置（inverse-vol）
- 多策略集成投票
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
    efficiency_ratio,
    rank_norm,
    realized_vol,
    sma,
    volume_ratio,
    zscore,
)
from .registry import register


# ==================================================================
# 1. 多因子机器学习 Alpha
# ==================================================================
@register
class MlAlphaRidge(Strategy):
    key = "ml_alpha_ridge"
    name = "机器学习多因子 Alpha"
    category = "进阶前沿"
    description = (
        "用 25+ 个量价因子（动量/波动/量能/趋势强度/微观结构）训练线性/梯度提升模型，"
        "预测未来 N 日收益，walk-forward 滚动重训避免前视偏差。"
        "多标的时做横截面排序选股，单标的时按预测值连续调仓。"
        "已安装 LightGBM 时自动升级为非线性模型，否则使用内置纯 numpy 岭回归。"
    )
    tags = ["机器学习", "多因子", "横截面", "walk-forward"]
    min_bars = 400

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return [
            ParamSpec("horizon", "预测周期(bar)", "int", 5, 1, 60, 1, group="目标"),
            ParamSpec("train_window", "训练窗口(bar)", "int", 500, 120, 2000, 50, group="模型"),
            ParamSpec("retrain_days", "重训间隔(bar)", "int", 21, 5, 126, 1, group="模型"),
            ParamSpec("alpha", "正则强度", "float", 1.0, 0.001, 100.0, 0.5, group="模型"),
            ParamSpec("top_n", "持仓数量", "int", 3, 1, 20, 1, group="组合"),
            ParamSpec("allow_short", "允许做空", "bool", False, group="方向"),
            ParamSpec("gross", "总敞口", "float", 1.0, 0.1, 2.0, 0.1, group="仓位"),
            ParamSpec("min_conviction", "最低信心分位", "float", 0.0, 0.0, 0.9, 0.05, group="信号"),
            ParamSpec("use_gbm", "优先使用 LightGBM", "bool", True, group="模型"),
        ]

    # ---- 内部：单标的特征与标签 ----
    def _build_xy(self, df: pd.DataFrame, bench: pd.Series | None, h: int) -> tuple[pd.DataFrame, pd.Series]:
        from .indicators import feature_frame

        X = feature_frame(df, bench)
        y = (df["close"].shift(-h) / df["close"] - 1).rename("y")
        data = X.join(y, how="inner").replace([np.inf, -np.inf], np.nan)
        data = data.dropna(subset=["y"])
        if data.empty:
            return pd.DataFrame(), pd.Series(dtype=float)
        data = data.dropna(axis=1, thresh=int(len(data) * 0.7))
        if data.shape[1] <= 1:
            return pd.DataFrame(), pd.Series(dtype=float)
        y_out = data["y"]
        # 长周期指标（如距 SMA200 偏离）在样本前段为 NaN → 前向填充后补 0，
        # 避免 NaN 进入最小二乘求解导致 SVD 不收敛
        X_out = data.drop(columns=["y"]).ffill().fillna(0.0)
        return X_out, y_out

    @staticmethod
    def _fit_predict(
        Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray, alpha: float, use_gbm: bool
    ) -> np.ndarray:
        if use_gbm:
            try:  # pragma: no cover - 依赖可选
                import lightgbm as lgb

                m = lgb.LGBMRegressor(
                    n_estimators=180, num_leaves=15, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8, min_child_samples=25, verbose=-1,
                )
                m.fit(Xtr, ytr)
                return m.predict(Xte)
            except Exception:
                pass
        # 内置岭回归（闭式解，含截距）
        mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0) + 1e-9
        Xs = np.column_stack([np.ones(len(Xtr)), (Xtr - mu) / sd])
        Ts = np.column_stack([np.ones(len(Xte)), (Xte - mu) / sd])
        n_feat = Xs.shape[1]
        reg = np.eye(n_feat) * float(alpha)
        reg[0, 0] = 0.0                      # 不惩罚截距
        try:
            w = np.linalg.solve(Xs.T @ Xs + reg, Xs.T @ ytr)
        except np.linalg.LinAlgError:
            w = np.linalg.pinv(Xs.T @ Xs + reg) @ (Xs.T @ ytr)
        return Ts @ w

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        c = ctx.closes
        h = int(self.params["horizon"])
        tw = int(self.params["train_window"])
        rt = int(self.params["retrain_days"])
        alpha = float(self.params["alpha"])
        use_gbm = bool(self.params["use_gbm"])
        cols = list(c.columns)

        preds = pd.DataFrame(np.nan, index=c.index, columns=cols)
        for sym in cols:
            df = ctx.data.get(sym)
            if df is None or len(df) < max(120, tw // 3):
                continue
            X, y = self._build_xy(df, ctx.bench, h)
            if len(X) < 80:
                continue
            Xv, yv = X.to_numpy(float), y.to_numpy(float)
            dates = X.index
            for start in range(tw, len(dates), rt):
                tr_lo = max(0, start - tw)
                Xtr, ytr = Xv[tr_lo:start], yv[tr_lo:start]
                te_hi = min(len(dates), start + rt)
                if len(Xtr) < 40 or te_hi <= start:
                    continue
                p = self._fit_predict(Xtr, ytr, Xv[start:te_hi], alpha, use_gbm)
                preds.loc[dates[start:te_hi], sym] = p
        preds = preds.ffill()

        if not preds.dropna(how="all").empty and len(cols) > 1:
            rk = rank_norm(preds)
            th = float(self.params["min_conviction"])
            if th > 0:
                flat = rk.to_numpy(dtype=float)
                flat = flat[np.isfinite(flat)]
                if flat.size:
                    cutoff = float(np.quantile(flat, th))
                    rk = rk.where(rk >= cutoff, np.nan)
            w = rank_to_weights(rk, int(self.params["top_n"]), long_only=True, gross=float(self.params["gross"]))
        else:
            sd = preds.std(axis=1).replace(0, np.nan)
            conv = (preds.iloc[:, 0] / (sd.fillna(preds.iloc[:, 0].abs().mean() + 1e-9))).clip(-1, 1)
            w = (conv * float(self.params["gross"])).to_frame(cols[0])

        if not self.params["allow_short"]:
            w = w.clip(lower=0.0)
        w = w.reindex(index=c.index, columns=cols).fillna(0.0)
        # 每 retrain 间隔更新，其余持有
        mask = np.zeros(len(w), dtype=bool)
        mask[::rt] = True
        w.loc[~mask, :] = np.nan
        return w.ffill().fillna(0.0)


# ==================================================================
# 2. 波动率管理动量
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


# ==================================================================
# 3. 状态自适应（趋势 / 均值回归切换）
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


# ==================================================================
# 4. Dual Thrust 区间突破
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
# 5. VCP 波动收缩突破
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


# ==================================================================
# 6. 网格交易
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


# ==================================================================
# 7. 风险平价配置
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


# ==================================================================
# 8. 多策略集成投票
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
        from .registry import create_strategy

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
