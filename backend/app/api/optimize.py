"""组合优化接口。

与 `/backtest/optimize`（参数寻优）不同：那边搜的是**策略参数**，
这里求的是**资金权重**——输入一篮子标的，输出每个标的配多少仓位。
"""
from __future__ import annotations

import json

import pandas as pd
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..data_provider import fetch_many
from ..engine.optimizer import (
    COV_METHODS,
    OBJECTIVES,
    RETURN_METHODS,
    OptimizeError,
    optimize_portfolio,
)
from ..models import StrategyConfig
from ..schemas import OptimizeSaveRequest, PortfolioOptimizeRequest
from .deps import CurrentUser, DbSession

router = APIRouter(prefix="/optimize", tags=["组合优化"])

# 目标函数的中文说明——前端直接渲染，避免文案散落两处
_OBJECTIVE_META = {
    "max_sharpe": ("最大夏普", "在给定约束下最大化「超额收益 / 波动」，最常用的默认目标"),
    "min_variance": ("最小方差", "只压波动不看收益，权重通常集中在低波动资产上"),
    "max_return": ("最大收益", "纯粹追期望收益，会严重依赖历史均值，外推风险最高"),
    "risk_parity": ("风险平价", "让每个标的贡献的风险相等，可配合风险预算做主动倾斜"),
    "inverse_vol": ("波动率倒数", "按 1/σ 分配，最小方差的解析近似，无需迭代、最稳"),
    "equal_weight": ("等权", "1/N 基准。优化前先看它——很多「优化」打不过等权"),
}

_COV_META = {
    "ledoit_wolf": ("Ledoit-Wolf 收缩", "向对角阵收缩，样本量不足时显著更稳（默认）"),
    "sample": ("样本协方差", "无偏但噪声大，标的数接近样本量时可能不可逆"),
    "ewma": ("指数加权", "对近期波动更敏感，适合波动率结构在变化的场景"),
}

_RETURN_META = {
    "shrunk": ("贝叶斯收缩", "Jorion Bayes-Stein，把极端均值拉向最小方差组合收益（默认）"),
    "mean": ("历史算术均值", "最直观也最不稳，容易把过去的赢家配成重仓"),
    "ewma": ("指数加权均值", "偏向近期表现，换手会比 shrunk 更高"),
}


@router.get("/meta")
def meta(user: CurrentUser = None) -> dict:  # noqa: ARG001
    """前端表单需要的全部枚举与默认值。"""
    return {
        "objectives": [
            {"key": k, "label": _OBJECTIVE_META[k][0], "desc": _OBJECTIVE_META[k][1]}
            for k in OBJECTIVES
        ],
        "cov_methods": [
            {"key": k, "label": _COV_META[k][0], "desc": _COV_META[k][1]} for k in COV_METHODS
        ],
        "return_methods": [
            {"key": k, "label": _RETURN_META[k][0], "desc": _RETURN_META[k][1]}
            for k in RETURN_METHODS
        ],
        "defaults": {
            "objective": "max_sharpe", "cov_method": "ledoit_wolf", "return_method": "shrunk",
            "max_weight": 0.35, "min_weight": 0.0, "max_gross": 1.0, "long_only": True,
            "corr_threshold": 0.85, "max_cluster_weight": 0.5,
            "risk_free_rate": 0.0, "periods_per_year": 252, "include_frontier": True,
        },
        "notes": [
            "协方差与期望收益均为历史估计，不含任何前瞻信息；结果反映的是「过去的结构」。",
            "优化器只能决定权重，不能替你判断标的是否该纳入——标的池的选择权在人。",
            "默认对相关系数 ≥ 0.85 的标的施加总权重上限，避免伪分散（持有 6 只半导体不是分散）。",
        ],
    }


def _load_prices(payload: PortfolioOptimizeRequest) -> tuple[pd.DataFrame, dict[str, str]]:
    """拉取并拼接收盘价矩阵。返回 (prices, 各标的实际数据源)。"""
    prefer = None if payload.data_source in ("", "auto") else payload.data_source
    raw, sources = fetch_many(
        payload.symbols, payload.start, payload.end, payload.interval, prefer=prefer
    )
    if not raw:
        raise HTTPException(400, "未获取到任何行情数据，请检查标的代码、时间范围或网络连接")

    cols: dict[str, pd.Series] = {}
    for sym, df in raw.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        ser = df["close"].copy()
        ser.index = pd.to_datetime(ser.index, utc=True, errors="coerce").tz_localize(None)
        ser = ser[~ser.index.isna()]
        ser = ser[~ser.index.duplicated(keep="last")].sort_index()
        if len(ser) > 20:
            cols[sym] = ser
    if len(cols) < 2:
        raise HTTPException(
            400,
            f"有效标的不足（仅 {len(cols)} 个有足够历史数据），组合优化至少需要 2 个",
        )
    prices = pd.DataFrame(cols).sort_index()
    return prices, sources


