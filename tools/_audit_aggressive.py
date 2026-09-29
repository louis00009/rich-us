"""修正版激进测试：严格标注样本周期，并把「几百个点」拆成总收益 vs 年化两件事。"""
from __future__ import annotations
import sys, pathlib, warnings
warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np, pandas as pd
from app.engine import backtest as bt

CACHE = ROOT / "backend" / "runtime" / "cache" / "1d"

def _read(sym, start, end, interval):
    p = CACHE / f"{sym}.csv"
    if not p.exists(): return None
    df = pd.read_csv(p); df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"]); df = df.set_index("date").sort_index()
    df = df[["open","high","low","close","volume"]].astype(float)
    df = df[df.index >= pd.Timestamp(start)]
    if end: df = df[df.index <= pd.Timestamp(end)]
    return df if len(df) else None

def fm(symbols, start, end, interval="1d", prefer=None):
    o, s = {}, {}
    for x in symbols:
        d = _read(x, start, end, interval)
        if d is not None: o[x] = d; s[x] = "cache"
    return o, s

def fh(symbol, start, end, interval="1d", prefer=None):
    d = _read(symbol, start, end, interval)
    return (d if d is not None else pd.DataFrame()), "cache"

bt.fetch_many = fm; bt.fetch_history = fh

def bh(syms, start, end):
    px = pd.DataFrame({s: _read(s, start, end, "1d")["close"] for s in syms})
    px = px.dropna(how="all").ffill().dropna()
    eq = px.mean(axis=1)
    yrs = (eq.index[-1]-eq.index[0]).days/365.25
    return (eq.iloc[-1]/eq.iloc[0]-1), (eq.iloc[-1]/eq.iloc[0])**(1/yrs)-1, float((eq/eq.cummax()-1).min()), len(eq)

# ================= 第一部分：几百个点到底能不能达到 =================
print("="*106)
print("【1】「几百个点」拆开看：总收益 vs 年化 —— 同一个数字，两种完全不同的含义")
print("="*106)
FULL = ["SPY","QQQ","IWM","EFA","EEM","GLD","XLP","XLU","VNQ","AGG"]
for s in ["SPY","QQQ"]:
    px = _read(s, "2019-01-01", "2026-09-25", "1d")["close"]
    yrs = (px.index[-1]-px.index[0]).days/365.25
    tot = px.iloc[-1]/px.iloc[0]-1
    print(f"  买入持有 {s:<4}（{yrs:.1f} 年，零策略、零 AI、零操作）"
          f"  总收益 {tot*100:>7.1f}%   年化 {((1+tot)**(1/yrs)-1)*100:>6.2f}%   最大回撤 {float((px/px.cummax()-1).min())*100:>6.1f}%")
t,c,m,n = bh(FULL, "2019-01-01", "2026-09-25")
print(f"  买入持有 10 只 ETF 等权（7.7 年）                总收益 {t*100:>7.1f}%   年化 {c*100:>6.2f}%   最大回撤 {m*100:>6.1f}%")

print()
print("="*106)
print("【2】把仓位上限/总敞口全部放开，策略库的收益天花板（7.7 年完整样本，10 只 ETF）")
print("="*106)
print(f"{'策略':<22}{'仓位/敞口':>12}{'年化':>9}{'总收益':>11}{'夏普':>7}{'回撤':>9}")
def run(basket, key, maxpos, gross, start="2019-01-01", end="2026-09-25"):
    sp = bt.BacktestSpec(strategy_key=key, symbols=basket, start=start, end=end, interval="1d",
        initial_capital=100_000.0, commission_bps=1.0, slippage_bps=2.0, benchmark="SPY",
        sizing_method="weight", max_position_pct=maxpos, gross_pct=gross, data_source="cache")
    sp.stop.stop_type="atr_trailing"; sp.stop.stop_value=3.0
    try: return bt.run_backtest(sp)
    except Exception as e: return {"ok": False, "error": str(e)}

