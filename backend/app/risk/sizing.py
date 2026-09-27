"""
仓位管理算法
=============
把「目标权重 / 信号」翻译成「实际股数」，并施加风控上限。
所有函数返回目标名义金额（美元），由调用方换算股数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def fixed_fraction(equity: float, weight: float, price: float, max_position_pct: float) -> float:
    """固定比例：按权益的固定百分比建仓。"""
    pct = min(abs(weight), max_position_pct / 100.0)
    return equity * pct * np.sign(weight) if weight else 0.0


def equal_weight(equity: float, n_positions: int, gross_pct: float = 100.0) -> float:
    n = max(int(n_positions), 1)
    return equity * (gross_pct / 100.0) / n


def risk_parity_vol(
    equity: float,
    vols: dict[str, float],
    weights: dict[str, float],
    gross_pct: float = 100.0,
    max_position_pct: float = 20.0,
) -> dict[str, float]:
    """波动率倒数加权：低波动标的多配。返回 symbol -> 名义金额。"""
    active = {s: abs(w) for s, w in weights.items() if w}
    if not active:
        return {}
    inv = {s: 1.0 / max(vols.get(s, 0.2), 1e-4) for s in active}
    tot = sum(inv.values())
    budget = equity * gross_pct / 100.0
    out = {}
    for s in active:
        share = inv[s] / tot
        notional = min(budget * share, equity * max_position_pct / 100.0)
        out[s] = notional * np.sign(weights[s])
    return out


def atr_risk(
    equity: float,
    price: float,
    atr_value: float | None,
    stop_mult: float,
    risk_per_trade_pct: float,
    max_position_pct: float = 20.0,
    weight: float = 1.0,
) -> float:
    """
    固定风险仓位（机构标准做法）：
        股数 = (权益 × 每笔风险%) / (ATR × 止损倍数)
    即无论标的波动率高低，单笔最大亏损都锁定在 risk_per_trade_pct。
    """
    if not price or price <= 0:
        return 0.0
    stop_dist = (float(atr_value) * float(stop_mult)) if atr_value else price * 0.05
    stop_dist = float(np.clip(stop_dist, price * 0.002, price * 0.30))
    risk_amt = equity * float(risk_per_trade_pct) / 100.0
    qty = risk_amt / stop_dist
    notional = qty * price
    cap = equity * float(max_position_pct) / 100.0
    notional = min(notional, cap)
    return notional * (np.sign(weight) if weight else 1.0)


def kelly_capped(
    equity: float,
    win_rate: float,
    win_loss_ratio: float,
    price: float,
    fraction: float = 0.5,
    cap_pct: float = 20.0,
    max_position_pct: float = 20.0,
) -> float:
    """
    凯利公式（可选半凯利降波动）：
        f* = p - (1-p)/b
    fraction 为凯利系数（0.5 = 半凯利），最终受 cap_pct 硬顶约束。
    """
    p = float(np.clip(win_rate, 0.01, 0.99))
    b = max(float(win_loss_ratio), 0.05)
    f = p - (1 - p) / b
    if f <= 0:
        return 0.0
    pct = min(f * float(fraction), float(cap_pct) / 100.0, float(max_position_pct) / 100.0)
    return equity * pct


def compute_target_notional(
    method: str,
    equity: float,
    weight: float,
    price: float,
    *,
    atr_value: float | None = None,
    stop_mult: float = 3.0,
    risk_per_trade_pct: float = 1.0,
    max_position_pct: float = 20.0,
    realized_vol: float | None = None,
    win_rate: float = 0.5,
    win_loss_ratio: float = 1.5,
    kelly_fraction: float = 0.5,
    n_positions: int = 1,
) -> float:
    """统一入口：按所选算法计算目标名义金额。"""
    if not weight or not price or price <= 0:
        return 0.0
    m = method
    if m == "fixed_fraction":
        return fixed_fraction(equity, weight, price, max_position_pct)
    if m == "equal_weight":
        amt = equal_weight(equity, n_positions)
        return amt * np.sign(weight)
    if m == "risk_parity_vol":
        vol = max(realized_vol or 0.2, 1e-4)
        target_vol = 0.20
        scale = np.clip(target_vol / vol, 0.1, 2.0)
        pct = min(abs(weight) * scale, max_position_pct / 100.0)
        return equity * pct * np.sign(weight)
    if m == "kelly_capped":
        amt = kelly_capped(equity, win_rate, win_loss_ratio, price, kelly_fraction, max_position_pct, max_position_pct)
        return amt * np.sign(weight)
    # 默认 atr_risk
    return atr_risk(equity, price, atr_value, stop_mult, risk_per_trade_pct, max_position_pct, weight)


def cap_targets(
    targets: dict[str, float],
    equity: float,
    max_position_pct: float = 20.0,
    gross_pct: float = 100.0,
) -> dict[str, float]:
    """对「逐标的权重 × 权益」类目标施加两级组合级约束（P0-1）。

    旧实现（backtest/live 的 weight 分支）对策略输出的逐标的权重只做逐元素 clip，
    不做 Σ 约束 —— 6 只标的各 100% 权重会跑出 6 倍免费杠杆，回测结论整体失真。
    这里统一施加：
      1. 单标的名义 ≤ equity × max_position_pct%（双向 clip，空头同样受限）；
      2. 总敞口 Σ|target| ≤ equity × gross_pct%（超限等比缩放）。
    """
    if equity <= 0 or not targets:
        return {s: float(v) for s, v in (targets or {}).items()}
    out = {s: float(v) for s, v in targets.items()}
    pos_cap = max(float(max_position_pct), 0.0) / 100.0 * equity
    if pos_cap > 0:
        out = {s: float(np.clip(v, -pos_cap, pos_cap)) for s, v in out.items()}
    g = sum(abs(v) for v in out.values())
    gross_cap = max(float(gross_pct), 0.0) / 100.0 * equity
    if gross_cap > 0 and g > gross_cap:
        k = gross_cap / g
        out = {s: v * k for s, v in out.items()}
    return out


def weights_to_notionals(
    weights: pd.Series,
    equity: float,
    prices: pd.Series,
    method: str,
    max_position_pct: float = 20.0,
    gross_pct: float = 100.0,
    atr_map: dict[str, float] | None = None,
    vol_map: dict[str, float] | None = None,
    risk_per_trade_pct: float = 1.0,
    stop_mult: float = 3.0,
) -> dict[str, float]:
    """一篮子权重 → 各标的目标名义金额（含总敞口约束）。"""
    atr_map = atr_map or {}
    vol_map = vol_map or {}
    raw = {s: float(w) for s, w in weights.items() if abs(float(w)) > 1e-9}
    if not raw:
        return {}
    n = len(raw)
    out: dict[str, float] = {}
    for s, w in raw.items():
        out[s] = compute_target_notional(
            method, equity, w, float(prices.get(s, 0.0)),
            atr_value=atr_map.get(s), stop_mult=stop_mult,
            risk_per_trade_pct=risk_per_trade_pct, max_position_pct=max_position_pct,
            realized_vol=vol_map.get(s), n_positions=n,
        )
    gross = sum(abs(v) for v in out.values())
    cap = equity * gross_pct / 100.0
    if gross > cap > 0:
        k = cap / gross
        out = {s: v * k for s, v in out.items()}
    return out