@router.post("/run")
async def run(payload: PortfolioOptimizeRequest, user: CurrentUser) -> dict:
    prices, sources = _load_prices(payload)

    def _work() -> dict:
        return optimize_portfolio(
            prices,
            objective=payload.objective,
            cov_method=payload.cov_method,
            return_method=payload.return_method,
            risk_free_rate=payload.risk_free_rate,
            periods_per_year=payload.periods_per_year,
            max_weight=payload.max_weight,
            min_weight=payload.min_weight,
            max_gross=payload.max_gross,
            long_only=payload.long_only,
            corr_threshold=payload.corr_threshold,
            max_cluster_weight=payload.max_cluster_weight,
            risk_budget=payload.risk_budget or None,
            include_frontier=payload.include_frontier,
        )

    try:
        result = await run_in_threadpool(_work)
    except OptimizeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"优化失败：{type(exc).__name__}: {exc}") from exc

    # 数据源曝光：合成数据绝不能当成真实历史去配权重
    used = sorted(set(sources.values()))
    synthetic = [s for s, v in sources.items() if v == "synthetic"]
    result["data_sources"] = sources
    result["data_source_used"] = used[0] if len(used) == 1 else "mixed"
    result["synthetic_symbols"] = synthetic
    if synthetic:
        result["notes"].append(
            f"⚠️ 以下标的为**合成行情**（非真实数据），权重不可用于实盘：{', '.join(synthetic)}"
        )

    await run_in_threadpool(
        appstate.log,
        "portfolio_optimize", "INFO",
        f"组合优化 {len(result['symbols'])} 标的 · {payload.objective} · "
        f"数据源 {'/'.join(used)} · 预期夏普 {result['portfolio'].get('sharpe', 0):.2f}",
        user.username,
    )
    return result


@router.post("/save")
def save(payload: OptimizeSaveRequest, db: DbSession, user: CurrentUser) -> dict:
    """把优化出的权重落成一条可直接回测/运行的「静态权重」代码策略。

    生成的是恒定权重策略：每根 bar 都输出同一组目标权重，
    引擎按权重再平衡。这是把优化结果接入回测与实盘的最短路径。
    """
    weights = {str(k).upper(): float(v) for k, v in payload.weights.items()}
    weights = {k: v for k, v in weights.items() if abs(v) > 1e-6}
    if not weights:
        raise HTTPException(400, "权重为空，无法保存")

    total = sum(weights.values())
    if total <= 0:
        raise HTTPException(400, "权重之和必须为正")

    symbols = [s.strip().upper() for s in payload.symbols if s.strip()]
    if not symbols:
        symbols = list(weights)

    exists = db.execute(
        select(StrategyConfig).where(StrategyConfig.name == payload.name)
    ).scalars().first()
    if exists:
        raise HTTPException(409, f"策略名「{payload.name}」已存在，请换一个名字")

    # 生成静态权重策略代码（已过 AST 白名单，不含 import / lambda / 文件 I/O）
    pairs = ", ".join(f"{s!r}: {v / total:.8f}" for s, v in weights.items())
    code = (
        "def generate(ctx):\n"
        "    # 由组合优化器生成：恒定目标权重，每根 bar 按权重再平衡\n"
        f"    target = {{{pairs}}}\n"
        "    idx = ctx.closes.index\n"
        "    cols = {}\n"
        "    for s in ctx.symbols:\n"
        "        cols[s] = [float(target.get(s, 0.0))] * len(idx)\n"
        "    return pd.DataFrame(cols, index=idx)\n"
    )

    row = StrategyConfig(
        name=payload.name,
        kind="code",
        strategy_key="custom_code",
        params_json=json.dumps({"portfolio_weights": weights, "objective": payload.objective},
                               ensure_ascii=False),
        code=code,
        symbols_json=json.dumps(symbols),
        notes=(payload.notes or "")[:900]
        or f"由组合优化器生成（目标：{payload.objective}），权重合计 {total:.4f}",
        tags_json=json.dumps(["组合优化", payload.objective]),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    appstate.log(
        "portfolio_save", "INFO",
        f"优化权重另存为策略「{payload.name}」（#{row.id}，{len(weights)} 标的）",
        actor=user.username,
    )
    return {
        "ok": True, "id": row.id, "name": row.name,
        "kind": row.kind, "strategy_key": row.strategy_key,
        "symbols": symbols, "weights": weights,
    }
