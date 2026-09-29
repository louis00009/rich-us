"""补充对照：基准 Sharpe、等权买入持有、多策略组合、不同仓位上限。"""
from __future__ import annotations
import sys, pathlib, warnings
warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np, pandas as pd
from app.engine import backtest as bt
from app.engine.metrics import compute_metrics

CACHE = ROOT / "backend" / "runtime" / "cache" / "1d"

def _read(sym, start, end, interval):
    p = CACHE / f"{sym}.csv"
    if not p.exists(): return None
    df = pd.read_csv(p); df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]); df = df.set_index("date").sort_index()
    return df[["open","high","low","close","volume"]].astype(float)

def fm(symbols, start, end, interval="1d", prefer=None):
    o, s = {}, {}
    for x in symbols:
        d = _read(x, start, end, interval)
        if d is not None and len(d): o[x] = d; s[x] = "cache"
    return o, s

def fh(symbol, start, end, interval="1d", prefer=None):
    d = _read(symbol, start, end, interval)
    return (d if d is not None else pd.DataFrame()), "cache"

bt.fetch_many = fm; bt.fetch_history = fh
START, END = "2019-01-01", "2026-09-25"
BASKET = ["SPY","QQQ","IWM","EFA","EEM","TLT","GLD"]

def stats(eq):
    m = compute_metrics(eq, [], float(eq.iloc[0]), periods_per_year=252.0)
    return m["cagr"], m["sharpe"], m["max_drawdown"], m["volatility"]

print("="*100)
print("【基准】买入持有（同期 2019-01 ~ 2026-09，7.7 年）")
print("="*100)
for sym, name in [("SPY","标普500"), ("QQQ","纳斯达克100"), ("TLT","长债"), ("GLD","黄金")]:
    d = _read(sym, START, END, "1d")["close"]
    c, s, mdd, v = stats(d)
    print(f"  {name:<12}({sym:<4}) CAGR {c*100:6.2f}%   夏普 {s:5.2f}   最大回撤 {mdd*100:6.1f}%   波动 {v*100:5.1f}%")

# 等权月度再平衡的 7 资产组合（"什么都不做"的分散化基线）
px = pd.DataFrame({s: _read(s, START, END, "1d")["close"] for s in BASKET}).dropna()
ret = px.pct_change().fillna(0)
w = pd.Series(1/len(BASKET), index=BASKET)
eq = (1 + (ret * w).sum(axis=1)).cumprod() * 100_000
c, s, mdd, v = stats(eq)
print(f"  {'等权7资产':<10}{'(月度再平衡)':<6} CAGR {c*100:6.2f}%   夏普 {s:5.2f}   最大回撤 {mdd*100:6.1f}%   波动 {v*100:5.1f}%")

# 60/40
w2 = pd.Series({"SPY":0.6,"TLT":0.4})
eq2 = (1 + (ret[["SPY","TLT"]] * w2).sum(axis=1)).cumprod() * 100_000
c, s, mdd, v = stats(eq2)
print(f"  {'60/40':<10}{'SPY+TLT':<10} CAGR {c*100:6.2f}%   夏普 {s:5.2f}   最大回撤 {mdd*100:6.1f}%   波动 {v*100:5.1f}%")

# ---- 策略在不同仓位上限下的表现 ----
def run(key, basket, maxpos, gross=100.0, sizing="weight", stop="atr_trailing", sv=3.0):
    sp = bt.BacktestSpec(strategy_key=key, symbols=basket, start=START, end=END, interval="1d",
        initial_capital=100_000.0, commission_bps=1.0, slippage_bps=2.0, benchmark="SPY",
        sizing_method=sizing, max_position_pct=maxpos, gross_pct=gross, data_source="cache")
    sp.stop.stop_type = stop; sp.stop.stop_value = sv
    r = bt.run_backtest(sp)
    return r

print()
print("="*100)
print("【仓位上限敏感性】多资产7只 + 不同单标的上限（gross 100%）")
print("="*100)
print(f"{'策略':<22}{'上限20%(默认)':>16}{'上限35%':>14}{'上限50%':>14}{'等权sizing 20%':>18}")
for key in ["dual_ma_trend","xs_momentum","donchian_breakout","trend_composite","dual_momentum","ensemble_vote"]:
    cells = []
    for mp in (20.0, 35.0, 50.0):
        r = run(key, BASKET, mp)
        m = r["metrics"] if r.get("ok") else None
        cells.append(f"{m['cagr']*100:5.2f}%/S{m['sharpe']:.2f}" if m else "ERR")
    r = run(key, BASKET, 20.0, sizing="equal_weight")
    m = r["metrics"] if r.get("ok") else None
    cells.append(f"{m['cagr']*100:5.2f}%/S{m['sharpe']:.2f}" if m else "ERR")
    print(f"{key:<22}{cells[0]:>16}{cells[1]:>14}{cells[2]:>14}{cells[3]:>18}")

# ---- 多策略组合（4 个正期望策略等权拼）----
print()
print("="*100)
print("【多策略组合】4 个正期望策略各 25% 资金，净值曲线相加（不是叠加杠杆）")
print("="*100)
picks = ["dual_ma_trend","xs_momentum","donchian_breakout","connors_rsi2"]
curves = []
for k in picks:
    r = run(k, BASKET, 20.0)
    if r.get("ok"):
        eqs = pd.Series({pd.Timestamp(p["date"]): p["equity"] for p in r["curve"]})
        curves.append(eqs / eqs.iloc[0])
    print(f"   {k:<22} CAGR {r['metrics']['cagr']*100:6.2f}%  夏普 {r['metrics']['sharpe']:.2f}  回撤 {r['metrics']['max_drawdown']*100:6.1f}%")
comb = pd.concat(curves, axis=1).ffill().dropna()
port = comb.mean(axis=1) * 100_000
c, s, mdd, v = stats(port)
print(f"   {'组合(等权4策略)':<22} CAGR {c*100:6.2f}%  夏普 {s:.2f}  回撤 {mdd*100:6.1f}%  波动 {v*100:.1f}%")

# ---- 成本敏感性：滑点放大 ----
print()
print("="*100)
print("【成本敏感性】dual_ma_trend 多资产7只，滑点从 2bp 升到 10bp")
print("="*100)
for slip in (2.0, 5.0, 10.0):
    sp = bt.BacktestSpec(strategy_key="dual_ma_trend", symbols=BASKET, start=START, end=END,
        interval="1d", initial_capital=100_000.0, commission_bps=1.0, slippage_bps=slip,
        benchmark="SPY", sizing_method="weight", max_position_pct=20.0, gross_pct=100.0, data_source="cache")
    sp.stop.stop_type="atr_trailing"; sp.stop.stop_value=3.0
    r = bt.run_backtest(sp); m = r["metrics"]
    print(f"   滑点 {slip:>4.1f}bp → CAGR {m['cagr']*100:6.2f}%  夏普 {m['sharpe']:.2f}  换手 {m['turnover']:.1f}x  交易 {m['trades']} 笔")
