"""回答「能不能做到 1000%」：
   (A) 1000% 需要多少年化 —— 拆解时间尺度
   (B) 在系统里暴力搜索最高收益配置（样本内）
   (C) 把样本内最优拿到样本外验证 —— 证明「调参凑收益」会崩
"""
from __future__ import annotations
import sys, pathlib, warnings, itertools, json
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

# ============ (A) 1000% 需要多少年化 ============
print("="*100)
print("【A】「1000%（10 倍）」在不同时间尺度下需要多少年化")
print("="*100)
print(f"{'时间':>10}{'所需年化':>12}   这个水平现实吗")
for yrs, label in [(1,"1 年"),(3,"3 年"),(5,"5 年"),(7.7,"7.7 年(本样本)"),(10,"10 年"),(15,"15 年"),(20,"20 年"),(30,"30 年")]:
    r = 10**(1/yrs)-1
    if r > 1.0:   verdict = "不可能（全球无人能稳定做到）"
    elif r > 0.5: verdict = "极高风险区（靠集中+杠杆+运气）"
    elif r > 0.25:verdict = "顶级水平（文艺复兴量级）"
    elif r > 0.15:verdict = "优秀（远超指数长期均值）"
    elif r > 0.09:verdict = "良好（略高于 SPY 长期均值 ~10%）"
    else:         verdict = "完全现实（SPY 长期均值即可）"
    print(f"{label:>10}{r*100:>11.1f}%   {verdict}")

# ============ 准备数据 ============
FULL = ["SPY","QQQ","IWM","EFA","EEM","GLD","XLP","XLU","VNQ","AGG"]
IS_S, IS_E = "2019-01-01", "2023-06-30"
OOS_S, OOS_E = "2023-07-01", "2026-09-25"

def run(basket, key, maxpos, gross, sizing, stop_type, stop_val, start, end):
    sp = bt.BacktestSpec(strategy_key=key, symbols=basket, start=start, end=end, interval="1d",
        initial_capital=100_000.0, commission_bps=1.0, slippage_bps=2.0, benchmark="SPY",
        sizing_method=sizing, max_position_pct=maxpos, gross_pct=gross, data_source="cache")
    sp.stop.stop_type = stop_type
    sp.stop.stop_value = stop_val
    try:
        r = bt.run_backtest(sp)
        return r if r.get("ok") else None
    except Exception:
        return None

# ============ (B) 样本内暴力搜索 ============
print()
print("="*100)
print(f"【B】样本内暴力搜索最高收益（{IS_S} ~ {IS_E}，10 只 ETF）")
print("="*100)
GRID = {
    "strategy_key": ["dual_ma_trend","xs_momentum","donchian_breakout","dual_momentum",
                     "trend_composite","ensemble_vote","vol_managed_momentum","regime_adaptive"],
    "maxpos": [20.0, 50.0],
    "gross": [100.0],
    "sizing": ["weight", "equal_weight"],
    "stop": [("atr_trailing", 3.0), ("none", 0.0)],
}
combos = list(itertools.product(*[GRID[k] for k in GRID]))
print(f"组合数：{len(combos)}，每个跑 2 段（样本内 + 样本外）\n")

rows = []
for i, (key, mp, gp, sz, st) in enumerate(combos, 1):
    r_is = run(FULL, key, mp, gp, sz, st[0], st[1], IS_S, IS_E)
    if not r_is: continue
    m = r_is["metrics"]
    rows.append({
        "key": key, "mp": mp, "sz": sz, "stop": st[0],
        "is_cagr": m["cagr"], "is_tot": m["total_return"], "is_dd": m["max_drawdown"],
        "is_sharpe": m["sharpe"], "is_calmar": m["calmar"],
    })
    if i % 8 == 0:
        print(f"  ... 已评估 {i}/{len(combos)}", flush=True)

df = pd.DataFrame(rows)
print(f"\n样本内最优 10 个（按年化排序）：")
print(f"{'策略':<22}{'上限':>6}{'仓位算法':>12}{'止损':>14}{'样本内年化':>11}{'样本内总收益':>13}{'回撤':>9}{'夏普':>7}")
top = df.sort_values("is_cagr", ascending=False).head(10)
for _, x in top.iterrows():
    print(f"{x['key']:<22}{x['mp']:>5.0f}%{x['sz']:>12}{x['stop']:>14}{x['is_cagr']*100:>10.2f}%{x['is_tot']*100:>12.1f}%{x['is_dd']*100:>8.1f}%{x['is_sharpe']:>7.2f}")

# ============ (C) 样本外验证 ============
print()
print("="*100)
print(f"【C】把样本内最优拿到「没见过的」样本外验证（{OOS_S} ~ {OOS_E}）")
print("="*100)
print(f"{'策略':<22}{'上限':>6}{'仓位算法':>12}{'止损':>14}{'样本内年化':>11}{'样本外年化':>11}{'样本外回撤':>11}{'落差':>10}")
oos = []
for _, x in top.iterrows():
    r = run(FULL, x["key"], x["mp"], x["gross"] if "gross" in x else 100.0, x["sz"], x["stop"], 3.0 if x["stop"]=="atr_trailing" else 0.0, OOS_S, OOS_E)
    if not r:
        print(f"{x['key']:<22}{x['mp']:>5.0f}%{x['sz']:>12}{x['stop']:>14}{x['is_cagr']*100:>10.2f}%{'  ERR':>11}")
        continue
    mo = r["metrics"]
    gap = mo["cagr"] - x["is_cagr"]
    oos.append((x["key"], x["mp"], x["sz"], x["stop"], x["is_cagr"], mo["cagr"], mo["max_drawdown"], gap))
    print(f"{x['key']:<22}{x['mp']:>5.0f}%{x['sz']:>12}{x['stop']:>14}{x['is_cagr']*100:>10.2f}%{mo['cagr']*100:>10.2f}%{mo['max_drawdown']*100:>10.1f}%{gap*100:>+9.2f}%")

if oos:
    arr = np.array([o[7] for o in oos])
    print(f"\n  → 样本内最优 10 个，样本外年化的平均落差：{arr.mean()*100:+.2f} 个百分点")
    print(f"  → 其中 {int((arr<0).sum())}/{len(arr)} 个在样本外变差")
    is_med = np.median([o[4] for o in oos]); oos_med = np.median([o[5] for o in oos])
    print(f"  → 中位数：样本内 {is_med*100:.2f}%  →  样本外 {oos_med*100:.2f}%")

# ============ (D) 1000% 需要什么条件 ============
print()
print("="*100)
print("【D】要在这套系统里摸到 1000%，数学上需要什么")
print("="*100)
best_is = df["is_cagr"].max()
print(f"  样本内最高年化（全组合搜索）：{best_is*100:.2f}%")
print(f"  → 该水平下达到 1000%（10 倍）需要：{np.log(10)/np.log(1+best_is):.1f} 年")
print(f"  → 要达到 7.7 年 1000%，需要年化 34.5%")
print(f"  → 缺口：{(0.345-best_is)*100:.1f} 个百分点/年")
print()
print("  补上缺口的唯一手段（及其代价）：")
print(f"    ① 杠杆 3x：{best_is*100:.1f}% → {best_is*3*100:.1f}%，但回撤同步 ×3")
print(f"    ② 换高波动标的：样本仅 1~2 年，无法验证，实测近 1 年多为负")
print(f"    ③ 期权凸性：平台未实现（T-133），且期权买方长期为负期望")
print(f"    ④ 更长时间：年化 8% 跑 30 年也能到 10 倍 —— 唯一无代价的路径")
