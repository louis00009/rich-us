"""
组合优化器
============
在「均值-方差」框架下求最优权重，并对真实数据的病态性做了工程处理。

为什么不能直接做教科书上的 w = Σ⁻¹μ：
  · 样本协方差矩阵在 N 接近 T 时接近奇异，求逆会把噪声放大成极端权重；
  · 样本均值收益的估计误差极大，最大夏普组合对 μ 的误差极其敏感。
因此这里做了三件事：
  1. 协方差默认做 **Ledoit-Wolf 收缩**（向对角阵收缩，强度由数据估计）；
  2. 期望收益可选 **Bayes-Stein 收缩**（向最小方差组合的收益收缩）；
  3. 权重有 **盒约束 + 相关性簇上限**，避免把 60% 押在一堆高度相关的标的上。

求解器不加外部依赖（本机无 scipy/cvxpy），用「投影梯度上升」：
  · 可行集 {Σw=1, lo≤w≤hi} ∩ {Σ_{i∈C} w_i ≤ cap} 是凸集；
  · 用 Dykstra 交替投影求该集合上的欧氏投影（收敛到真正的投影）；
  · 目标函数 w'μ − (λ/2)·w'Σw 梯度上升，步长取 1/L（L 为 Lipschitz 常数），保证收敛。

FILE_SIZE_DEBT Batch E-1：数学核（估计/投影/簇）拆至 `optimizer_math.py`，
本文件保留求解器与对外主函数；旧 import 路径经 re-export 保持不变。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

# 数学核（re-export：run_checks 等旧路径 `from ...optimizer import project` 仍然可用）
from .optimizer_math import (  # noqa: F401
    OptimizeError,
    bayes_stein_mean,
    correlation_clusters,
    estimate_cov,
    estimate_mean,
    ewma_cov,
    is_feasible,
    ledoit_wolf_diag,
    project,
    to_returns,
    _ewma_mean,
    _proj_halfspace,
    _proj_simplex_box,
)

# P2-9：原先这里有 PERIODS_PER_YEAR 与 annualize()，**全项目零引用**，
# 且与 metrics._BAR_MAP_PPY 口径冲突（1h: 252*7 vs 252*6.5）—— 属潜在陷阱，已删除。
# 年化因子一律以 engine/metrics.periods_per_year() 为唯一来源。

OBJECTIVES = [
    "max_sharpe", "min_variance", "max_return",
    "risk_parity", "inverse_vol", "equal_weight",
]
COV_METHODS = ["ledoit_wolf", "sample", "ewma"]
RETURN_METHODS = ["shrunk", "mean", "ewma"]


# ======================================================================
# 求解器
# ======================================================================
@dataclass
class SolveInput:
    symbols: list[str]
    mu: np.ndarray                      # 年化期望收益
    cov: np.ndarray                     # 年化协方差
    lo: np.ndarray
    hi: np.ndarray
    total: float = 1.0
    rf: float = 0.0
    risk_budget: np.ndarray | None = None
    halfspaces: list[tuple[np.ndarray, float]] = field(default_factory=list)


def _ascend_bb(
    grad: Callable[[np.ndarray], np.ndarray],
    x0: np.ndarray,
    project_fn: Callable[[np.ndarray], np.ndarray],
    score: Callable[[np.ndarray], float],
    iters: int = 400,
    tol: float = 1e-9,
) -> np.ndarray:
    """投影梯度上升 + Barzilai-Borwein 步长。

    对二次型问题 BB 步长的收敛速度远优于固定 1/L 步长（实测从 1500 步降到 <150 步），
    配合一个简单的非单调保护，避免步长过大导致震荡。
    """
    x = project_fn(x0.copy())
    g = grad(x)
    step = 1.0 / max(float(np.linalg.norm(g)), 1e-12)
    best_x, best_s = x, score(x)
    for _ in range(iters):
        x_new = project_fn(x + step * g)
        s_new = score(x_new)
        if s_new > best_s:
            best_x, best_s = x_new, s_new
        elif s_new < best_s - 1e-6 * (1.0 + abs(best_s)):
            # 步子迈大了：回退半步重试一次
            step *= 0.5
            x_new = project_fn(x + step * g)
        g_new = grad(x_new)
        s_vec = x_new - x
        y_vec = g_new - g
        sy = float(s_vec @ y_vec)
        # P1-4：这里是**梯度上升**（凹目标极大化），海塞负定 → 上升方向的曲率
        # sᵀy < 0。旧实现条件写 `sy > 1e-18` 恒不成立，BB 步长从未真正生效
        # （实测 max_sharpe 与参照解差 10.4%，全靠步长回退兜底）。
        if sy < -1e-18:
            step = float(np.clip((s_vec @ s_vec) / (-sy), 1e-8, 1e6))
        if np.max(np.abs(s_vec)) < tol:
            return x_new
        x, g = x_new, g_new
    return best_x


def _grad_proj(
    si: SolveInput, grad: Callable[[np.ndarray], np.ndarray],
    score: Callable[[np.ndarray], float], iters: int,
) -> np.ndarray:
    n = si.mu.size
    proj = lambda w: project(w, si.total, si.lo, si.hi, si.halfspaces)  # noqa: E731
    x0 = project(np.full(n, si.total / n), si.total, si.lo, si.hi, si.halfspaces)
    return _ascend_bb(grad, x0, proj, score, iters=iters)


def _mv_score(si: SolveInput, lam: float) -> Callable[[np.ndarray], float]:
    return lambda w: float(w @ si.mu - 0.5 * lam * (w @ si.cov @ w))  # noqa: E731


def _mean_variance(si: SolveInput, lam: float, iters: int = 400) -> np.ndarray:
    """max w'μ − (λ/2)w'Σw s.t. 约束。"""
    grad = lambda w: si.mu - lam * (si.cov @ w)          # noqa: E731
    return _grad_proj(si, grad, _mv_score(si, lam), iters)


def _min_variance(si: SolveInput, iters: int = 400) -> np.ndarray:
    grad = lambda w: -(si.cov @ w)                        # noqa: E731
    score = lambda w: -float(w @ si.cov @ w)              # noqa: E731
    return _grad_proj(si, grad, score, iters)


def _risk_parity(si: SolveInput) -> np.ndarray:
    """风险平价 / 风险预算：使各标的风险贡献占比等于预算。

    用标准乘性迭代：w ← w·sqrt(b / rc_norm)，再归一化。
    触顶（hi）的标的会被固定在上限，其余重新按预算分配。
    """
    n = si.mu.size
    b = si.risk_budget if si.risk_budget is not None else np.ones(n) / n
    b = np.asarray(b, dtype=float)
    if b.sum() <= 0:
        b = np.ones(n) / n
    b = b / b.sum()

    free = np.ones(n, dtype=bool)
    w = np.full(n, si.total / n)

    for _ in range(60):                                    # 外层：处理上限
        wf = w.copy()
        bf = b.copy()
        for _ in range(1500):                              # 内层：乘性迭代
            if bf.sum() <= 0:
                break
            port_var = float(wf @ si.cov @ wf)
            if port_var <= 1e-18:
                break
            rc = wf * (si.cov @ wf) / port_var             # 归一化风险贡献
            w_new = wf * np.sqrt(np.maximum(bf, 1e-14) / np.maximum(rc, 1e-14))
            w_new = np.maximum(w_new, 1e-12)
            w_new = w_new / w_new.sum() * si.total
            if np.max(np.abs(w_new - wf)) < 1e-12:
                wf = w_new
                break
            wf = w_new

        w = np.where(free, wf, w)
        # 把超过上限的固定住，剩余权重交给其余标的
        over = free & (w > si.hi + 1e-12)
        if not over.any():
            break
        w[over] = si.hi[over]
        free = free & ~over
        if not free.any():
            break
        rest = si.total - float(w[~free].sum())
        if rest <= 0:
            break
        sub = w[free].sum()
        w[free] = w[free] / sub * rest if sub > 0 else rest / free.sum()
        b = np.where(free, b, 0.0)
        if b.sum() <= 0:
            b = free.astype(float)
        b = b / b.sum()

    return project(w, si.total, si.lo, si.hi, si.halfspaces)


def _inverse_vol(si: SolveInput) -> np.ndarray:
    vol = np.sqrt(np.maximum(np.diag(si.cov), 1e-18))
    w = 1.0 / vol
    w = w / w.sum()
    return project(w, si.total, si.lo, si.hi, si.halfspaces)


def _equal_weight(si: SolveInput) -> np.ndarray:
    n = si.mu.size
    return project(np.full(n, 1.0 / n), si.total, si.lo, si.hi, si.halfspaces)


def solve(si: SolveInput, objective: str, *, frontier: list[dict[str, float]] | None = None) -> np.ndarray:
    if objective == "min_variance":
        return _min_variance(si)
    if objective == "max_return":
        return _mean_variance(si, lam=1e-7)
    if objective == "risk_parity":
        return _risk_parity(si)
    if objective == "inverse_vol":
        return _inverse_vol(si)
    if objective == "equal_weight":
        return _equal_weight(si)
    if objective == "max_sharpe":
        return _max_sharpe(si, frontier=frontier)
    raise OptimizeError(f"未知优化目标：{objective}")


def frontier_points(si: SolveInput, n_points: int = 28, iters: int = 140) -> list[dict[str, float]]:
    """扫描风险厌恶系数 λ，得到有效前沿。

    前沿点只用于展示，迭代数低于最终解，避免整页计算过慢。
    """
    vols = np.sqrt(np.maximum(np.diag(si.cov), 1e-18))
    # λ 的量纲与 Σ 耦合，按「平均波动」归一化，使扫描区间与标的无关
    mean_vol = float(np.maximum(vols.mean(), 1e-6))
    lams = np.logspace(np.log10(1e-3 / mean_vol), np.log10(1e4 / mean_vol), n_points)
    out: list[dict[str, float]] = []
    prev: np.ndarray | None = None
    for lam in lams:
        w = _mean_variance(si, lam=float(lam), iters=iters)
        if prev is not None and np.max(np.abs(w - prev)) < 1e-12:
            continue
        prev = w
        ret = float(w @ si.mu)
        vol = float(np.sqrt(max(w @ si.cov @ w, 0.0)))
        out.append({
            "lambda": float(lam), "ret": ret, "vol": vol,
            "sharpe": (ret - si.rf) / vol if vol > 1e-12 else 0.0,
        })
    return out


def _max_sharpe(si: SolveInput, frontier: list[dict[str, float]] | None = None) -> np.ndarray:
    """切点组合：在有效前沿上找 (μ−rf)/σ 最大者。

    先在前沿粗扫结果里挑最优 λ，再对 λ 做黄金分割细化。
    """
    pts = frontier if frontier else frontier_points(si, n_points=40, iters=200)
    if not pts:
        return _min_variance(si)
    best = max(pts, key=lambda p: p["sharpe"])
    lam_best = max(float(best["lambda"]), 1e-12)

    lo, hi = lam_best / 4.0, lam_best * 4.0
    gr = (np.sqrt(5.0) - 1.0) / 2.0
    c, d = hi - gr * (hi - lo), lo + gr * (hi - lo)

    def score(lam: float) -> float:
        w = _mean_variance(si, lam=float(lam), iters=220)
        vol = float(np.sqrt(max(w @ si.cov @ w, 0.0)))
        ret = float(w @ si.mu)
        return (ret - si.rf) / vol if vol > 1e-12 else -1e9

    sc, sd = score(c), score(d)
    for _ in range(12):
        if sc > sd:
            hi, d, sd = d, c, sc
            c = hi - gr * (hi - lo)
            sc = score(c)
        else:
            lo, c, sc = c, d, sd
            d = lo + gr * (hi - lo)
            sd = score(d)
    lam_star = c if sc > sd else d
    if not np.isfinite(lam_star) or lam_star <= 0:
        lam_star = lam_best
    return _mean_variance(si, lam=float(lam_star))


# ======================================================================
# 组合统计
# ======================================================================
def portfolio_stats(w: np.ndarray, si: SolveInput) -> dict[str, float]:
    ret = float(w @ si.mu)
    var = float(w @ si.cov @ w)
    vol = float(np.sqrt(max(var, 0.0)))
    vols = np.sqrt(np.maximum(np.diag(si.cov), 1e-18))
    # 分散化比率 = Σ w_i σ_i / σ_p，衡量相对加权平均波动降低了多少
    wt_vol = float(np.abs(w) @ vols)
    div = wt_vol / vol if vol > 1e-12 else 1.0
    # 有效标的数 = 1 / HHI
    hhi = float(np.sum(w ** 2))
    eff_n = 1.0 / hhi if hhi > 1e-12 else 0.0
    # 组合风险贡献（含符号处理，便于展示）
    rc = w * (si.cov @ w)
    rc_total = float(rc.sum())
    return {
        "ann_return": ret,
        "ann_vol": vol,
        "sharpe": (ret - si.rf) / vol if vol > 1e-12 else 0.0,
        "diversification_ratio": div,
        "effective_n": eff_n,
        "risk_concentration": float(np.max(np.abs(rc)) / abs(rc_total)) if abs(rc_total) > 1e-12 else 1.0,
        "gross": float(np.abs(w).sum()),
    }


def asset_stats(symbols: list[str], mu: np.ndarray, cov: np.ndarray,
                weights: np.ndarray, rets: pd.DataFrame,
                rf: float = 0.0) -> list[dict[str, Any]]:
    vols = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    rc_total = float(weights @ cov @ weights)
    out: list[dict[str, Any]] = []
    for i, s in enumerate(symbols):
        series = rets.iloc[:, i].dropna() if i < rets.shape[1] else pd.Series(dtype=float)
        curve = (1.0 + series).cumprod()
        dd = float((curve / curve.cummax() - 1.0).min()) if len(curve) else 0.0
        rc = float(weights[i] * (cov[i] @ weights))
        out.append({
            "symbol": s,
            "weight": float(weights[i]),
            "ann_return": float(mu[i]),
            "ann_vol": float(vols[i]),
            "sharpe": float((mu[i] - rf) / vols[i]) if vols[i] > 1e-12 else 0.0,
            "max_drawdown": dd,
            "risk_contrib_pct": (rc / rc_total * 100.0) if abs(rc_total) > 1e-12 else 0.0,
            "obs": int(len(series)),
        })
    return out


# ======================================================================
# 对外主函数
# ======================================================================
def optimize_portfolio(
    prices: pd.DataFrame,
    *,
    objective: str = "max_sharpe",
    cov_method: str = "ledoit_wolf",
    return_method: str = "shrunk",
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
    max_weight: float = 0.35,
    min_weight: float = 0.0,
    max_gross: float = 1.0,
    long_only: bool = True,
    corr_threshold: float = 0.85,
    max_cluster_weight: float = 0.5,
    risk_budget: dict[str, float] | None = None,
    include_frontier: bool = True,
) -> dict[str, Any]:
    """对给定收盘价矩阵求解最优权重。

    prices: index=日期, columns=标的, values=收盘价
    """
    symbols = [str(c).upper() for c in prices.columns]
    # 补齐节假日/停牌缺口（最多 5 根），避免个别缺口导致整列被剔除
    prices = prices.astype(float).ffill(limit=5)
    rets = to_returns(prices)
    # 每只标的至少要有若干观测，否则剔除（其余标的仍可参与）
    min_obs = max(30, int(0.5 * len(rets)))
    keep = [c for c in rets.columns if rets[c].notna().sum() >= min_obs]
    dropped = [str(c).upper() for c in rets.columns if c not in keep]
    if len(keep) < 2:
        raise OptimizeError(
            f"有效标的不足（可用 {len(keep)} 个，至少需要 2 个）。"
            f"已剔除：{', '.join(dropped) if dropped else '无'}"
        )
    rets = rets[keep].dropna(how="any")
    if len(rets) < 40:
        raise OptimizeError(f"重叠交易日不足（{len(rets)} 天），无法稳定估计协方差")

    symbols = [str(c).upper() for c in keep]
    X_raw = rets.to_numpy(dtype=float)
    # 协方差用去均值后的数据；期望收益必须用原始收益，否则均值恒为 0
    X = X_raw - X_raw.mean(axis=0, keepdims=True)

    cov = estimate_cov(X, cov_method) * periods_per_year
    cov = (cov + cov.T) / 2.0                              # 数值对称化
    mu = estimate_mean(X_raw, cov / periods_per_year, return_method) * periods_per_year

    n = len(symbols)
    # 盒约束：单边上限不超过 100%，下限不能把总量卡死
    hi = np.full(n, float(np.clip(max_weight, 1e-4, 1.0)))
    cap_relaxed = False
    if hi.sum() < max_gross:
        # 上限 × 标的数 < 总仓位 ⇒ 无解。这里放宽到等权，但**必须显式告知**，
        # 否则用户以为「单标的上限 15%」被遵守了，实际拿到的是 16.7%。
        hi = np.full(n, float(max_gross) / n)
        cap_relaxed = True
    effective_max_weight = float(hi.max())
    lo = np.zeros(n) if long_only else np.full(n, -float(np.clip(max_weight, 1e-4, 1.0)))
    if long_only:
        lo = np.full(n, float(np.clip(min_weight, 0.0, hi.min() - 1e-9)))
        if lo.sum() > max_gross:
            lo = np.zeros(n)

    # 相关性簇上限
    vols = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    corr = cov / np.outer(vols, vols)
    corr = np.clip(np.nan_to_num(corr, nan=0.0), -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    clusters = correlation_clusters(corr, float(corr_threshold))
    halfspaces = [(np.asarray(c, dtype=int), float(max_cluster_weight) * float(max_gross))
                  for c in clusters]

    budget_vec = None
    if risk_budget:
        b = np.array([float(risk_budget.get(s, 0.0)) for s in symbols], dtype=float)
        if b.sum() > 0:
            budget_vec = b

    si = SolveInput(
        symbols=symbols, mu=mu, cov=cov, lo=lo, hi=hi, total=float(max_gross),
        rf=float(risk_free_rate), risk_budget=budget_vec, halfspaces=halfspaces,
    )

    # 有效前沿只算一次：既给 max_sharpe 定位切点，也直接作为返回值展示
    frontier: list[dict[str, float]] = []
    if include_frontier and n >= 2:
        try:
            frontier = frontier_points(si, n_points=28, iters=140)
        except Exception:  # noqa: BLE001
            frontier = []

    weights = solve(si, objective, frontier=frontier)

    # 清理数值噪声后**重新投影**，而不是按和归一化——
    # 按和缩放会把触顶的权重推回上限之上，破坏盒约束与簇约束。
    weights = np.where(np.abs(weights) < 1e-4, 0.0, weights)
    if abs(float(weights.sum()) - float(max_gross)) > 1e-9:
        weights = project(weights, si.total, si.lo, si.hi, si.halfspaces)

    feasible, why_infeasible = is_feasible(weights, si)
    if not feasible:
        # 极端参数下（如上限×标的数 < 总仓位）确实可能无解，退回可行兜底
        weights = project(np.full(n, 1.0 / n), si.total, si.lo, si.hi, si.halfspaces)
        feasible, why_infeasible = is_feasible(weights, si)

    pstats = portfolio_stats(weights, si)
    astats = asset_stats(symbols, mu, cov, weights, rets, rf=si.rf)

    # 等权基准，用于对比「优化到底有没有用」
    ew = np.full(n, 1.0 / n)
    ew_stats = portfolio_stats(ew, si)

    notes = [
        f"协方差估计：{cov_method}（年化因子 {periods_per_year}）",
        f"期望收益估计：{return_method}",
        f"样本区间：{str(rets.index[0])[:10]} ~ {str(rets.index[-1])[:10]}，{len(rets)} 个交易日",
        f"约束：单标的上限 {effective_max_weight:.2%}、总仓位 {max_gross:.0%}"
        + (f"、相关性 ≥ {corr_threshold:.2f} 的标的总权重 ≤ {max_cluster_weight:.0%}" if clusters else ""),
    ]
    if cap_relaxed:
        notes.append(
            f"⚠️ 单标的上限 {max_weight:.0%} × {n} 个标的 = {max_weight * n:.0%} < 总仓位 "
            f"{max_gross:.0%}，约束无解；已自动放宽上限至 {effective_max_weight:.2%}（等权）。"
            f"如需严格守住 {max_weight:.0%}，请把总仓位降到 {max_weight * n:.0%} 或以下。"
        )
    if dropped:
        notes.append(f"因数据不足剔除：{', '.join(dropped)}")
    if clusters:
        notes.append(
            "检测到高相关簇：" + "；".join(
                f"[{'/'.join(symbols[i] for i in c)}]" for c in clusters
            )
        )
    if cov_method == "sample":
        notes.append("⚠️ 使用样本协方差，标的数接近样本量时权重可能不稳定，建议改用 Ledoit-Wolf")
    if not feasible:
        notes.append(f"⚠️ 约束无解，已退回等权可行解：{why_infeasible}")

    return {
        "ok": True,
        "objective": objective,
        "symbols": symbols,
        "weights": {s: float(weights[i]) for i, s in enumerate(symbols)},
        "feasible": feasible,
        "infeasible_reason": why_infeasible,
        "portfolio": pstats,
        "benchmark_equal_weight": ew_stats,
        "assets": astats,
        "correlation": {
            "symbols": symbols,
            "matrix": [[float(x) for x in row] for row in corr],
        },
        "clusters": [[symbols[i] for i in c] for c in clusters],
        "frontier": frontier,
        "constraints": {
            "max_weight": max_weight, "min_weight": min_weight, "max_gross": max_gross,
            "long_only": long_only, "corr_threshold": corr_threshold,
            "max_cluster_weight": max_cluster_weight,
            "effective_max_weight": effective_max_weight,
            "max_weight_relaxed": cap_relaxed,
        },
        "params": {
            "cov_method": cov_method, "return_method": return_method,
            "risk_free_rate": risk_free_rate, "periods_per_year": periods_per_year,
        },
        "notes": notes,
    }
