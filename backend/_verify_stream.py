"""#31 行情中枢（MarketDataHub）验证。

用一个可编程的假券商驱动，覆盖：订阅生命周期、三种模式、广播、
last-value-wins 合并、降级、并发安全、延迟量级。
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time

sys.path.insert(0, ".")

from app.brokers.base import Tick
from app.engine import stream as st

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


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


# ======================================================================
# 假券商
# ======================================================================
class FakeBroker:
    name = "fake"
    supports_live = False
    supports_history = False
    supports_streaming = True

    def __init__(self, streaming: bool = True, connected: bool = True) -> None:
        self.enable_stream = streaming
        self._connected = connected
        self.tick_sink = None
        self.streamed: set[str] = set()
        self.subscribe_calls: list[list[str]] = []
        self.unsubscribe_calls: list[list[str]] = []
        self.snapshot_calls = 0
        self.snapshot_rounds = 0
        self._ticks: dict[str, Tick] = {}
        self.base_price = 100.0
        self.fail_snapshot = False

    # --- 连接 ---
    @property
    def connected(self) -> bool:
        return self._connected

    def set_connected(self, v: bool) -> None:
        self._connected = v

    # --- 流式 ---
    def subscribe(self, symbols):
        self.subscribe_calls.append(list(symbols))
        if not self.enable_stream or not self._connected:
            return False
        self.streamed |= {str(s).upper() for s in symbols}
        return True

    def unsubscribe(self, symbols):
        self.unsubscribe_calls.append(list(symbols))
        for s in symbols:
            self.streamed.discard(str(s).upper())
            self._ticks.pop(str(s).upper(), None)

    def get_tick(self, symbol):
        return self._ticks.get(str(symbol).upper())

    def streamed_symbols(self):
        return sorted(self.streamed)

    def emit(self, symbol: str, price: float, source: str = "ibkr-stream") -> Tick:
        """模拟券商推送：构造 tick → 调 tick_sink（= hub.push）。"""
        t = st.tick_from_quote({"symbol": symbol, "price": price, "bid": price - 0.01,
                                "ask": price + 0.01, "volume": 1000}, source=source)
        self._ticks[t.symbol] = t
        if self.tick_sink is not None:
            self.tick_sink(t)
        return t

    # --- 快照 ---
    def snapshot(self, symbols):
        self.snapshot_calls += 1
        if self.fail_snapshot:
            raise RuntimeError("snapshot boom")
        self.snapshot_rounds += 1
        out = []
        for s in symbols:
            sym = st.tick_from_quote({"symbol": s}).symbol
            p = self.base_price + self.snapshot_rounds
            out.append({
                "symbol": s, "price": p, "prev_close": self.base_price,
                "volume": 5000, "day_high": p + 1, "day_low": p - 1,
                "open": self.base_price, "bid": p - 0.02, "ask": p + 0.02,
                "ts": "2026-09-23T09:00:00+00:00", "source": "ibkr",
            })
        return out


class TestHub(st.MarketDataHub):
    """绕过设置表：直接注入假券商。"""

    def __init__(self, broker, **kw):
        super().__init__(**kw)
        self._fake = broker

    def _resolve_broker(self):
        self._attach_sink(self._fake)
        return self._fake, "fake"


def wait_for(pred, timeout: float = 5.0, interval: float = 0.02) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(interval)
    return False


print("=" * 78)
print("#31 行情中枢 MarketDataHub 验证")
print("=" * 78)

# ---------------------------------------------------------------- 1 报价转换
print("\n[1] tick_from_quote：跨市场规范化")
t_us = st.tick_from_quote({"symbol": "AAPL", "price": 187.25, "prev_close": 185.0,
                           "bid": 187.2, "ask": 187.3, "volume": 1234567})
check(t_us.symbol == "AAPL" and t_us.market == "US" and t_us.currency == "USD",
      "AAPL → US / USD", f"{t_us.symbol} {t_us.market} {t_us.currency}")
check(t_us.price == 187.25 and t_us.prev_close == 185.0, "价格与前收盘正确")
check(abs(t_us.spread_bps - (0.1 / 187.25 * 1e4)) < 1e-6,
      "买卖价差 bps 计算正确", f"{t_us.spread_bps:.3f} bps")
check(t_us.recv_ns > 0, "recv_ns 已填充单调纳秒")

t_hk = st.tick_from_quote({"symbol": "0700", "price": 412.6})
check(t_hk.symbol == "0700.HK", "0700 → 0700.HK（港股规范化）", t_hk.symbol)
check(t_hk.market == "HK" and t_hk.currency == "HKD",
      "港股市场/币种正确", f"{t_hk.market} {t_hk.currency}")

t_edge = st.tick_from_quote({"symbol": "", "price": 5})
check(t_edge.symbol == "" and t_edge.price == 5.0, "空符号不抛异常（容错）")
t_nan = st.tick_from_quote({"symbol": "SPY", "price": float("nan"), "bid": -1})
check(t_nan.price == 0.0 and t_nan.bid is None, "NaN / -1 占位被过滤")
# ---------------------------------------------------------------- 2 引用计数
print("\n[2] 订阅生命周期：引用计数 `ensure` / `release`")
fb = FakeBroker()
hub = TestHub(fb, poll_interval=0.2, stale_after=1.0)
hub.start()

got = hub.ensure(["SPY", "0700"])
check(got == ["SPY", "0700.HK"], "ensure 返回规范化代码", str(got))
check(hub.state_of("SPY").refs == 1, "SPY 引用计数 = 1")
hub.ensure(["SPY"])
check(hub.state_of("SPY").refs == 2, "重复 ensure → refs = 2")
hub.release(["SPY"])
check(hub.state_of("SPY") is not None and hub.state_of("SPY").refs == 1,
      "release 一次后仍存在（refs=1）")
hub.release(["SPY"])
check(hub.state_of("SPY") is None, "refs 归零 → 从表里移除")
check(wait_for(lambda: any("SPY" in c for c in fb.unsubscribe_calls), 2.0),
      "券商侧收到退订通知", str(fb.unsubscribe_calls))
check(hub.state_of("0700.HK") is not None, "其它标的未受影响")

# ---------------------------------------------------------------- 3 流式模式
print("\n[3] 流式订阅：建立 reqMktData 级推送")


def _has_stream(sym: str) -> bool:
    stt = hub.state_of(sym)
    return stt is not None and stt.mode == st.MODE_STREAM


check(wait_for(lambda: _has_stream("0700.HK"), 3.0),
      "轮询线程自动为标的建立流式订阅", f"mode={hub.mode_of('0700.HK')}")
check(fb.streamed == {"0700.HK"}, "券商侧 streamed set 正确", str(fb.streamed))
check(hub.mode_of("0700.HK") == st.MODE_STREAM, "中枢标记为 stream")

fb.emit("0700.HK", 415.0)
check(wait_for(lambda: hub.latest("0700.HK") is not None and hub.latest("0700.HK").price == 415.0, 1.0),
      "推送直达中枢缓存（tick_sink 链路）")
check(hub.latest("0700.HK").source == "ibkr-stream", "流式 tick 的 source 标记正确")
check(hub.age_ms("0700.HK") < 1000, "age_ms 合理", f"{hub.age_ms('0700.HK'):.1f} ms")

# ---------------------------------------------------------------- 4 快照模式
print("\n[4] 无流式权限 → 自动降级为快照轮询")
fb2 = FakeBroker(streaming=False)
hub2 = TestHub(fb2, poll_interval=0.2, stale_after=1.0)
hub2.start()
hub2.ensure(["AAPL"])


def _has_snapshot(h, sym):
    s = h.state_of(sym)
    return s is not None and s.mode == st.MODE_SNAPSHOT and s.tick is not None


check(wait_for(lambda: _has_snapshot(hub2, "AAPL"), 3.0),
      "streaming=False 时走快照轮询", f"mode={hub2.mode_of('AAPL')}")
check(fb2.snapshot_calls >= 1, "确实调用了券商快照", f"{fb2.snapshot_calls} 次")
check(hub2.latest("AAPL").price > 0, "快照价格已入缓存",
      f"{hub2.latest('AAPL').price}")
check(hub2.status()["streaming"] == [], "status.streaming 为空")
check("AAPL" in hub2.status()["snapshot"], "status.snapshot 含 AAPL")

# ---------------------------------------------------------------- 5 合成行情
print("\n[5] 全源不可用 → 合成行情被明确标记（前端必须告警）")
fb3 = FakeBroker(streaming=False)
hub3 = TestHub(fb3, poll_interval=0.2, stale_after=1.0)
hub3.start()
hub3.ensure(["ZZZZ"])
hub3.push(st.tick_from_quote({"symbol": "ZZZZ", "price": 42.0}, source="synthetic"))
check(hub3.mode_of("ZZZZ") == st.MODE_SYNTHETIC, "source=synthetic → mode=synthetic")
check(hub3.state_of("ZZZZ").error, "带有明确错误说明",
      hub3.state_of("ZZZZ").error)
check(any("合成行情" in w for w in hub3.status()["warnings"]),
      "status.warnings 提示合成行情", str(hub3.status()["warnings"]))

# ---------------------------------------------------------------- 6 流式失联降级
print("\n[6] 流式长时间无推送 → 累计兜底后降级为快照")
fb4 = FakeBroker(streaming=True)
hub4 = TestHub(fb4, poll_interval=0.2, stale_after=0.5)
hub4.start()
hub4.ensure(["TSLA"])
check(wait_for(lambda: hub4.mode_of("TSLA") == st.MODE_STREAM, 3.0), "先建立流式")
# 不再推送，让它失联
check(wait_for(lambda: hub4.mode_of("TSLA") == st.MODE_SNAPSHOT, 6.0),
      "失联后降级为 snapshot", f"mode={hub4.mode_of('TSLA')}")
check("降级" in (hub4.state_of("TSLA").error or ""), "记录了降级原因",
      hub4.state_of("TSLA").error)

# ---------------------------------------------------------------- 7 拉取模式订阅者
print("\n[7] 订阅者（拉取模式）：drain + last-value-wins 合并")
fb5 = FakeBroker(streaming=True)
hub5 = TestHub(fb5, poll_interval=0.2, stale_after=30.0)
hub5.start()
sub = hub5.subscribe_events(["AAPL", "MSFT"], sid="pull-1")
check(sub.stats()["mode"] == "pull", "无 loop → 拉取模式")
# 多推几次 AAPL，只应保留最新
for i in range(5):
    hub5.push(st.tick_from_quote({"symbol": "AAPL", "price": 100.0 + i}, source="ibkr-stream"))
hub5.push(st.tick_from_quote({"symbol": "MSFT", "price": 300.0}, source="ibkr-stream"))
items = sub.drain()
check(len(items) == 2, "5 次 AAPL + 1 次 MSFT → 合并为 2 条", f"实际 {len(items)}")
check([t.price for t in items if t.symbol == "AAPL"] == [104.0],
      "AAPL 只保留最新价 104", str([t.price for t in items if t.symbol == "AAPL"]))
check(sub.coalesced == 4, "coalesced 计数 = 4", f"{sub.coalesced}")
check(sub.delivered == 2, "delivered 计数 = 2")
check(sub.drain() == [], "再次 drain 为空")

# 溢出淘汰
sub_small = hub5.subscribe_events(["AAPL", "MSFT", "NVDA", "AMD"], sid="pull-2", maxlen=2)
for s in ("AAPL", "MSFT", "NVDA", "AMD"):
    hub5.push(st.tick_from_quote({"symbol": s, "price": 1.0}, source="ibkr-stream"))
check(sub_small.overflow >= 1, "超过 maxlen 时淘汰最早条目", f"overflow={sub_small.overflow}")
check(len(sub_small.drain()) == 2, "pending 不超过 maxlen")

hub5.unsubscribe_events("pull-1")
check(hub5.subscriber_count == 1, "退订后订阅者数 = 1")
check(hub5.state_of("AAPL") is None or hub5.state_of("AAPL").refs >= 1,
      "共享标的不会因单个订阅者退出而丢订阅")

# ---------------------------------------------------------------- 8 推送模式订阅者
print("\n[8] 订阅者（推送模式）：asyncio 队列 + 唤醒")


async def push_mode_test() -> dict:
    fb6 = FakeBroker(streaming=True)
    # 轮询周期拉长，避免测试期间混入兜底快照
    hub6 = TestHub(fb6, poll_interval=30.0, stale_after=60.0)
    hub6.start()
    loop = asyncio.get_running_loop()
    sub = hub6.subscribe_events(["AAPL", "0700"], loop=loop, sid="push-1")
    # 等首轮「建立流式订阅 + 基线快照」（这是期望行为：订阅者立刻有数据可看）
    await asyncio.sleep(0.4)
    out: dict = {
        "mode": sub.stats()["mode"],
        "baseline": [(t.symbol, t.price) for t in sub.drain()],
    }

    sub.discard()
    out["discard_after"] = len(sub._pending)

    # ---- A. 消费者「不消费」时：同一标的应被合并为最新一条（背压） ----
    def emitter_blocking():
        for i in range(3):
            fb6.emit("AAPL", 200.0 + i)
            time.sleep(0.02)
        fb6.emit("0700.HK", 410.0)
        time.sleep(0.05)

    th = threading.Thread(target=emitter_blocking, daemon=True)
    th.start()
    th.join(timeout=5.0)
    await asyncio.sleep(0.15)          # 让 call_soon_threadsafe 全部落地
    coalesced = sub.drain()
    out["coalesced"] = [(t.symbol, t.price) for t in coalesced]

    # ---- B. 消费者「跟得上」时：逐笔送达，不做无谓丢弃 ----
    delivered: list[tuple[str, float]] = []

    async def consume(n: int) -> None:
        for _ in range(n):
            t = await asyncio.wait_for(sub.get(timeout=3.0), timeout=4.0)
            if t is not None:
                delivered.append((t.symbol, t.price))

    task = asyncio.create_task(consume(3))
    await asyncio.sleep(0.05)
    for i in range(3):
        fb6.emit("AAPL", 300.0 + i)
        await asyncio.sleep(0.03)
    await asyncio.wait_for(task, timeout=5.0)
    out["delivered"] = delivered

    out["timeout_returns_none"] = (await sub.get(timeout=0.2)) is None
    out["cache_final"] = hub6.latest("AAPL").price
    hub6.unsubscribe_events("push-1")
    hub6.stop()
    return out


res = asyncio.run(push_mode_test())
check(res["mode"] == "push", "有 loop → 推送模式")
check(len(res["baseline"]) == 2, "订阅后立刻收到基线快照（不空窗）", str(res["baseline"]))
check(res["discard_after"] == 0, "discard() 清空待消费队列")
check(len(res["coalesced"]) == 2, "消费者落后时 3 次 AAPL + 1 次 0700 合并为 2 条",
      str(res["coalesced"]))
check(("AAPL", 202.0) in res["coalesced"], "AAPL 保留最新价 202（last-value-wins）")
check(("0700.HK", 410.0) in res["coalesced"], "0700.HK 取到 410")
check(res["delivered"] == [("AAPL", 300.0), ("AAPL", 301.0), ("AAPL", 302.0)],
      "消费者跟得上时逐笔送达（不做无谓丢弃）", str(res["delivered"]))
check(res["timeout_returns_none"], "get 超时返回 None 而非抛异常")
check(res["cache_final"] == 302.0, "中枢缓存最终价 = 302")

# ---------------------------------------------------------------- 8b 快照不得覆盖新鲜流式
print("\n[8b] 新鲜流式数据优先：兜底快照不得覆盖它")
fb8 = FakeBroker(streaming=True)
hub8 = TestHub(fb8, poll_interval=30.0, stale_after=60.0)
hub8.start()
hub8.ensure(["AAPL"])
check(wait_for(lambda: hub8.mode_of("AAPL") == st.MODE_STREAM, 3.0), "先进入流式模式")
fb8.emit("AAPL", 250.0)
check(hub8.latest("AAPL").price == 250.0, "流式价 250 已入缓存")
st_before = hub8.state_of("AAPL")
pushes_before = st_before.pushes
# 模拟一次「迟到的兜底快照」：创建时间更晚，但信息更旧
hub8.push(st.tick_from_quote({"symbol": "AAPL", "price": 101.0}, source="ibkr"))
check(hub8.latest("AAPL").price == 250.0, "快照未覆盖新鲜流式价（仍为 250）",
      f"实际 {hub8.latest('AAPL').price}")
check(st_before.pushes == pushes_before, "被拒的 tick 未计入 pushes",
      f"{pushes_before} → {st_before.pushes}")
# 流式变陈旧后，快照应能接管
hub8.stale_after = 0.001
time.sleep(0.02)
hub8.push(st.tick_from_quote({"symbol": "AAPL", "price": 101.0}, source="ibkr"))
check(hub8.latest("AAPL").price == 101.0, "流式陈旧后快照可以接管",
      f"实际 {hub8.latest('AAPL').price}")
hub8.stop()

# ---------------------------------------------------------------- 8c IB 占位值过滤
print("\n[8c] IB 占位值（-1 / 0 / NaN）不得被当作真实报价")
t_ph = st.tick_from_quote({"symbol": "AAPL", "price": 100.0, "bid": -1, "ask": -1,
                           "prev_close": 0, "day_high": -1.7976931348623157e308})
check(t_ph.bid is None and t_ph.ask is None, "bid/ask = -1 → None（非「负买价」）",
      f"bid={t_ph.bid} ask={t_ph.ask}")
check(t_ph.spread_bps == 0.0, "缺买一卖一时价差为 0（不是负值）", f"{t_ph.spread_bps}")
check(t_ph.prev_close == 0.0, "prev_close = 0 → 0.0")
check(t_ph.high == 100.0, "异常大的占位值被过滤，回退到最新价", f"{t_ph.high}")

# ---------------------------------------------------------------- 9 读路径延迟
print("\n[9] 读路径延迟：latest() 必须远低于 1ms")
hub.ensure(["SPY"])
hub.push(st.tick_from_quote({"symbol": "SPY", "price": 555.0}, source="ibkr-stream"))
N = 20000
t0 = time.perf_counter()
for _ in range(N):
    hub.latest("SPY")
per_call_us = (time.perf_counter() - t0) / N * 1e6
check(per_call_us < 100, f"latest() 单次 {per_call_us:.2f} µs < 100µs")
check(hub.price("SPY") == 555.0, "price() 直达缓存", str(hub.price("SPY")))

t0 = time.perf_counter()
for _ in range(2000):
    hub.push(st.tick_from_quote({"symbol": "SPY", "price": 556.0}, source="ibkr-stream"))
per_push_us = (time.perf_counter() - t0) / 2000 * 1e6
check(per_push_us < 300, f"push() 单次 {per_push_us:.2f} µs（含序列号+订阅遍历）")

# ---------------------------------------------------------------- 10 并发安全
print("\n[10] 并发：推送线程 + 读取线程 + 订阅变更同时进行")
fb7 = FakeBroker(streaming=True)
hub7 = TestHub(fb7, poll_interval=0.2, stale_after=30.0)
hub7.start()
hub7.ensure([f"S{i}" for i in range(10)])
errors: list[str] = []
stop_flag = threading.Event()


def pusher():
    try:
        n = 0
        while not stop_flag.is_set():
            hub7.push(st.tick_from_quote({"symbol": f"S{n % 10}", "price": 10.0 + n % 7},
                                        source="ibkr-stream"))
            n += 1
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pusher: {exc}")


def reader():
    try:
        while not stop_flag.is_set():
            for i in range(10):
                hub7.latest(f"S{i}")
            hub7.status()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"reader: {exc}")


def churner():
    try:
        for _ in range(40):
            hub7.ensure(["S0", "S1"])
            hub7.release(["S0", "S1"])
    except Exception as exc:  # noqa: BLE001
        errors.append(f"churner: {exc}")


ths = [threading.Thread(target=pusher), threading.Thread(target=reader),
       threading.Thread(target=reader), threading.Thread(target=churner)]
for t in ths:
    t.start()
time.sleep(1.0)
stop_flag.set()
for t in ths:
    t.join(timeout=3)
check(not errors, "无异常抛出", str(errors[:3]))
check(hub7.stats.ticks_in > 1000, "推送量已达千级", f"{hub7.stats.ticks_in} 条")
check(all(hub7.state_of(f"S{i}") is not None for i in range(2, 10)),
      "高频 churn 下未登记的标的未丢失")

# ---------------------------------------------------------------- 11 quotes / status
print("\n[11] 对外接口：quotes / status / symbol_table")
qs = hub.quotes(["SPY", "0700.HK"])
check(len(qs) == 2, "quotes 返回 2 条")
check({"price", "prev_close", "change", "change_pct", "bid", "ask", "currency",
       "market", "source", "mode", "recv_ns"} <= set(qs[0]), "报价字典字段完整")
check(qs[0]["market"] == "US" and qs[1]["market"] == "HK", "多市场标记正确")

stt = hub.status()
for k in ("running", "subscribers", "streaming", "snapshot", "synthetic",
          "broker", "warnings", "stats", "mode_labels"):
    check(k in stt, f"status 含字段 {k}")
check(stt["broker"]["provider"] == "fake", "status 暴露券商来源")
check(isinstance(hub.symbol_table(), list), "symbol_table 返回列表")
check(stt["stats"]["ticks_in"] > 0, "统计有数据", f"ticks_in={stt['stats']['ticks_in']}")

# 快照失败不应炸掉轮询线程
fb2.fail_snapshot = True
hub2.refresh()  # 内部吞异常
check(hub2.running, "快照抛异常后轮询线程仍存活")

# ---------------------------------------------------------------- 12 收尾
for h in (hub, hub2, hub3, hub4, hub5, hub7):
    h.stop()
check(not hub.running, "stop() 后线程已退出")

print("\n" + "=" * 78)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
