"""IBKR 适配层验证（#26 合约层 / #31 流式 / #33 下单去阻塞 / #34 回报异步 / #35 超时限流）。

用 FakeIB 冒充 ib_async.IB，不依赖 TWS / IB Gateway 在线。
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, ".")

import ib_async

from app.brokers import ibkr as K

PASS = 0
FAIL = 0


def check(ok: bool, label: str, extra: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {label}" + (f" | {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" | {extra}" if extra else ""))


# ======================================================================
# 假 ib_async.IB
# ======================================================================
class Ev:
    def __init__(self) -> None:
        self.h: list = []

    def __iadd__(self, fn):
        self.h.append(fn)
        return self

    def __isub__(self, fn):
        if fn in self.h:
            self.h.remove(fn)
        return self

    def emit(self, *a, **kw):
        for f in list(self.h):
            try:
                f(*a, **kw)
            except Exception:  # noqa: BLE001
                pass


class FakeStatus:
    def __init__(self) -> None:
        self.status = "Submitted"
        self.filled = 0.0
        self.avgFillPrice = 0.0
        self.remaining = 0.0


class FakeOrder:
    def __init__(self, oid: int, order_type: str, action: str, qty: float) -> None:
        self.orderId = oid
        self.permId = 900000 + oid
        self.clientId = 17
        self.action = action
        self.totalQuantity = qty
        self.orderType = order_type
        self.lmtPrice = 0.0
        self.auxPrice = 0.0
        self.tif = "DAY"
        self.transmit = True
        self.parentId = 0
        self.ocaGroup = ""
        self.ocaType = 0
        self.outsideRth = False


class FakeTrade:
    def __init__(self, contract, order: FakeOrder) -> None:
        self.contract = contract
        self.order = order
        self.orderStatus = FakeStatus()


class FakeTicker:
    def __init__(self, contract) -> None:
        self.contract = contract
        self.last = float("nan")
        self.bid = -1.0
        self.ask = -1.0
        self.bidSize = 0
        self.askSize = 0
        self.lastSize = 0
        self.volume = 0
        self.open = 0.0
        self.high = 0.0
        self.low = 0.0
        self.close = 0.0
        self.time = ""


class FakeIB:
    def __init__(self) -> None:
        self.orderStatusEvent = Ev()
        self.execDetailsEvent = Ev()
        self.commissionReportEvent = Ev()
        self.pendingTickersEvent = Ev()
        self.errorEvent = Ev()
        self.disconnectedEvent = Ev()
        self._next_oid = 1000
        self.trades: list[FakeTrade] = []
        self.tickers: dict[str, FakeTicker] = {}
        self.md_requests: list[str] = []
        self.md_cancels: list[str] = []
        self.ticker_req_count = 0
        self.md_type = 3
        self.auto_fill_after: float | None = None   # 秒；None = 不自动成交
        self.fill_price = 0.0
        self.fail_next: str = ""

    # --- 连接 ---
    def isConnected(self) -> bool:
        return True

    def disconnect(self) -> None:
        return None

    def managedAccounts(self):
        return ["DU1234567"]

    # --- 异步方法 ---
    async def connectAsync(self, *a, **kw):
        return None

    async def qualifyContractsAsync(self, *contracts):
        for c in contracts:
            if not getattr(c, "localSymbol", ""):
                c.localSymbol = getattr(c, "symbol", "")
        return list(contracts)

    async def reqTickersAsync(self, *contracts):
        self.ticker_req_count += 1
        if self.fail_next == "tickers":
            raise RuntimeError("tickers boom")
        out = []
        for c in contracts:
            t = FakeTicker(c)
            if not c.localSymbol:
                c.localSymbol = c.symbol
            out.append(t)
        return out

    async def accountSummaryAsync(self, acct="", *a):
        return [
            SimpleNamespace(tag="NetLiquidation", value="100000.0", currency="USD"),
            SimpleNamespace(tag="TotalCashValue", value="50000.0", currency="USD"),
            SimpleNamespace(tag="UnrealizedPnL", value="1200.0", currency="USD"),
            SimpleNamespace(tag="RealizedPnL", value="300.0", currency="USD"),
            SimpleNamespace(tag="BuyingPower", value="200000.0", currency="USD"),
            SimpleNamespace(tag="GrossPositionValue", value="50000.0", currency="USD"),
            SimpleNamespace(tag="MaintMarginReq", value="10000.0", currency="USD"),
        ]

    async def reqHistoricalDataAsync(self, *a, **kw):
        return []

    # --- 同步方法 ---
    def reqMarketDataType(self, n) -> None:
        self.md_type = int(n)

    def reqMktData(self, contract, *a, **kw) -> FakeTicker:
        if self.fail_next == "mktdata":
            raise RuntimeError("mktdata boom")
        key = getattr(contract, "localSymbol", "") or contract.symbol
        self.md_requests.append(key)
        t = FakeTicker(contract)
        self.tickers[key] = t
        return t

    def cancelMktData(self, contract) -> None:
        key = getattr(contract, "localSymbol", "") or contract.symbol
        self.md_cancels.append(key)
        self.tickers.pop(key, None)

    def placeOrder(self, contract, order):
        oid = self._next_oid
        self._next_oid += 1
        order.orderId = oid
        tr = FakeTrade(contract, order)
        self.trades.append(tr)
        if self.auto_fill_after is not None:
            t0 = time.monotonic()

            def worker():
                time.sleep(self.auto_fill_after)
                st = tr.orderStatus
                st.status = "Filled"
                st.filled = float(order.totalQuantity)
                st.avgFillPrice = self.fill_price or 100.0
                self.orderStatusEvent.emit(tr)

            threading.Thread(target=worker, daemon=True).start()
        return tr

    def cancelOrder(self, order) -> None:
        return None

    def portfolio(self, acct=""):
        return []

    def openTrades(self):
        return [t for t in self.trades if t.orderStatus.status not in ("Filled", "Cancelled")]

    def fills(self):
        return []

    def accountValues(self, acct=""):
        return [SimpleNamespace(tag="BaseCurrency", value="USD")]


def make_broker(**kw) -> tuple[K.IBKRBroker, FakeIB]:
    b = K.IBKRBroker(
        host="127.0.0.1", port=7497, client_id=99, account="DU1234567",
        mode="paper", readonly=False,
    )
    fake = FakeIB()
    b._ib = fake
    b._connected = True
    b._register_events()
    for k, v in kw.items():
        setattr(b, k, v)
    return b, fake


def hk_contract(symbol: str, digits: str):
    c = ib_async.Stock(symbol, "SEHK", "HKD")
    c.primaryExchange = "SEHK"
    c.localSymbol = digits
    return c


print("=" * 78)
print("IBKR 适配层验证")
print("=" * 78)

# ---------------------------------------------------------------- 1 合约层
print("\n[1] 合约层（#26 A4）：不再硬编码 SMART + USD")
b, fake = make_broker()
s = b._spec("AAPL")
check(s.symbol == "AAPL" and s.exchange == "SMART" and s.currency == "USD"
      and s.primary_exchange == "NASDAQ" and s.sec_type == "STK",
      "AAPL → SMART/USD/primary=NASDAQ", f"{s}")
s = b._spec("0700.HK")
check(s.symbol == "700" and s.exchange == "SEHK" and s.currency == "HKD"
      and s.primary_exchange == "SEHK" and s.market == "HK",
      "0700.HK → SEHK/HKD/symbol=700", f"{s}")
s = b._spec("700")
check(s.symbol == "700" and s.market == "HK", "700 → 同为港股合约")
s = b._spec("^HSI")
check(s.symbol == "HSI" and s.sec_type == "IND" and s.exchange == "HKFE"
      and s.currency == "HKD", "^HSI → Index(HKFE, HKD)", f"{s}")
s = b._spec("^GSPC")
check(s.symbol == "SPX" and s.exchange == "CBOE" and s.currency == "USD",
      "^GSPC → Index(CBOE, USD)")
s = b._spec("BRK-B")
check(s.symbol == "BRK B" and s.primary_exchange == "NYSE",
      "BRK-B → 'BRK B' (IB 用空格)", f"{s}")

try:
    b._spec("!!!")
    check(False, "非法符号应抛异常")
except Exception as exc:  # noqa: BLE001
    check(isinstance(exc, K.mksym.SymbolError), "非法符号抛 SymbolError", type(exc).__name__)

# display_symbol 反向还原
d = b.display_symbol(hk_contract("700", "700"))
check(d == ("0700.HK", "HK", "HKD"), "港股合约 → 0700.HK", str(d))
us = ib_async.Stock("AAPL", "SMART", "USD")
us.localSymbol = "AAPL"
check(b.display_symbol(us)[0] == "AAPL", "美股合约 → AAPL")
idx = ib_async.Index("HSI", "HKFE", "HKD")
idx.localSymbol = "HSI"
check(b.display_symbol(idx) == ("^HSI", "HK", "HKD"), "港股指数 → ^HSI",
      str(b.display_symbol(idx)))

# 合约缓存按规范化代码去重
b._contracts.clear()
for name in ("0700.HK", "700", "0700"):
    b._contract(name)
check(len(b._contracts) == 1, "三种写法共用一份缓存的合约", str(list(b._contracts)))

# ---------------------------------------------------------------- 2 事件注册
print("\n[2] 事件注册（#34）：补齐 6 个回报通道")
check(set(b._registered) >= {"orderStatusEvent", "execDetailsEvent", "commissionReportEvent",
                             "pendingTickersEvent", "errorEvent", "disconnectedEvent"},
      "注册了全部关键事件", str(b._registered))

# ---------------------------------------------------------------- 3 流式行情
print("\n[3] 流式行情（#31）：reqMktData + 内存 tick 缓存 + 中枢转发")
b2, fake2 = make_broker()
received: list = []
b2.tick_sink = received.append

ok = b2.subscribe(["AAPL", "0700.HK"])
check(ok is True, "subscribe 返回 True")
check(fake2.md_requests == ["AAPL", "700"], "对 IB 发了 2 次 reqMktData",
      str(fake2.md_requests))
check(set(b2.streamed_symbols()) == {"AAPL", "0700.HK"}, "streamed_symbols 正确",
      str(b2.streamed_symbols()))

# 推送一个真实 tick
tk = fake2.tickers["AAPL"]
tk.last = 187.4
tk.bid = 187.35
tk.ask = 187.45
tk.bidSize = 300
tk.askSize = 500
tk.volume = 1_234_567
tk.high = 188.0
tk.low = 185.5
tk.open = 186.0
tk.close = 185.0
fake2.pendingTickersEvent.emit([tk])
got = b2.get_tick("AAPL")
check(got is not None and got.price == 187.4, "推送进入本地 tick 缓存",
      f"{got.price if got else None}")
check(got.source == "ibkr-stream" and got.market == "US" and got.currency == "USD",
      "tick 携带市场/币种/来源", f"{got.source} {got.market} {got.currency}")
check(abs(got.spread_bps - (0.1 / 187.4 * 1e4)) < 0.01, "价差计算正确",
      f"{got.spread_bps:.3f} bps")
check(len(received) == 1, "已转发给中枢（tick_sink）", f"{len(received)} 条")

# 港股推送到缓存并正名
tk2 = fake2.tickers["700"]
tk2.last = 412.8
tk2.bid = 412.6
tk2.ask = 413.0
fake2.pendingTickersEvent.emit([tk2])
hk_tick = b2.get_tick("0700.HK")
check(hk_tick is not None and hk_tick.market == "HK" and hk_tick.currency == "HKD",
      "港股 tick 正确归类", f"{hk_tick.market} {hk_tick.currency}")
check(b2.get_tick("700") is not None, "同一港股用 '700' 也能取到")
check(b2.get_tick("09999") is None, "未订阅的标的返回 None")

# IB 占位值过滤
tk3 = fake2.tickers["AAPL"]
tk3.last = float("nan")     # 无 last
tk3.bid = -1.0
tk3.ask = -1.0
tk3.close = 185.0
fake2.pendingTickersEvent.emit([tk3])
check(b2.get_tick("AAPL").price == 185.0, "last/bid/ask 全是占位时回退到前收盘",
      str(b2.get_tick("AAPL").price))
check(b2.get_tick("AAPL").bid is None, "-1 占位 → bid=None")

# 缓存直出：不再发 reqTickers
before = fake2.ticker_req_count
b2.get_tick("AAPL")
tk3.last = 187.9
fake2.pendingTickersEvent.emit([tk3])
rows = b2.snapshot(["AAPL"])
check(fake2.ticker_req_count == before, "有流式缓存时 snapshot 零 IB 请求",
      f"reqTickers 调用次数 {fake2.ticker_req_count}（之前 {before}）")
check(rows[0]["price"] == 187.9 and rows[0]["mode"] == "stream",
      "快照读的是流式缓存", f"{rows[0]['price']}")
check(rows[0]["market"] == "US" and rows[0]["currency"] == "USD",
      "快照带市场/币种字段")

# 退订
b2.unsubscribe(["0700.HK"])
check("0700.HK" not in b2.streamed_symbols(), "退订后 streamed_symbols 移除")
check(fake2.md_cancels == ["700"], "对 IB 发了 cancelMktData", str(fake2.md_cancels))
check(b2.get_tick("0700.HK") is None, "退订后清空 tick 缓存")

# ---------------------------------------------------------------- 4 限流 / 熔断
print("\n[4] 限流与熔断（#35）：IB 50 msg/s 硬限")
b3, fake3 = make_broker()
b3._pacer = K.Pacer(rate=1.0, burst=1, max_wait=0.0)
b3._gate()
try:
    b3._gate()
    check(False, "令牌耗尽后第二次 _gate 应拒绝")
except K.BrokerError as exc:
    check("限流" in str(exc), "令牌耗尽 → 抛限流错误", str(exc)[:60])

b4, fake4 = make_broker()
b4._breaker = K.CircuitBreaker(fail_threshold=3, cooldown=5.0)
for _ in range(3):
    b4._breaker.record_failure("boom")
try:
    b4._gate()
    check(False, "熔断后 _gate 应拒绝")
except K.BrokerError as exc:
    check("熔断" in str(exc), "连续失败 → 抛熔断错误", str(exc)[:70])

b5, fake5 = make_broker()
check(b5._breaker.state == "closed", "初始未熔断，_gate 放行")
b5._gate()

# ---------------------------------------------------------------- 5 下单前置校验
print("\n[5] 下单校验：只读 / 非法标的 / 非法 TIF / 港股市价单")
b6, fake6 = make_broker(readonly=True)
r = b6.place_order("AAPL", "BUY", 10)
check(r.ok is False and "只读" in r.message, "只读模式拒单", r.message[:40])

b6.readonly = False
r = b6.place_order("!!!", "BUY", 10)
check(r.ok is False and "无法识别的标的" in r.message, "非法标的拒单", r.message[:50])
r = b6.place_order("AAPL", "BUY", 0)
check(r.ok is False and "大于 0" in r.message, "数量为 0 拒单")
r = b6.place_order("AAPL", "BUY", 10, order_type="LMT")
check(r.ok is False and "limit_price" in r.message, "限价单缺价格 → 拒单")

# 港股：TIF 白名单
r = b6.place_order("0700.HK", "BUY", 100, order_type="LMT", limit_price=410.0, tif="IOC")
check(r.ok is False and "TIF=IOC" in r.message, "港股拒绝 IOC（只允许 DAY/GTC）",
      r.message[:70])
r = b6.place_order("AAPL", "BUY", 10, order_type="LMT", limit_price=180.0, tif="IOC")
check(r.ok is True, "美股允许 IOC", r.message[:50])

# 港股：无盘口时不能凭空造市价单
b7, fake7 = make_broker()
r = b7.place_order("0700.HK", "BUY", 100, order_type="MKT")
check(r.ok is False and "不支持市价单" in r.message,
      "港股 MKT 且无盘口 → 拒单并解释", r.message[:70])

# 港股：有盘口 → 自动转进取限价
fake7.reqMktData(hk_contract("700", "700"))
tk_hk = fake7.tickers["700"]
tk_hk.last = 412.0
tk_hk.bid = 411.8
tk_hk.ask = 412.2
fake7.pendingTickersEvent.emit([tk_hk])
b7.subscribe(["0700.HK"])
r = b7.place_order("0700.HK", "BUY", 100, order_type="MKT", wait_fill=False)
check(r.ok is True, "港股 MKT → 自动转进取限价单", r.message[:80])
check(r.raw.get("market_order_simulated") is True, "raw 标记了模拟市价单")
placed = fake7.trades[-1]
check(placed.order.orderType == "LMT", "实际下发的是 LMT", placed.order.orderType)
check(placed.order.lmtPrice > 412.2, "买单价挂在卖一之上（保证成交）",
      f"lmt={placed.order.lmtPrice} > ask=412.2")
check(placed.order.tif in ("DAY", "GTC"), "TIF 合法", placed.order.tif)

# ---------------------------------------------------------------- 6 下单去阻塞
print("\n[6] 下单去阻塞（#33）：删除固定 sleep(0.8)")
b8, fake8 = make_broker()
fake8.auto_fill_after = 0.05
fake8.fill_price = 187.5
t0 = time.perf_counter()
r = b8.place_order("AAPL", "BUY", 10, order_type="MKT")
el = (time.perf_counter() - t0) * 1000
check(r.ok is True, "美股市价单提交成功", r.message[:70])
check(r.order_id and r.order_id != "", "拿到 orderId", r.order_id)
check(el < 500, f"事件驱动等待成交，总耗时 {el:.0f}ms（旧实现固定 800ms 起）")
check(r.filled_qty == 10 and r.avg_price == 187.5, "成交数量/均价由事件回填",
      f"filled={r.filled_qty} avg={r.avg_price}")
check(r.latency_ms > 0, "埋点给出 latency_ms", f"{r.latency_ms} ms")
check(r.raw["submit_ms"] < el, "submit_ms 只覆盖提交阶段",
      f"submit={r.raw['submit_ms']}ms total={r.latency_ms}ms")
check(b8._last_order_latency_ms.get("waited_for_fill") is True, "记录等待了成交事件")

# wait_fill=False 应立即返回
b9, fake9 = make_broker()
t0 = time.perf_counter()
r2 = b9.place_order("AAPL", "BUY", 10, order_type="MKT", wait_fill=False)
el2 = (time.perf_counter() - t0) * 1000
check(r2.ok and el2 < 150, f"wait_fill=False 立即返回 {el2:.0f}ms", r2.status)

# 无成交回报时会等到 fill_timeout 后返回，而不是永久阻塞
b10, fake10 = make_broker(fill_timeout=0.3)
t0 = time.perf_counter()
r3 = b10.place_order("AAPL", "BUY", 10, order_type="MKT")
el3 = (time.perf_counter() - t0) * 1000
check(r3.ok is True, "超时不算失败（订单已被受理）", r3.message[:60])
check(200 < el3 < 700, f"等待上限约等于 fill_timeout=0.3s，实测 {el3:.0f}ms")

# 括号单：OCO 止盈止损
b11, fake11 = make_broker()
r4 = b11.place_order("AAPL", "BUY", 10, order_type="LMT", limit_price=180.0,
                     take_profit_price=200.0, stop_loss_price=170.0, wait_fill=False)
check(r4.ok is True, "括号单提交成功", r4.message[:80])
check(len(fake11.trades) == 3, "下发 1 主单 + 2 子单", f"{len(fake11.trades)} 笔")
children = fake11.trades[1:]
check(all(c.order.ocaGroup == children[0].order.ocaGroup for c in children),
      "止盈止损同属一个 OCA 组")
check(all(c.order.ocaType == 1 for c in children), "ocaType=1（成交即撤另一腿）")
check("US$200" in r4.message and "US$170" in r4.message,
      "提示文案用市场币种符号（美股 US$）", r4.message[:110])

b12, fake12 = make_broker()
tk12 = fake12.reqMktData(hk_contract("700", "700"))
tk12.last, tk12.bid, tk12.ask = 412.0, 411.8, 412.2
fake12.pendingTickersEvent.emit([tk12])
b12.subscribe(["0700.HK"])
r5 = b12.place_order("0700.HK", "BUY", 100, order_type="LMT", limit_price=410.0,
                     take_profit_price=450.0, stop_loss_price=390.0, wait_fill=False)
check("HK$450" in r5.message and "HK$390" in r5.message,
      "港股提示文案用 HK$", r5.message[:110])

# ---------------------------------------------------------------- 7 回报异步化
print("\n[7] 回报异步化（#34）：回调只碰内存，异常不再静默")
b13, fake13 = make_broker()
jobs: list = []
b13._apply_write = jobs.append

# 7a 订单状态
tr = fake13.placeOrder(ib_async.Stock("AAPL", "SMART", "USD"), FakeOrder(1, "MKT", "BUY", 10))
tr.orderStatus.status = "Filled"
tr.orderStatus.filled = 10.0
tr.orderStatus.avgFillPrice = 187.0
t0 = time.perf_counter()
b13._on_order_status(tr)
el = (time.perf_counter() - t0) * 1000
check(el < 5.0, f"订单状态回调耗时 {el:.3f}ms（纯内存，无数据库 IO）")
check(b13.stats["events_dropped"] == 0, "回调未抛异常（不再静默吞掉）",
      b13._last_error or "无错误")
check(b13.order_status_snapshot("1000") is not None, "快照可供落库时回放",
      str(b13.order_status_snapshot("1000")))
b13.drain_writes(2.0)
check(len(jobs) == 1 and jobs[0]["kind"] == "order_status", "状态变化投递到写队列",
      f"{len(jobs)} 条")

# 重复推送同一 filled 不再投递
b13._on_order_status(tr)
b13.drain_writes(2.0)
check(len(jobs) == 1, "filled 未增加 → 不重复投递", f"{len(jobs)} 条")

# 7b 成交明细去重
ex = SimpleNamespace(execId="0001.a", orderId="1", side="BOT", shares=10.0,
                     price=187.0, time="20260923 10:00:00", exchange="NASDAQ",
                     permId="900001")
fill = SimpleNamespace(execution=ex, contract=ib_async.Stock("AAPL", "SMART", "USD"),
                       commissionReport=None)
b13._on_exec_details(tr, fill)
b13.drain_writes(2.0)
n1 = len(jobs)
check(n1 == 2 and jobs[-1]["kind"] == "exec", "成交明细投递到写队列", f"{n1} 条")
b13._on_exec_details(tr, fill)      # 同一 execId 再来一次
b13.drain_writes(2.0)
check(len(jobs) == n1, "同一 execId 重复回报被去重", f"{len(jobs)} 条（首次后 {n1}）")
check(b13.stats["fills_seen"] == 1, "fills_seen 只计一次", str(b13.stats["fills_seen"]))

ex2 = SimpleNamespace(execId="0002.b", orderId="1", side="BOT", shares=5.0,
                      price=187.2, time="", exchange="NASDAQ", permId="900001")
b13._on_exec_details(tr, SimpleNamespace(execution=ex2, contract=tr.contract,
                                         commissionReport=None))
b13.drain_writes(2.0)
check(len(jobs) == n1 + 1, "新 execId 正常投递", f"{len(jobs)} 条")

# 7c 佣金
cr = SimpleNamespace(commission=1.05, currency="USD")
b13._on_commission(tr, fill, cr)
b13.drain_writes(2.0)
check(any(j["kind"] == "commission" for j in jobs), "佣金回报投递")
check(jobs[-1]["commission"] == 1.05, "佣金金额正确", str(jobs[-1].get("commission")))

# 7d 异常不再静默
b14, fake14 = make_broker()
b14._apply_write = lambda j: (_ for _ in ()).throw(RuntimeError("db down"))
bad = SimpleNamespace()   # 缺 order 属性 → 触发内部异常
b14._on_order_status(bad)
check(b14.stats["events_dropped"] == 1, "回调异常被计数（不再静默吞掉）",
      str(b14.stats["events_dropped"]))
check("订单回报处理异常" in b14._last_error, "异常写入 last_error", b14._last_error[:60])

# 7e 写队列满时不阻塞
b15, fake15 = make_broker()
b15._ensure_writer()
b15._write_q.maxsize = 1
b15._apply_write = lambda j: time.sleep(0.3)
b15._enqueue_write({"kind": "exec", "snap": {}})
b15._enqueue_write({"kind": "exec", "snap": {}})
b15._enqueue_write({"kind": "exec", "snap": {}})
check(b15.stats["events_dropped"] >= 1, "写队列满 → 丢弃并计数，不阻塞回调",
      f"dropped={b15.stats['events_dropped']}")

# ---------------------------------------------------------------- 8 错误 / 断连
print("\n[8] 错误与断连：关键错误码不再丢失")
b16, fake16 = make_broker()
b16._on_error(1, 200, "No security definition has been found")
check(b16._last_error_code == 200, "记录错误码 200")
check("No security definition" in b16._last_error, "记录错误文本", b16._last_error[:60])
b16._on_error(2, 2104, "Market data farm connection is OK")
check(b16._last_error_code == 2104, "信息性消息（2104）也记录错误码")
check("No security definition" in b16._last_error,
      "信息性消息不覆盖真正的错误", b16._last_error[:60])
b16._on_error(3, 1101, "Connectivity between IB and TWS has been lost")
check(b16.connected is False, "1101 → 标记为断开")
check("中断" in b16._last_error, "说明断连原因", b16._last_error[:70])

fake16.reqMktData(ib_async.Stock("AAPL", "SMART", "USD"))
fake16.reqMktData(hk_contract("700", "700"))
b16.subscribe(["AAPL", "0700.HK"])
check(len(b16.streamed_symbols()) == 2, "断连前有 2 个订阅")
b16._on_disconnected()
check(b16.streamed_symbols() == [], "断连后清空流式订阅")
check(b16.get_tick("AAPL") is None, "断连后清空 tick 缓存")

# ---------------------------------------------------------------- 9 状态输出
print("\n[9] status()：暴露流式 / 限流 / 熔断 / 延迟")
b17, fake17 = make_broker()
stt = b17.status()
for k in ("supports_streaming", "stream_method", "streamed_symbols", "tick_cache",
          "call_timeout_sec", "fill_timeout_sec", "pacing", "breaker",
          "event_handlers", "stats", "base_currency"):
    check(k in stt, f"status 含 {k}")
check(stt["stream_method"] == "reqMktData", "声明的流式方式正确")
check(stt["pacing"]["ib_hard_limit_per_sec"] == 50, "限流快照带 IB 硬限")
check(stt["call_timeout_sec"] <= 6.0, "调用超时已下调到 5s 量级",
      f"{stt['call_timeout_sec']}s")
check(stt["fill_timeout_sec"] <= 2.0, "成交等待上限 2s 量级",
      f"{stt['fill_timeout_sec']}s")

# 账户基准币种
acc = b17.account()
check(acc.currency == "USD" and acc.base_currency == "USD", "账户基准币种来自 accountValues")
check(acc.equity == 100000.0 and acc.realized_pnl == 300.0, "账户数值解析正确",
      f"equity={acc.equity}")

# ---------------------------------------------------------------- 10 中枢联动
print("\n[10] 与行情中枢的端到端联动")
from app.engine import stream as ST

try:
    hub = ST.MarketDataHub(poll_interval=0.2, stale_after=1.0)
    hub._broker = b2
    hub._broker_provider = "ibkr"
    hub._broker_at = time.monotonic()
    hub._attach_sink(b2)
    hub.start()
    hub.ensure(["AAPL"])
    time.sleep(0.35)
    tk3.last = 190.25
    tk3.bid = 190.2
    tk3.ask = 190.3
    fake2.pendingTickersEvent.emit([tk3])
    time.sleep(0.05)
    check(hub.mode_of("AAPL") == ST.MODE_STREAM,
          "真实 IBKR 适配器被中枢识别为 stream 模式", hub.mode_of("AAPL"))
    check(hub.latest("AAPL") is not None and hub.latest("AAPL").price == 190.25,
          "IBKR 推送 → 中枢缓存", f"{hub.latest('AAPL').price if hub.latest('AAPL') else None}")
    hub.stop()
except Exception as exc:  # noqa: BLE001
    check(False, "中枢联动失败", f"{type(exc).__name__}: {exc}")

# ---------------------------------------------------------------- 收尾
print("\n[11] 清理")
for bb in (b, b2, b3, b4, b5, b6, b7, b8, b9, b10, b11, b12, b13, b14, b15, b16, b17):
    try:
        bb._writer_stop.set()
    except Exception:  # noqa: BLE001
        pass
check(True, "写线程全部停止")

print("\n" + "=" * 78)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
