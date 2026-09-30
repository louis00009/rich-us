"""组合优化的数学核（FILE_SIZE_DEBT Batch E-1 从 optimizer.py 拆出）。

只放「纯数学」：收益/协方差/期望收益估计、Dykstra 凸投影、可行性判定、
相关性簇。求解器（投影梯度上升、目标函数、optimize_portfolio）留在
optimizer.py，旧 import 路径经 re-export 保持可用。

协方差的坑（曾实际踩中）：**协方差用去均值数据估计，期望收益必须用原始收益**
—— 传去均值矩阵给 estimate_mean 会让 μ 恒为 0，最大夏普退化为最小方差。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # 只为注解 —— 运行时不导入，避免 optimizer_math ↔ optimizer 成环
    from .optimizer import SolveInput


class OptimizeError(ValueError):
    """优化输入不合法或数据不足。"""


# ======================================================================
# 输入准备
# ======================================================================
def to_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """收盘价 → 简单收益率，去极值并丢弃全空行。"""
    px = prices.astype(float).replace(0.0, np.nan)
    rets = px / px.shift(1) - 1.0
    rets = rets.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    # 极端值（拆分/数据错误）截断，避免污染协方差
    return rets.clip(lower=-0.5, upper=0.5)


# ======================================================================
# 协方差估计
# ======================================================================
def ledoit_wolf_diag(X: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf 收缩协方差（目标为对角阵）。

    X 为已去均值的 T×N 收益矩阵。收缩强度按 LW 的解析式估计：
        δ* = clip((π − ρ) / γ / T, 0, 0.95)
    其中
        π = Σ_ij Var̂(√T·s_ij)     （样本协方差各元素方差之和）
        ρ = Σ_i  Var̂(√T·s_ii)     （对角项对应的协方差项）
        γ = ‖F − S‖²_F, F = diag(S)
    为避免构造 T×N×N 张量，用 G = (X∘X)′(X∘X)/T 恒等改写。
    """
    T, N = X.shape
    if T < 2:
        raise OptimizeError("样本量不足，无法估计协方差")
    S = X.T @ X / T
    F = np.diag(np.diag(S))

    XX = X * X
    G = XX.T @ XX / T                                   # G_ij = (1/T)Σ_t x_ti²x_tj²
    pi = float(G.sum() - (S * S).sum())
    d = np.diag(S)
    rho = float((X ** 4).sum() / T - (d * d).sum())
    gamma = float(((S - F) ** 2).sum())
    if gamma <= 1e-14:
        return S                                        # 已是对角阵，无需收缩
    delta = float(np.clip((pi - rho) / gamma / T, 0.0, 0.95))
    return delta * F + (1.0 - delta) * S


def ewma_cov(X: np.ndarray, halflife: int = 63) -> np.ndarray:
    """指数加权协方差（离当前越近权重越高）。"""
    T = X.shape[0]
    lam = 0.5 ** (1.0 / max(int(halflife), 1))
    w = lam ** np.arange(T - 1, -1, -1)
    w = w / w.sum()
    Xw = X * np.sqrt(w)[:, None]
    return Xw.T @ Xw


def estimate_cov(X: np.ndarray, method: str) -> np.ndarray:
    if method == "sample":
        return X.T @ X / max(X.shape[0], 1)
    if method == "ewma":
        return ewma_cov(X)
    if method == "ledoit_wolf":
        return ledoit_wolf_diag(X)
    raise OptimizeError(f"未知协方差估计方法：{method}")


def _ewma_mean(X: np.ndarray, halflife: int = 63) -> np.ndarray:
    T = X.shape[0]
    lam = 0.5 ** (1.0 / max(int(halflife), 1))
    w = lam ** np.arange(T - 1, -1, -1)
    return (X * (w / w.sum())[:, None]).sum(axis=0)


# ======================================================================
# 期望收益估计
# ======================================================================
def bayes_stein_mean(mu: np.ndarray, cov: np.ndarray, n_obs: int) -> np.ndarray:
    """Jorion(1986) Bayes-Stein 收缩：向最小方差组合的收益收缩。

    样本均值收益的估计误差会主导最大夏普组合的权重，收缩能显著改善样本外表现。
        w = (N+2) / ((N+2) + T·(μ−μ₀1)′Σ⁻¹(μ−μ₀1))
        μ_BS = (1−w)·μ + w·μ₀·1
    """
    N = mu.size
    if N < 2:
        return mu
    try:
        inv = np.linalg.pinv(cov)
    except np.linalg.LinAlgError:
        return mu
    ones = np.ones(N)
    denom = float(ones @ inv @ ones)
    if denom <= 1e-14:
        return mu
    mu0 = float(mu @ inv @ ones) / denom                # 最小方差组合的期望收益
    diff = mu - mu0 * ones
    quad = float(diff @ inv @ diff)
    T_eff = int(n_obs) if n_obs > 0 else max(N * 4, 60)
    w = (N + 2) / ((N + 2) + T_eff * max(quad, 1e-12))
    w = float(np.clip(w, 0.0, 1.0))
    return (1.0 - w) * mu + w * mu0 * ones