best = []
for key in ["dual_ma_trend","xs_momentum","donchian_breakout","dual_momentum","trend_composite","ensemble_vote"]:
    for mp, gp in [(20.0,100.0), (50.0,100.0), (100.0,100.0), (100.0,150.0)]:
        r = run(FULL, key, mp, gp)
        if not r.get("ok"): continue
        m = r["metrics"]
        best.append((m["total_return"], key, mp, gp, m))
        print(f"{key:<22}{f'{mp:.0f}%/{gp:.0f}%':>12}{m['cagr']*100:>8.2f}%{m['total_return']*100:>10.1f}%{m['sharpe']:>7.2f}{m['max_drawdown']*100:>8.1f}%")
best.sort(reverse=True)
print(f"\n  → 放开到极限后的最优：{best[0][1]}（{best[0][2]:.0f}%/{best[0][3]:.0f}%）"
      f" 总收益 {best[0][4]['total_return']*100:.1f}%  年化 {best[0][4]['cagr']*100:.2f}%  回撤 {best[0][4]['max_drawdown']*100:.1f}%")

# ================= 第二部分：短线窗口的高波动赌博 =================
print()
print("="*106)
print("【3】如果去赌高波动个股（样本仅 2025-08-22 ~ 2026-09-25，约 1.1 年，275 根）")
print("="*106)
HOT = ["MSTR","COIN","PLTR","SMCI","IONQ","OKLO","ARM","HOOD","SOFI","RDDT"]
HOT = [s for s in HOT if _read(s, "2025-08-22", "2026-09-25", "1d") is not None]
t,c,m,n = bh(HOT, "2025-08-22", "2026-09-25")
print(f"  {'买入持有等权 '+str(len(HOT))+' 只':<24} 总收益 {t*100:>7.1f}%   年化 {c*100:>6.2f}%   最大回撤 {m*100:>6.1f}%   ({n} 根)")
print(f"{'策略':<24}{'仓位/敞口':>12}{'年化':>9}{'总收益':>11}{'夏普':>7}{'回撤':>9}")
for key in ["dual_ma_trend","xs_momentum","donchian_breakout","supertrend"]:
    for mp, gp in [(20.0,100.0), (100.0,100.0)]:
        r = run(HOT, key, mp, gp, start="2025-08-22", end="2026-09-25")
        if not r.get("ok"): continue
        m2 = r["metrics"]
        print(f"{key:<24}{f'{mp:.0f}%/{gp:.0f}%':>12}{m2['cagr']*100:>8.2f}%{m2['total_return']*100:>10.1f}%{m2['sharpe']:>7.2f}{m2['max_drawdown']*100:>8.1f}%")

# ================= 第三部分：杠杆与复利 =================
print()
print("="*106)
print("【4】杠杆的数学：把 6.94%/年化（波动 7.3%）放大 N 倍会发生什么")
print("="*106)
base_r, base_v, base_dd = 0.0694, 0.073, -0.123
print(f"{'杠杆':>5}{'年化收益':>11}{'年化波动':>11}{'预期最大回撤':>13}{'3年内腰斩概率':>15}   判定")
for L in (1,2,3,5,10,20):
    r_, v_, dd_ = base_r*L, base_v*L, base_dd*L
    if v_ > 0:
        expo = 2*r_*np.log(0.5)/(v_**2)
        p = min(1.0, float(np.exp(expo))) if expo < 0 else 1.0
    else:
        p = 0.0
    verdict = "安全" if dd_ > -0.35 else ("危险" if dd_ > -1.0 else "数学上必然归零")
    print(f"{L:>4}x{r_*100:>10.1f}%{v_*100:>10.1f}%{dd_*100:>12.1f}%{p*100:>14.1f}%   {verdict}")

print()
print("="*106)
print("【5】如果真能稳定跑出「每年几百个点」")
print("="*106)
for rate, label in [(0.20,"巴菲特 60 年的水平"), (0.39,"文艺复兴 Medallion（人类最佳）"),
                    (1.00,"一年翻倍"), (2.00,"一年三倍"), (3.00,"一年四倍")]:
    print(f"  年化 {label:<24} $25,000 起步 →  5年 {((1+rate)**5):>18,.0f}x   10年 {((1+rate)**10):>22,.0f}x   20年 {((1+rate)**20):>26,.0f}x")
print()
print(f"  $25,000 × 4^20 = ${25000*4**20:,.0f}  ← 一年四倍持续 20 年")
print(f"  作为对照，伯克希尔哈撒韦当前市值约 $1.1 万亿")
