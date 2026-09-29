"""
因子 IC（信息系数）诊断
========================
对多因子策略的每个启用因子计算「因子值 vs 未来 N 期收益」的横截面 Spearman 相关（IC），
输出平均 IC / IC 标准差 / ICIR / IC>0 占比 / 覆盖率，用于评估因子质量与权重设置。

口径（业界惯例）：
- |IC 均值| ≥ 0.03 视为有效因子，ICIR = IC均值 / IC标准差 ≥ 0.5 较稳健
- IC>0 占比 ≥ 55% 说明方向稳定，不靠少数极端月份撑起来

重要边界：IC 分析**必须使用未来收益**（t 期因子 vs t+horizon 收益），这是纯离线
研究工具的固有属性 —— 它绝不进入交易信号路径，与回测引擎的「无未来函数」铁律
（t 日信号 → t+1 开盘成交）互不冲突。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..strategies.base import SignalContext, Strategy


def _cross_section_spearman(a: pd.Series, b: pd.Series) -> float | None:
    """两截面的 Spearman 相关（秩的 Pearson）。有效样本 < 2 或零方差 → None。"""
    mask = a.notna() & b.notna() & np.isfinite(a.to_numpy(float)) & np.isfinite(b.to_numpy(float))
    if int(mask.sum()) < 2:
        return None
    ra, rb = a[mask].rank(), b[mask].rank()
    da, db = ra - ra.mean(), rb - rb.mean()
    denom = float(np.sqrt((da**2).sum()) * np.sqrt((db**2).sum()))
    if denom <= 0:
        return None
    return float((da * db).sum() / denom)


def factor_ic_report(
    strategy: Strategy,
    ctx: SignalContext,
    horizon: int = 21,
    min_names: int = 4,
) -> dict:
    """对策略暴露的每个启用因子计算 IC 统计。

    仅支持实现 `_active_factors(ctx)` 的策略（当前即 multi_factor_score）。
    返回 {"ok": bool, "horizon": int, "min_names": int, "factors": [...]}。
    """
    c = ctx.closes
    get_factors = getattr(strategy, "_active_factors", None)
    if get_factors is None:
        return {"ok": False, "error": "该策略不提供因子诊断（未暴露 _active_factors）", "factors": []}

    factors = get_factors(ctx)
    if not factors:
        return {"ok": False, "error": "所有因子权重均为 0 —— 先在参数里启用至少一个因子", "factors": []}

    # 未来收益：诊断专用（见模块 docstring 的边界说明）
    fwd = c.shift(-int(horizon)) / c - 1

    out: list[dict] = []
    for name, weight, invert, f in factors:
        # 方向统一为「因子值越大越看多」：与 generate() 的 rank_norm * dir 同一口径
        fv = f * (-1.0 if invert else 1.0)
        ic_list: list[float] = []
        cov_list: list[float] = []
        for i in range(len(c)):
            ic = _cross_section_spearman(fv.iloc[i], fwd.iloc[i])
            if ic is None:
                continue
            ic_list.append(ic)
            valid = int((fv.iloc[i].notna() & np.isfinite(fv.iloc[i].to_numpy(float))).sum())
            cov_list.append(valid / max(1, len(c.columns)))

        row: dict = {
            "name": str(name),
            "weight": round(float(weight), 2),
            "n_dates": len(ic_list),
        }
        if len(ic_list) >= 5:
            arr = np.asarray(ic_list, dtype=float)
            sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
            row.update({
                "ic_mean": round(float(arr.mean()), 4),
                "ic_std": round(sd, 4),
                "icir": round(float(arr.mean()) / sd, 3) if sd > 1e-9 else None,
                "ic_positive_pct": round(float((arr > 0).mean()), 3),
                "coverage": round(float(np.mean(cov_list)), 3) if cov_list else None,
            })
        else:
            row.update({
                "ic_mean": None, "ic_std": None, "icir": None,
                "ic_positive_pct": None, "coverage": None,
                "note": "有效截面不足（样本太短或重叠交易日太少）",
            })
        out.append(row)

    return {"ok": True, "horizon": int(horizon), "min_names": int(min_names), "factors": out}
