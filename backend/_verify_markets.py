"""市场层验证（临时脚本）。"""
import sys, datetime as dt
sys.path.insert(0, ".")

from app.markets import calendar as cal, fees, fx, lots, symbols as sym, shortlist
from app.markets.registry import get_market, market_summary

fails = []

def ck(ok, label, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ← {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(label)

print("=" * 74)
print("A1 市场注册表")
print("=" * 74)
us, hk = get_market("US"), get_market("HK")
ck(us.currency == "USD" and hk.currency == "HKD", "币种正确", f"{us.currency}/{hk.currency}")
ck(us.timezone == "America/New_York" and hk.timezone == "Asia/Hong_Kong", "时区正确")
ck(len(hk.regular) == 2, "港股有两个常规时段（早盘/午盘）", str(hk.regular))
ck("IOC" not in hk.allowed_tif and "FOK" not in hk.allowed_tif, "港股不允许 IOC/FOK")
ck("IOC" in us.allowed_tif, "美股允许 IOC")
ck(hk.native_market_order is False and us.native_market_order is True, "港股无原生市价单")
ck(len(market_summary()) == 2, "market_summary 返回 2 个市场")

print()
print("=" * 74)
print("A2 交易日历")
print("=" * 74)
# 2026-07-03 美股独立日（7/4 周六提前）
ck(not cal.is_trading_day("US", dt.date(2026, 7, 3)), "美股 2026-07-03 休市（独立日提前）")
ck(not cal.is_trading_day("US", dt.date(2026, 1, 1)), "美股元旦休市")
ck(not cal.is_trading_day("US", dt.date(2026, 7, 4)), "美股 2026-07-04 周六休市")
ck(cal.is_trading_day("US", dt.date(2026, 9, 23)), "美股 2026-09-23 开市")
# 港股春节
ck(not cal.is_trading_day("HK", dt.date(2026, 2, 17)), "港股农历年初一休市")
ck(not cal.is_trading_day("HK", dt.date(2026, 2, 18)), "港股农历年初二休市")
ck(not cal.is_trading_day("HK", dt.date(2026, 2, 19)), "港股农历年初三休市")
ck(cal.is_trading_day("HK", dt.date(2026, 2, 20)), "港股年初四开市")
# 港股午休
lunch = get_market("HK").localize(dt.datetime(2026, 9, 23, 12, 30))
st = cal.market_status("HK", lunch)
ck(st.session == "closed" and "间歇" in st.reason, "港股 12:30 为午休（closed）", f"{st.session} / {st.reason}")
morning = get_market("HK").localize(dt.datetime(2026, 9, 23, 10, 30))
ck(cal.market_status("HK", morning).session == "regular", "港股 10:30 为早盘")
noon = get_market("HK").localize(dt.datetime(2026, 9, 23, 14, 30))
ck(cal.market_status("HK", noon).session == "regular", "港股 14:30 为午盘")
hk_close = get_market("HK").localize(dt.datetime(2026, 9, 23, 16, 30))
ck(cal.market_status("HK", hk_close).session == "closed", "港股 16:30 已收盘")
# 美股盘前
pre = get_market("US").localize(dt.datetime(2026, 9, 23, 7, 0))
ck(cal.market_status("US", pre).session == "extended", "美股 07:00 为盘前")
rth = get_market("US").localize(dt.datetime(2026, 9, 23, 11, 0))
ck(cal.market_status("US", rth).session == "regular", "美股 11:00 为盘中")
# 半日市
hd = get_market("US").localize(dt.datetime(2026, 11, 27, 14, 0))
st_hd = cal.market_status("US", hd)
ck(st_hd.is_half_day and st_hd.session == "closed", "美股 11/27 半日市 14:00 已收盘", f"{st_hd.session}")
hd2 = get_market("US").localize(dt.datetime(2026, 11, 27, 12, 0))
ck(cal.market_status("US", hd2).session == "regular", "美股 11/27 半日市 12:00 仍盘中")
hd_hk = get_market("HK").localize(dt.datetime(2026, 12, 24, 12, 30))
ck(cal.market_status("HK", hd_hk).session == "closed", "港股 12/24 平安夜 12:30 已收盘")
# 日历覆盖警告
ck(cal.market_status("HK", dt.datetime(2026, 9, 23, 10, 30, tzinfo=dt.timezone(dt.timedelta(hours=8)))).calendar_verified is False,
   "港股 2026 年未核对 → 产生警告")
ck(cal.market_status("US", dt.datetime(2026, 9, 23, 10, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))).calendar_verified is True,
   "美股 2026 年已核对")
cov = cal.coverage(dt.date(2026, 9, 23))
ck(len(cov) == 2 and cov[0]["holiday_count"] > 30, f"日历覆盖度：US {cov[0]['holiday_count']} 条 / HK {cov[1]['holiday_count']} 条")
# next_open
nxt = cal.next_open("HK", dt.datetime(2026, 9, 23, 17, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))
ck(nxt.date() == dt.date(2026, 9, 24) and nxt.hour == 9 and nxt.minute == 30, "港股收盘后 next_open = 次日 09:30", str(nxt))
# 春节连休后的 next_open
nxt2 = cal.next_open("HK", dt.datetime(2026, 2, 16, 17, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))
ck(nxt2.date() == dt.date(2026, 2, 20), "春节连休后 next_open = 年初四", str(nxt2))
# 交易日列表
days = cal.trading_days("HK", dt.date(2026, 2, 13), dt.date(2026, 2, 23))
ck(dt.date(2026, 2, 17) not in days and dt.date(2026, 2, 20) in days, "trading_days 正确跳过春节", str([d.isoformat() for d in days]))

print()
print("=" * 74)
print("A3 符号解析")
print("=" * 74)
cases = [
    ("AAPL", "US", "AAPL", "USD", "SMART"),
    ("aapl", "US", "AAPL", "USD", "SMART"),
    ("BRK-B", "US", "BRK B", "USD", "SMART"),
    ("SPY", "US", "SPY", "USD", "SMART"),
    ("0700.HK", "HK", "700", "HKD", "SEHK"),
    ("0700", "HK", "700", "HKD", "SEHK"),
    ("700", "HK", "700", "HKD", "SEHK"),
    ("00700.HK", "HK", "700", "HKD", "SEHK"),
    ("09988", "HK", "9988", "HKD", "SEHK"),
    ("0005.HK", "HK", "5", "HKD", "SEHK"),
    ("1810.HK", "HK", "1810", "HKD", "SEHK"),
]
for raw, mkt, ib, ccy, exch in cases:
    r = sym.parse(raw)
    ok = r.market == mkt and r.ib_symbol == ib and r.currency == ccy and r.exchange == exch
    ck(ok, f"解析 {raw!r} → {r.symbol} / ib={r.ib_symbol} / {r.currency} / {r.exchange}",
       f"期望 market={mkt} ib={ib} ccy={ccy} exch={exch}")
ck(sym.parse("0700.HK").symbol == "0700.HK", "港股规范展示码 0700.HK", sym.parse("0700.HK").symbol)
ck(sym.parse("09988").symbol == "9988.HK", "5 位港股规范码 9988.HK", sym.parse("09988").symbol)
ck(sym.parse("^HSI").market == "HK" and sym.parse("^HSI").exchange == "HKFE", "恒指解析为港股指数")
ck(sym.parse("^GSPC").market == "US" and sym.parse("^GSPC").ib_symbol == "SPX", "标普解析为 SPX")
ck(sym.market_of("0700.HK") == "HK" and sym.market_of("AAPL") == "US", "market_of 快捷判定")
g = sym.group_by_market(["AAPL", "0700.HK", "MSFT", "9988.HK"])
ck(set(g) == {"US", "HK"} and len(g["HK"]) == 2, "按市场分组正确", str({k: [x.symbol for x in v] for k, v in g.items()}))

print()
print("=" * 74)
print("A5 手数与最小变动")
print("=" * 74)
q, lot, note = lots.round_qty("0700.HK", 150)
ck(q == 100 and lot == 100, "腾讯 150 股 → 100 股（1 手）", f"{q}/{lot}")
q2, _, _ = lots.round_qty("0700.HK", 250)
ck(q2 == 200, "腾讯 250 股 → 200 股", str(q2))
q3, lot3, _ = lots.round_qty("0005.HK", 1000)
ck(q3 == 800 and lot3 == 400, "汇丰每手 400 → 1000 股取整为 800", f"{q3}/{lot3}")
q4, _, _ = lots.round_qty("AAPL", 10.7)
ck(q4 == 10.0, "美股取整为整数股", str(q4))
q5, _, n5 = lots.round_qty("0200.HK", 150)  # 未收录标的
ck(q5 == 100 and "默认值" in n5, "未收录港股用默认 100 并提示核对", n5)
q6, _, n6 = lots.round_qty("0700.HK", 50)
ck(q6 == 0.0 and "不足 1 手" in n6, "不足 1 手 → 0", n6)
ck(lots.tick_size("0700.HK", 300) == 0.2, f"港股 300 元档价差 0.2（实际 {lots.tick_size('0700.HK', 300)}）")
ck(lots.tick_size("0700.HK", 5) == 0.01, f"港股 5 元档价差 0.01（实际 {lots.tick_size('0700.HK', 5)}）")
ck(lots.tick_size("AAPL", 200) == 0.01, "美股 ≥$1 价差 0.01")
ck(lots.tick_size("AAPL", 0.5) == 0.0001, "美股 <$1 价差 0.0001")
ck(lots.round_price("0700.HK", 300.17, side="BUY") == 300.0, f"买单向下取整（{lots.round_price('0700.HK', 300.17)}）")
ck(lots.round_price("0700.HK", 300.17, side="SELL") == 300.2, f"卖单向上取整（{lots.round_price('0700.HK', 300.17)}）")

print()
print("=" * 74)
print("A6 分项费用")
print("=" * 74)
hk_fee = fees.estimate("0700.HK", "BUY", 100, 300.0)
print(f"  港股买 100 股 @300（成交额 {hk_fee.notional:,.0f} HKD）：")
for it in hk_fee.items:
    print(f"    {it.name:<12} {it.amount:>8.2f}  {it.note}")
print(f"    {'合计':<12} {hk_fee.total:>8.2f} HKD  = {hk_fee.bps:.2f} bps")
ck(abs(hk_fee.total - 37.66) < 3.0, f"港股总费用约 37.7 HKD（实际 {hk_fee.total:.2f}）")
duty = next(i for i in hk_fee.items if i.name == "印花税")
ck(duty.amount == 30.0, f"印花税 = 30.00（成交额 0.1%，进位到元）实际 {duty.amount}")
ck(hk_fee.bps > 8, f"港股单边费用 > 8 bps（实际 {hk_fee.bps:.2f}）")

us_fee = fees.estimate("AAPL", "BUY", 100, 200.0)
print(f"\n  美股买 100 股 @200（成交额 {us_fee.notional:,.0f} USD）：")
for it in us_fee.items:
    print(f"    {it.name:<12} {it.amount:>8.2f}  {it.note}")
print(f"    {'合计':<12} {us_fee.total:>8.2f} USD  = {us_fee.bps:.2f} bps")
ck(us_fee.total < hk_fee.total / 5, f"美股买入成本远低于港股（{us_fee.total:.2f} vs {hk_fee.total:.2f}）")

us_sell = fees.estimate("AAPL", "SELL", 100, 200.0)
sec = next(i for i in us_sell.items if i.name == "SEC 交易费")
taf = next(i for i in us_sell.items if i.name == "FINRA TAF")
ck(sec.amount > 0 and taf.amount > 0, f"美股卖出含 SEC({sec.amount:.4f}) 与 TAF({taf.amount:.4f})")
ck(abs(sec.amount - 20000 * 27.80e-6) < 1e-6, "SEC 费按成交额计算")
ck(abs(taf.amount - 100 * 0.000166) < 1e-9, "TAF 按股数计算")

hk_big = fees.estimate("0700.HK", "SELL", 100_000, 300.0)  # 大额，CCASS 触上限
cc = next(i for i in hk_big.items if i.name == "CCASS 结算费")
ck(cc.amount == 100.0, f"CCASS 触上限 100（实际 {cc.amount}）")

hk_small = fees.estimate("0700.HK", "BUY", 100, 1.0)  # 小额，CCASS 触下限
cc2 = next(i for i in hk_small.items if i.name == "CCASS 结算费")
ck(cc2.amount == 2.0, f"CCASS 触下限 2（实际 {cc2.amount}）")

rt_hk = fees.round_trip_bps("0700.HK", 300.0)
rt_us = fees.round_trip_bps("SPY", 500.0)
print(f"\n  往返成本：港股 {rt_hk:.2f} bps ｜ 美股 {rt_us:.2f} bps ｜ 倍数 {rt_hk/max(rt_us,0.01):.1f}x")
ck(rt_hk > rt_us * 5, "港股往返成本显著高于美股")
ck(len(fees.schedule_summary()) == 2, "费率表可输出")

print()
print("=" * 74)
print("A7 汇率")
print("=" * 74)
r = fx.get_rate("USD", "HKD")
print(f"  USD/HKD = {r.rate:.4f}（来源 {r.source}, estimated={r.estimated}）")
ck(r.rate > 7.0 and r.rate < 8.5, "USD/HKD 在联系汇率区间", str(r.rate))
ck(fx.get_rate("HKD", "HKD").rate == 1.0, "同币种恒为 1")
ck(fx.convert(1000, "USD", "USD")[0] == 1000, "USD→USD 恒等")
v, est = fx.convert(7800, "HKD", "USD")
ck(abs(v - 1000) < 60, f"7800 HKD ≈ 1000 USD（实际 {v:.2f}）")
ck(fx.symbol_currency("0700.HK") == "HKD" and fx.symbol_currency("AAPL") == "USD", "symbol_currency 正确")
snap = fx.rates_snapshot()
ck(snap["base"] == "USD" and len(snap["rates"]) >= 1, "汇率快照可输出")

print()
print("=" * 74)
print("A8 做空")
print("=" * 74)
ck(shortlist.is_shortable("0700.HK").allowed, "腾讯可做空")
ck(not shortlist.is_shortable("0200.HK").allowed, "未收录港股默认拒绝做空")
ck(shortlist.is_shortable("AAPL").allowed, "美股默认允许做空（需券商确认券源）")
ck(not shortlist.is_shortable("^HSI").allowed, "指数不可直接做空")
s = shortlist.summary()
ck(s["hk_count"] > 80, f"港股可做空名单 {s['hk_count']} 只")

print()
print("=" * 74)
print(f"结果：{'全部通过 ✓' if not fails else f'{len(fails)} 项失败: ' + ', '.join(fails)}")
print("=" * 74)
sys.exit(1 if fails else 0)
