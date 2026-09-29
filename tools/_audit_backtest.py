"""离线审计：用本地缓存日线跑真实回测（不联网），评估策略族的历史表现。
只读缓存，不写任何生产数据。
"""
from __future__ import annotations

import sys
import pathlib
import warnings

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd

from app.engine import backtest as bt

CACHE = ROOT / "backend" / "runtime" / "cache" / "1d"


def _read(sym: str, start: str, end: str | None, interval: str):
    p = CACHE / f"{sym}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def fake_fetch_many(symbols, start, end, interval="1d", prefer=None):
    out, src = {}, {}
    for s in symbols:
        df = _read(s, start, end, interval)
        if df is not None and len(df) > 0:
            out[s] = df
            src[s] = "cache"
    return out, src


def fake_fetch_history(symbol, start, end, interval="1d", prefer=None):
    df = _read(symbol, start, end, interval)
    return (df if df is not None else pd.DataFrame()), "cache"


bt.fetch_many = fake_fetch_many
bt.fetch_history = fake_fetch_history

START, END = "2019-01-01", "2026-09-25"
BASKETS = {
    "多资产7只(SPY/QQQ/IWM/EFA/EEM/TLT/GLD)": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"],
    "股指3只(SPY/QQQ/IWM)": ["SPY", "QQQ", "IWM"],
    "科技权重(QQQ/NVDA/MSFT/AAPL/META/GOOGL)": ["QQQ", "NVDA", "MSFT", "AAPL", "META", "GOOGL"],
    "单标的SPY": ["SPY"],
}
STRATS = [
    "dual_ma_trend", "tsmom_vol_target", "dual_momentum", "xs_momentum",
    "donchian_breakout", "supertrend", "trend_composite",
    "rsi_meanrev", "bollinger_meanrev", "connors_rsi2",
    "vol_managed_momentum", "regime_adaptive", "risk_parity_alloc", "ensemble_vote",
]


def run(basket, key, sizing="weight", stop_type="atr_trailing", stop_value=3.0):
    spec = bt.BacktestSpec(
        strategy_key=key, symbols=basket, start=START, end=END, interval="1d",
        initial_capital=100_000.0, commission_bps=1.0, slippage_bps=2.0,
        benchmark="SPY", sizing_method=sizing, max_position_pct=20.0, gross_pct=100.0,
        data_source="cache",
    )
    spec.stop.stop_type = stop_type
    spec.stop.stop_value = stop_value
    try:
        r = bt.run_backtest(spec)
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}
    return r


rows = []
for bname, basket in BASKETS.items():
    for key in STRATS:
        r = run(basket, key)
        if not r.get("ok"):
            rows.append((bname, key, None, None, None, None, None, r.get("err", "")[:60]))
            continue
        m = r["metrics"]
        rows.append((bname, key, m["cagr"], m["total_return"], m["sharpe"],
                     m["max_drawdown"], m["win_rate"], m["trades"]))

# 基准：SPY 买入持有
spy = _read("SPY", START, END, "1d")
spy_cagr = (spy["close"].iloc[-1] / spy["close"].iloc[0]) ** (1 / ((spy.index[-1] - spy.index[0]).days / 365.25)) - 1
spy_mdd = float((spy["close"] / spy["close"].cummax() - 1).min())
qqq = _read("QQQ", START, END, "1d")
qqq_cagr = (qqq["close"].iloc[-1] / qqq["close"].iloc[0]) ** (1 / ((qqq.index[-1] - qqq.index[0]).days / 365.25)) - 1
qqq_mdd = float((qqq["close"] / qqq["close"].cummax() - 1).min())

print(f"\n样本区间 {START} ~ {END}（{(spy.index[-1]-spy.index[0]).days/365.25:.1f} 年，{len(spy)} 根日线）")
print(f"基准 SPY 买入持有: CAGR {spy_cagr*100:.2f}%  最大回撤 {spy_mdd*100:.1f}%")
print(f"基准 QQQ 买入持有: CAGR {qqq_cagr*100:.2f}%  最大回撤 {qqq_mdd*100:.1f}%")
print("\n" + "=" * 118)
print(f"{'组合':<38}{'策略':<22}{'CAGR':>8}{'总收益':>10}{'夏普':>7}{'回撤':>8}{'胜率':>7}{'笔数':>7}")
print("=" * 118)
for bname, key, cagr, tot, sh, mdd, wr, n in rows:
    if cagr is None:
        print(f"{bname:<38}{key:<22}{'  ERR':>8}  {n}")
        continue
    print(f"{bname:<38}{key:<22}{cagr*100:>7.2f}%{tot*100:>9.1f}%{sh:>7.2f}{mdd*100:>7.1f}%{wr*100:>6.1f}%{n:>7}")
