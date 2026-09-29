"""杠杆到底能不能把收益推上去 —— 精确计算（含 IBKR 实际融资成本与波动率拖累）"""
import numpy as np

# 输入：系统实测的最优配置
mu_a   = 0.10      # 标的/策略的年化算术收益（实测 ~10%）
sigma  = 0.15      # 年化波动（实测 4 策略组合 7.3%，趋势类 ~15%）
rf     = 0.0538    # IBKR 美元首档保证金利率 5.38%（BM + 1.5%）
mdd_1x = -0.255    # 1x 时的最大回撤（实测 xs_momentum -25.5%）

print("="*100)
print("杠杆的精确效应：收益被放大，但同时被「融资成本」和「波动率拖累」吃掉")
print("="*100)
print(f"假设：标的算术收益 {mu_a*100:.1f}%、波动 {sigma*100:.0f}%、融资利率 {rf*100:.2f}%")
print()
print(f"{'杠杆':>5}{'毛收益':>10}{'融资成本':>11}{'算术收益':>11}{'波动':>9}{'波动率拖累':>12}{'几何收益':>11}{'预期回撤':>11}   评价")
best = (0, 0)
rows = []
for L in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0]:
    gross = L * mu_a
    fin   = max(L - 1.0, 0.0) * rf
    arith = gross - fin
    vol   = L * sigma
    drag  = vol**2 / 2.0
    geo   = arith - drag
    mdd   = mdd_1x * L
    if geo > best[0]:
        best = (geo, L)
    verdict = ("最优区" if abs(L - 2.0) < 0.01 else
               "还能接受" if geo > 0.085 else
               "得不偿失" if geo > 0.06 else
               "自我毁灭" if geo > 0.02 else "等于白干")
    rows.append((L, gross, fin, arith, vol, drag, geo, mdd, verdict))
    print(f"{L:>4.1f}x{gross*100:>9.1f}%{fin*100:>10.1f}%{arith*100:>10.1f}%{vol*100:>8.1f}%{drag*100:>11.1f}%{geo*100:>10.2f}%{mdd*100:>10.1f}%   {verdict}")

print()
print(f"  → 理论最优杠杆 = (μ − r_f) / σ² = ({mu_a:.3f} − {rf:.4f}) / {sigma**2:.4f} = {(mu_a-rf)/sigma**2:.2f}x")
print(f"  → 最优杠杆下的几何收益：{best[0]*100:.2f}%（1x 时是 {(mu_a - sigma**2/2)*100:.2f}%）")
print(f"  → 也就是说：加杠杆最多多赚 {(best[0]-(mu_a-sigma**2/2))*100:.2f} 个百分点/年，代价是回撤从 {mdd_1x*100:.1f}% 变成 {mdd_1x*best[1]*100:.1f}%")
print()
print("  5x 杠杆：几何收益 0.35%，预期回撤 -127%  →  数学上必然归零")

print()
print("="*100)
print("即使按最优杠杆 2x，到 1000%（10 倍）需要多久")
print("="*100)
for L in [1.0, 2.0, 3.0, 5.0]:
    geo = L*mu_a - max(L-1,0)*rf - (L*sigma)**2/2
    if geo > 0:
        yrs = np.log(10)/np.log(1+geo)
        print(f"  {L:.1f}x → 几何收益 {geo*100:>5.2f}%/年 → 到 10 倍需要 {yrs:>5.1f} 年   （预期回撤 {mdd_1x*L*100:>6.1f}%）")
    else:
        print(f"  {L:.1f}x → 几何收益 {geo*100:>5.2f}%/年 → 永远到不了，本金在缩水")
