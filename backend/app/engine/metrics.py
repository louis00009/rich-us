"""
绩效与风险指标
================
输入净值曲线与成交记录，输出机构级绩效报告所需的全套指标。
所有年化一律按 252 个交易日。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# P1-8：年化因子按 bar 周期推导，不再硬编码 252。
# 旧实现对 1h/30m/15m/5m/1wk 回测一律按日频年化 —— 1h 回测的夏普与波动率
# 被低估 √7 ≈ 2.65 倍，1wk 被高估。美股常规时段每天 6.5 小时。
_BAR_MAP_PPY: dict[str, float] = {
    "1d": 252.0,
    "1h": 252.0 * 6.5,
    "30m": 252.0 * 13.0,
    "15m": 252.0 * 26.0,
    "5m": 252.0 * 78.0,
    "1m": 252.0 * 390.0,
    "1wk": 52.0,
}


def periods_per_year(interval: str) -> float:
    """按 bar 周期返回年化 bar 数（未知周期按日线 252 处理）。"""
    return _BAR_MAP_PPY.get(str(interval or "1d").lower(), 252.0)


def _safe(x: float) -> float:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return 0.0
    return float(x)


def drawdown_series(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0


def max_drawdown(equity: pd.Series) -> tuple[float, int, str, str]:
    """返回 (最大回撤(负数), 最长水下期 **bar 数**, 回撤开始日, 回撤最低点日)。

    注意：第二个返回值是 **bar 计数**而非日历天数（日线回测下两者近似，
    但分钟/小时周期下差异巨大）。指标标签已改为「最长水下期(bar)」，
    此处注释同步修正 —— 旧注释写「天数」，与实现不符。
    """
    if len(equity) < 2:
        return 0.0, 0, "", ""
    peak = equity.cummax()
    dd = equity / peak - 1.0
    mdd = float(dd.min())
    trough_idx = dd.idxmin()
    peak_idx = equity.loc[:trough_idx].idxmax()

    # 最长水下期
    underwater = dd < -1e-9
    longest, cur, start = 0, 0, None
    for ts, uw in underwater.items():
        if uw:
            if cur == 0:
                start = ts
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return mdd, longest, str(peak_idx)[:10], str(trough_idx)[:10]


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    yrs = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-6)
    if yrs < 1 / 365:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    if total <= 0:
        return -1.0
    return float(total ** (1 / yrs) - 1)


def period_returns(equity: pd.Series) -> pd.Series:
    """逐 bar 收益率。

    P3：必须清理 ±inf。权益序列出现 0（空头巨亏 / 停牌估值异常）时，
    `pct_change()` 会产生 ±inf，而下游 `_safe()` 会把它静默吞成 0 ——
    结果是 Sharpe / 波动率 / Alpha 全部变成 0 却没有任何报错，
    比直接抛异常更难排查。
    """
    return equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)


def sharpe(ret: pd.Series, rf: float = 0.0, ppy: float = TRADING_DAYS) -> float:
    # P3：用阈值而非浮点精确比较 —— `std == 0` 在浮点下几乎永不成立，
    # 而极小的标准差会让比率爆炸成天文数字。同时挡掉 NaN / inf。
    if len(ret) < 3:
        return 0.0
    sd = float(ret.std(ddof=1))
    if not np.isfinite(sd) or sd < 1e-12:
        return 0.0
    excess = ret - rf / ppy
    return float(excess.mean() / sd * np.sqrt(ppy))


def sortino(ret: pd.Series, rf: float = 0.0, ppy: float = TRADING_DAYS) -> float:
    """索提诺比率。

    P1-8：下行偏差必须按**全样本**计算 —— sqrt(mean(min(r − MAR, 0)²))。
    旧实现取 `excess[excess < 0].std(ddof=1)`（负收益子集的样本标准差），
    分母偏小 → 比率系统性偏高（实测 500 样本高估约 16%），
    会直接影响「多策略对比」页的排序。
    """
    if len(ret) < 3:
        return 0.0
    excess = ret - rf / ppy
    dd = float(np.sqrt(np.mean(np.minimum(excess.to_numpy(dtype=float), 0.0) ** 2)))
    if not dd or np.isnan(dd) or np.isinf(dd):
        return 0.0
    return float(excess.mean() / dd * np.sqrt(ppy))


def var_cvar(ret: pd.Series, level: float = 0.95) -> tuple[float, float]:
    if len(ret) < 20:
        return 0.0, 0.0
    q = float(np.quantile(ret, 1 - level))
    tail = ret[ret <= q]
    return q, float(tail.mean()) if len(tail) else q


def monthly_returns(equity: pd.Series) -> pd.DataFrame:
    if len(equity) < 2:
        return pd.DataFrame()
    m = equity.resample("ME").last().pct_change().dropna()
    if m.empty:
        return pd.DataFrame()
    df = pd.DataFrame({"year": m.index.year, "month": m.index.month, "ret": m.values})
    return df.pivot_table(index="year", columns="month", values="ret", aggfunc="last")


def trade_stats(trades: list[dict]) -> dict:
    if not trades:
        return {
            "trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "payoff_ratio": 0.0, "expectancy": 0.0, "avg_bars_held": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0, "max_consec_loss": 0,
        }
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    win_rate = len(wins) / len(pnls)
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    cons, best = 0, 0
    for p in pnls:
        cons = cons + 1 if p < 0 else 0
        best = max(best, cons)
    return {
        "trades": int(len(pnls)),
        "win_rate": _safe(win_rate),
        "profit_factor": _safe(gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0),
        "avg_win": _safe(avg_win),
        "avg_loss": _safe(avg_loss),
        "payoff_ratio": _safe(abs(avg_win / avg_loss)) if avg_loss else 0.0,
        "expectancy": _safe(pnls.mean()),
        "avg_bars_held": _safe(np.mean([t.get("bars_held", 0) for t in trades])),
        "best_trade": _safe(pnls.max()),
        "worst_trade": _safe(pnls.min()),
        "max_consec_loss": int(best),
    }


def alpha_beta(ret: pd.Series, bench_ret: pd.Series, ppy: float = TRADING_DAYS) -> tuple[float, float, float]:
    a, b = ret.align(bench_ret, join="inner")
    if len(a) < 30 or b.std(ddof=1) == 0:
        return 0.0, 0.0, 0.0
    beta = float(np.cov(a, b, ddof=1)[0, 1] / np.var(b, ddof=1))
    alpha = float((a.mean() - beta * b.mean()) * ppy)
    excess = a - b
    ir = float(excess.mean() / excess.std(ddof=1) * np.sqrt(ppy)) if excess.std(ddof=1) else 0.0
    return alpha, beta, ir


def compute_metrics(
    equity: pd.Series,
    trades: list[dict],
    initial_capital: float,
    bench_equity: pd.Series | None = None,
    exposure: pd.Series | None = None,
    turnover: float = 0.0,
    rf: float = 0.0,
    periods_per_year: float | None = None,
) -> dict:
    # P1-8：年化因子按 bar 周期推导（默认日线 252），1h/1wk 等周期不再被错误年化
    ppy = float(periods_per_year) if periods_per_year else float(TRADING_DAYS)
    equity = equity.astype(float)
    ret = period_returns(equity)
    mdd, dd_days, dd_start, dd_trough = max_drawdown(equity)
    c = cagr(equity)
    vol = float(ret.std(ddof=1) * np.sqrt(ppy)) if len(ret) > 2 else 0.0
    var95, cvar95 = var_cvar(ret)
    ts = trade_stats(trades)

    bench_total = bench_cagr = bench_mdd = 0.0
    alpha, beta, ir = 0.0, 0.0, 0.0
    if bench_equity is not None and len(bench_equity) > 2:
        b = bench_equity.reindex(equity.index).ffill().dropna()
        if len(b) > 2:
            bench_total = float(b.iloc[-1] / b.iloc[0] - 1)
            bench_cagr = cagr(b)
            bench_mdd = max_drawdown(b)[0]
            alpha, beta, ir = alpha_beta(ret, period_returns(b), ppy)

    monthly = monthly_returns(equity)
    best_month = worst_month = 0.0
    if not monthly.empty:
        vals = monthly.to_numpy(dtype=float)
        vals = vals[~np.isnan(vals)]
        if len(vals):
            best_month, worst_month = float(vals.max()), float(vals.min())

    return {
        # 收益
        "total_return": _safe(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) > 1 else 0.0,
        "cagr": _safe(c),
        "final_equity": _safe(equity.iloc[-1]) if len(equity) else initial_capital,
        "initial_capital": float(initial_capital),
        # 风险
        "volatility": _safe(vol),
        "max_drawdown": _safe(mdd),
        "max_dd_days": int(dd_days),
        "dd_start": dd_start,
        "dd_trough": dd_trough,
        "var95_daily": _safe(var95),
        "cvar95_daily": _safe(cvar95),
        # 风险调整
        "sharpe": _safe(sharpe(ret, rf, ppy)),
        "sortino": _safe(sortino(ret, rf, ppy)),
        "calmar": _safe(c / abs(mdd)) if mdd < 0 else 0.0,
        # 交易
        **ts,
        # 其他
        "turnover": _safe(turnover),
        "avg_exposure": _safe(exposure.mean()) if exposure is not None and len(exposure) else 0.0,
        "best_month": _safe(best_month),
        "worst_month": _safe(worst_month),
        "skew": _safe(ret.skew()) if len(ret) > 3 else 0.0,
        "kurtosis": _safe(ret.kurtosis()) if len(ret) > 3 else 0.0,
        # 基准
        "benchmark_total_return": _safe(bench_total),
        "benchmark_cagr": _safe(bench_cagr),
        "benchmark_max_drawdown": _safe(bench_mdd),
        "alpha": _safe(alpha),
        "beta": _safe(beta),
        "information_ratio": _safe(ir),
        "excess_cagr": _safe(c - bench_cagr),
    }


METRIC_LABELS: list[dict[str, str]] = [
    {"key": "total_return", "label": "累计收益", "fmt": "pct"},
    {"key": "cagr", "label": "年化收益 (CAGR)", "fmt": "pct"},
    {"key": "excess_cagr", "label": "超额年化(vs基准)", "fmt": "pct"},
    {"key": "volatility", "label": "年化波动率", "fmt": "pct"},
    {"key": "sharpe", "label": "夏普比率", "fmt": "num"},
    {"key": "sortino", "label": "索提诺比率", "fmt": "num"},
    {"key": "calmar", "label": "卡玛比率", "fmt": "num"},
    {"key": "max_drawdown", "label": "最大回撤", "fmt": "pct"},
    {"key": "max_dd_days", "label": "最长水下期(bar)", "fmt": "int"},
    {"key": "win_rate", "label": "胜率", "fmt": "pct"},
    {"key": "profit_factor", "label": "盈亏比(总额)", "fmt": "num"},
    {"key": "payoff_ratio", "label": "平均盈亏比", "fmt": "num"},
    {"key": "expectancy", "label": "单笔期望盈亏", "fmt": "money"},
    {"key": "trades", "label": "交易笔数", "fmt": "int"},
    {"key": "avg_bars_held", "label": "平均持有(bar)", "fmt": "num"},
    {"key": "turnover", "label": "年化换手率", "fmt": "num"},
    {"key": "avg_exposure", "label": "平均持仓比例", "fmt": "pct"},
    {"key": "var95_daily", "label": "日 VaR(95%)", "fmt": "pct"},
    {"key": "cvar95_daily", "label": "日 CVaR(95%)", "fmt": "pct"},
    {"key": "beta", "label": "Beta", "fmt": "num"},
    {"key": "alpha", "label": "年化 Alpha", "fmt": "pct"},
    {"key": "information_ratio", "label": "信息比率", "fmt": "num"},
    {"key": "benchmark_cagr", "label": "基准年化", "fmt": "pct"},
    {"key": "benchmark_max_drawdown", "label": "基准最大回撤", "fmt": "pct"},
]
