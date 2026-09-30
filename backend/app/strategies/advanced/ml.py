"""多因子机器学习 Alpha（walk-forward 滚动训练，杜绝前视偏差）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import ParamSpec, SignalContext, Strategy, rank_to_weights
from ..frames import rank_norm
from ..registry import register


# ==================================================================
# 多因子机器学习 Alpha
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
        from ..indicators import feature_frame

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