def estimate_mean(X: np.ndarray, cov: np.ndarray, method: str) -> np.ndarray:
    """返回**单期**期望收益（调用方负责年化）。"""
    mu = X.mean(axis=0)
    if method == "mean":
        return mu
    if method == "ewma":
        return _ewma_mean(X)
    if method == "shrunk":
        return bayes_stein_mean(mu, cov, int(X.shape[0]))
    raise OptimizeError(f"未知期望收益估计方法：{method}")


# ======================================================================
# 凸投影（Dykstra 交替投影）
# ======================================================================
def _proj_simplex_box(v: np.ndarray, total: float, lo: np.ndarray, hi: np.ndarray,
                      iters: int = 36) -> np.ndarray:
    """投影到 {Σw = total, lo ≤ w ≤ hi}。

    对偶变量 τ 单调，二分即可：w(τ) = clip(v + τ, lo, hi)。
    36 次二分已足够（精度 ~2⁻³⁶ × 取值范围）。
    """
    a = float((v - hi).min() - abs(total) - 1.0)
    b = float((v - lo).max() + abs(total) + 1.0)
    for _ in range(iters):
        mid = 0.5 * (a + b)
        s = float(np.clip(v + mid, lo, hi).sum())
        if s > total:
            b = mid
        else:
            a = mid
    return np.clip(v + 0.5 * (a + b), lo, hi)


def _proj_halfspace(w: np.ndarray, idx: np.ndarray, cap: float) -> np.ndarray:
    """投影到 {Σ_{i∈idx} w_i ≤ cap}（单个线性不等式的投影有闭式解）。"""
    s = float(w[idx].sum())
    if s <= cap or idx.size == 0:
        return w
    out = w.copy()
    out[idx] = w[idx] - (s - cap) / idx.size
    return out


def project(
    v: np.ndarray,
    total: float,
    lo: np.ndarray,
    hi: np.ndarray,
    halfspaces: Iterable[tuple[np.ndarray, float]] = (),
    iters: int = 120,
    tol: float = 1e-13,
) -> np.ndarray:
    """Dykstra 交替投影：box-simplex ∩ 若干半空间。

    收敛到该交集的真正欧氏投影。用「迭代位移小于 tol」提前退出，
    常规规模（N≤30、簇≤3）通常 15~30 轮即可收敛。
    """
    sets: list[Callable[[np.ndarray], np.ndarray]] = [
        lambda w: _proj_simplex_box(w, total, lo, hi)
    ]
    for idx, cap in halfspaces:
        sets.append(lambda w, i=idx, c=cap: _proj_halfspace(w, i, c))

    w = v.astype(float).copy()
    if len(sets) == 1:
        return sets[0](w)

    corr = [np.zeros_like(w) for _ in sets]
    for _ in range(iters):
        moved = 0.0
        for k, P in enumerate(sets):
            y = w + corr[k]
            w_new = P(y)
            corr[k] = y - w_new
            moved = max(moved, float(np.max(np.abs(w_new - w))))
            w = w_new
        if moved < tol:
            break
    # 以 0.5 的概率最后一轮停在半空间上会导致 sum 漂移，
    # 这里显式再投一次 box-simplex，保证 Σw=total 与盒上限严格成立
    # （簇约束在收敛后偏差 < tol，量级上可忽略）
    return _proj_simplex_box(w, total, lo, hi)


def is_feasible(w: np.ndarray, si: "SolveInput", tol: float = 1e-6) -> tuple[bool, str]:
    """检查解是否满足全部约束，返回 (是否可行, 违反说明)。

    si 为 optimizer.SolveInput（只读其 total/lo/hi/halfspaces 属性，
    为避免循环 import 用字符串注解）。
    """
    if abs(float(w.sum()) - si.total) > tol * max(1.0, abs(si.total)):
        return False, f"权重和 {w.sum():.6f} ≠ {si.total}"
    if float(w.min()) < float(si.lo.min()) - tol:
        return False, f"存在低于下限的权重 {w.min():.6f}"
    worst = float((w - si.hi).max())
    if worst > tol:
        return False, f"超出单标的上限 {worst:.6f}"
    for idx, cap in si.halfspaces:
        s = float(w[idx].sum())
        if s > cap + tol:
            return False, f"簇权重 {s:.6f} 超过上限 {cap:.6f}"
    return True, ""


# ======================================================================
# 相关性簇（"不要把鸡蛋放在同一个篮子里"的可计算版本）
# ======================================================================
def correlation_clusters(corr: np.ndarray, threshold: float) -> list[list[int]]:
    """把两两相关性 ≥ 阈值的标的并成一个簇（并查集）。"""
    n = corr.shape[0]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if np.isfinite(corr[i, j]) and abs(corr[i, j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]
