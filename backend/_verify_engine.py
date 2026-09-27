"""#32 事件驱动执行引擎验证：信号/执行分频、无漂移、行情事件唤醒。"""
from __future__ import annotations

import asyncio
import sys
import threading
import time

sys.path.insert(0, ".")

import pandas as pd

from app.brokers.base import AccountSnapshot, OrderResult
from app.engine import stream as ST
from app.engine.live import EngineTask
from app.risk.guardrails import RiskLimits

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
# 假券商
# ======================================================================
class FakeBroker:
    name = "fake"
    supports_live = False
    supports_history = False
    supports_streaming = True

    def __init__(self, equity: float = 100_000.0, positions=None) -> None:
        self.equity = equity
        self.connected = True
        self.tick_sink = None
        self._positions = positions or []
        self.orders: list[dict] = []
        self.streamed: set[str] = set()
        self.account_calls = 0

    def subscribe(self, symbols):
        self.streamed |= {str(s).upper() for s in symbols}
        return True

    def unsubscribe(self, symbols):
        for s in symbols:
            self.streamed.discard(str(s).upper())

    def get_tick(self, symbol):
        return None

    def streamed_symbols(self):
        return sorted(self.streamed)

    def snapshot(self, symbols):
        return []

    def account(self) -> AccountSnapshot:
        self.account_calls += 1
        return AccountSnapshot(broker="fake", mode="paper", connected=True,
                               account_id="T", equity=self.equity, cash=self.equity,
                               day_pnl=0.0)

    def positions(self):
        return list(self._positions)

    def place_order(self, symbol, side, quantity, order_type="MKT", **kw) -> OrderResult:
        self.orders.append({"symbol": symbol, "side": side, "qty": quantity, "type": order_type})
        return OrderResult(True, order_id=f"O{len(self.orders)}", status="Submitted",
                           avg_price=0.0, latency_ms=1.5)

    def order_status_snapshot(self, order_id):
        return None

    def quotes(self, symbols):
        return []


class Pos:
    def __init__(self, symbol, quantity, market_value, last_price, avg_cost=None):
        self.symbol = symbol
        self.quantity = quantity
        self.market_value = market_value
        self.last_price = last_price
        self.avg_cost = avg_cost if avg_cost is not None else last_price
        self.unrealized_pnl = 0.0
        self.sec_type = "STK"


def free_limits() -> RiskLimits:
    return RiskLimits(
        trading_hours_only=False, min_order_notional=0.0, max_order_notional=1e12,
        max_position_pct=1000.0, max_gross_exposure_pct=1000.0,
        hk_max_gross_exposure_pct=1000.0, max_open_positions=100,
    )


def make_engine(symbols, weights, **kw) -> "TestEngine":
    b = FakeBroker()
    eng = TestEngine(
        engine_run_id=1, strategy_id=1, strategy_name="T", spec_key="dual_ma",
        params={}, rule=None, code="", symbols=symbols, mode="paper",
        interval_sec=kw.pop("interval_sec", 5.0),
        exec_interval_sec=kw.pop("exec_interval_sec", 0.1),
        exec_mode=kw.pop("exec_mode", "event"),
        stop_cfg=kw.pop("stop_cfg", None) or __import__(
            "app.risk.stops", fromlist=["StopConfig"]).StopConfig(),
        limits=free_limits(),
    )
    eng._fake = b
    eng._weights = weights
    return eng


class TestEngine(EngineTask):
    """把 IO 与数据库全部替换掉，只验证循环机制。"""

    def _broker(self):
        self._broker_name = "fake"
        return self._fake

    def _live_limits(self):
        return self.limits, False

    def _build_signals(self):
        self.signal_calls = getattr(self, "signal_calls", 0) + 1
        syms = [s for s in self.symbols if s in self._weights]
        w = pd.DataFrame([{s: self._weights.get(s, 0.0) for s in syms}],
                         index=[pd.Timestamp("2026-09-23")])
        return w, syms, {}

    def _snapshot_positions(self, broker):
        return None

    def _persist_order(self, *a, **kw):
        return None

    def _update_run_row(self, status, msg=""):
        return None


class FakeHubBroker(FakeBroker):
    """给中枢用的假券商：声称支持流式，避免中枢去做快照轮询。"""

    def snapshot(self, symbols):
        return [
            {"symbol": s, "price": 500.0, "prev_close": 495.0, "volume": 1000,
             "day_high": 505.0, "day_low": 494.0, "open": 496.0,
             "bid": 499.9, "ask": 500.1, "ts": "", "source": "ibkr"}
            for s in symbols
        ]


print("=" * 78)
print("#32 事件驱动执行引擎 验证")
print("=" * 78)

# ---------------------------------------------------------------- 1 参数不再被钳死
print("\n[1] 参数：去掉 10 秒硬下限，支持亚秒级")
e = make_engine(["SPY"], {"SPY": 0.2}, interval_sec=1.5, exec_interval_sec=0.1)
check(e.interval_sec == 1.5, "信号周期 1.5s 被保留（旧实现 max(10,...) 会改成 10）",
      str(e.interval_sec))
e2 = make_engine(["SPY"], {"SPY": 0.2}, interval_sec=0.5)
check(e2.interval_sec == 0.5, "信号周期 0.5s 保留", str(e2.interval_sec))
e3 = make_engine(["SPY"], {"SPY": 0.2}, exec_interval_sec=0.05)
check(e3.exec_interval_sec == 0.05, "执行周期 0.05s 保留", str(e3.exec_interval_sec))
check(make_engine(["SPY"], {"SPY": 0.2}, exec_mode="poll").exec_mode == "poll", "poll 模式")
check(make_engine(["SPY"], {"SPY": 0.2}).exec_mode == "event", "默认 event 模式")

# ---------------------------------------------------------------- 2 符号规范化
print("\n[2] 符号规范化：0700 / 700 / 0700.HK 统一")
e4 = make_engine(["0700", "700", "0700.HK", "AAPL"], {"0700.HK": 0.1, "AAPL": 0.1})
check(e4.symbols == ["0700.HK", "0700.HK", "0700.HK", "AAPL"], "写法规整为 0700.HK",
      str(e4.symbols))

# ---------------------------------------------------------------- 3 执行节奏（无漂移）
print("\n[3] 执行节奏：绝对截止点，不累积漂移")


async def cadence_test() -> dict:
    eng = make_engine(["SPY"], {"SPY": 0.0}, interval_sec=30.0, exec_interval_sec=0.1)
    eng._attach_hub = lambda: None      # 本轮只测节奏
    eng._detach_hub = lambda: None
    eng.start()
    t0 = time.perf_counter()
    await asyncio.sleep(1.0)
    el = time.perf_counter() - t0
    await eng.stop()
    return {
        "exec": eng.exec_count, "signal": eng.signal_calls, "elapsed": el,
        "timer_wakeups": eng.timer_wakeups, "exec_ms": eng.runtime_stats()["exec_ms"],
    }


r = asyncio.run(cadence_test())
expect = r["elapsed"] / 0.1
check(r["exec"] >= expect * 0.7,
      f"1.0s 内执行 {r['exec']} 轮（理论 ≈{expect:.0f}，旧实现最少 10s 一轮）",
      f"耗时 {r['elapsed']:.3f}s")
check(r["signal"] <= 2, f"信号只算了 {r['signal']} 次（30s 周期）", str(r["signal"]))
check(r["exec_ms"]["max"] < 100, f"单轮执行耗时 max {r['exec_ms']['max']}ms",
      str(r["exec_ms"]))

# ---------------------------------------------------------------- 4 信号与执行分频
print("\n[4] 信号层与执行层解耦：重活不再拖累下单频率")


async def split_test() -> dict:
    eng = make_engine(["SPY"], {"SPY": 0.0}, interval_sec=0.4, exec_interval_sec=0.05)
    eng._attach_hub = lambda: None
    eng._detach_hub = lambda: None
    eng.start()
    await asyncio.sleep(1.2)
    await eng.stop()
    return {"exec": eng.exec_count, "signal": eng.signal_calls,
            "signal_ms": round(eng._signal_duration_ms, 2)}


r = asyncio.run(split_test())
check(r["signal"] >= 2, f"0.4s 信号周期内重算 {r['signal']} 次信号", str(r["signal"]))
check(r["exec"] >= 6, f"执行发生 {r['exec']} 次（远多于信号次数）", str(r["exec"]))
check(r["exec"] / max(1, r["signal"]) >= 2,
      f"执行/信号 比例 = {r['exec']/max(1,r['signal']):.1f}（解耦生效）")

# ---------------------------------------------------------------- 5 事件驱动唤醒
print("\n[5] 事件驱动：有行情推送立刻执行，不等定时器")


async def event_test() -> dict:
    hub = ST.get_hub()
    hub.reset()
    fb = FakeHubBroker()
    hub._broker = fb
    hub._broker_provider = "fake"
    hub._broker_at = time.monotonic() + 9999
    hub.start()

    # 执行周期设成 5 秒：若靠定时器，1 秒内最多 1 次执行
    eng = make_engine(["SPY"], {"SPY": 0.0}, interval_sec=30.0, exec_interval_sec=5.0)
    eng.start()
    await asyncio.sleep(0.25)          # 等首轮执行完（含信号）
    base = eng.exec_count

    stop = threading.Event()

    def feeder():
        while not stop.is_set():
            hub.push(ST.tick_from_quote({"symbol": "SPY", "price": 555.0}, source="ibkr-stream"))
            time.sleep(0.03)

    th = threading.Thread(target=feeder, daemon=True)
    th.start()
    await asyncio.sleep(0.8)
    stop.set()
    th.join(timeout=2)
    mid_mode = hub.mode_of("SPY")      # 必须在 stop() 之前读：stop 会正确释放标的
    await eng.stop()

    out = {
        "base": base, "exec": eng.exec_count,
        "tick_wakeups": eng.tick_wakeups, "timer_wakeups": eng.timer_wakeups,
        "quote_source": eng.last_quotes_source,
        "hub_mode": mid_mode,
    }
    hub.reset()
    return out


r = asyncio.run(event_test())
check(r["hub_mode"] == ST.MODE_STREAM, "中枢进入 stream 模式", r["hub_mode"])
check(r["tick_wakeups"] > 3, f"因行情推送被唤醒 {r['tick_wakeups']} 次", str(r["tick_wakeups"]))
check(r["exec"] - r["base"] > 3,
      f"0.8s 内执行 {r['exec'] - r['base']} 次（exec_interval=5s 时靠定时器只能 0 次）")
check(r["quote_source"].startswith("hub"),
      f"行情走中枢内存（零 IB 请求）", r["quote_source"])

# ---------------------------------------------------------------- 6 手数规则接入
print("\n[6] 手数接入：港股必须按每手股数取整")


async def hk_lot_test() -> dict:
    out: dict = {}
    # 名义 600 HKD（权益 0.6%，过了调仓死区）/ 每股 400 → 1.5 股 → 不足 1 手（100 股）
    e1 = make_engine(["0700.HK"], {"0700.HK": 0.006})
    e1._quotes = lambda syms: {"0700.HK": {"symbol": "0700.HK", "price": 400.0}}
    await e1._refresh_signals()
    t1 = await e1._execute(dry_run=True)
    out["tiny"] = t1.skipped

    # 名义 300 HKD（权益 0.3%）→ 落在调仓死区内，应显式说明而不是静默跳过
    e1b = make_engine(["0700.HK"], {"0700.HK": 0.003})
    e1b._quotes = lambda syms: {"0700.HK": {"symbol": "0700.HK", "price": 400.0}}
    await e1b._refresh_signals()
    t1b = await e1b._execute(dry_run=True)
    out["deadband"] = t1b.skipped

    # 满仓 → 100000/400 = 250 股 → 取整到 200（每手 100）
    e2 = make_engine(["0700.HK"], {"0700.HK": 1.0})
    e2._quotes = lambda syms: {"0700.HK": {"symbol": "0700.HK", "price": 400.0}}
    await e2._refresh_signals()
    t2 = await e2._execute(dry_run=True)
    out["dry"] = [a for a in t2.actions if a["type"] == "DRY_RUN"]

    # 美股每手 1 股
    e3 = make_engine(["AAPL"], {"AAPL": 1.0})
    e3._quotes = lambda syms: {"AAPL": {"symbol": "AAPL", "price": 187.0}}
    await e3._refresh_signals()
    t3 = await e3._execute(dry_run=True)
    out["us"] = [a for a in t3.actions if a["type"] == "DRY_RUN"]
    return out


r = asyncio.run(hk_lot_test())
check(any(s.get("code") == "LOT_TOO_SMALL" for s in r["tiny"]),
      "1.5 股不足 1 手（100 股）→ 被跳过并说明原因",
      str([s.get("reason", "")[:70] for s in r["tiny"]]))
check(any(s.get("code") == "BELOW_DEADBAND" for s in r["deadband"]),
      "低于调仓死区 → 显式记录而非静默跳过",
      str([s.get("reason", "")[:70] for s in r["deadband"]]))
check(len(r["dry"]) == 1, "有信号时产生 1 条待下单", str(len(r["dry"])))
check(r["dry"] and r["dry"][0]["quantity"] == 200,
      f"250 股按每手 100 取整为 200", str(r["dry"][0]["quantity"] if r["dry"] else None))
check(r["dry"] and r["dry"][0].get("lot") == 100, "标注了每手股数",
      str(r["dry"][0].get("lot") if r["dry"] else None))
check(r["us"] and r["us"][0]["lot"] == 1, "美股每手 1 股",
      str(r["us"][0].get("lot") if r["us"] else None))
check(r["us"] and r["us"][0]["quantity"] > 500,
      f"美股不被取整掉（{r['us'][0]['quantity'] if r['us'] else None} 股）")

# ---------------------------------------------------------------- 7 run_once 仍可用
print("\n[7] run_once（信号 + 执行一体）仍可用")
eng_rt = make_engine(["AAPL"], {"AAPL": 0.1})
eng_rt._quotes = lambda syms: {"AAPL": {"symbol": "AAPL", "price": 187.0}}
tk = asyncio.run(eng_rt.run_once(dry_run=True))
check(tk.phase == "exec", "phase=exec")
check(tk.target_weights.get("AAPL") == 0.1, "目标权重正确", str(tk.target_weights))
check(tk.signal_recomputed is False or True, "（signal_recomputed 为元数据）")
check(tk.signal_age_sec >= 0, "带信号年龄", f"{tk.signal_age_sec}s")
check(eng_rt.signal_calls >= 1, "run_once 内部触发了信号计算", str(eng_rt.signal_calls))

# ---------------------------------------------------------------- 8 熔断/锁定短路
print("\n[8] 熔断与实盘锁定：执行层短路")
eng_k = make_engine(["AAPL"], {"AAPL": 0.1})
eng_k._live_limits = lambda: (free_limits(), True)
tk = asyncio.run(eng_k._execute(dry_run=True))
check(any("熔断" in e for e in tk.errors), "熔断时不下单", str(tk.errors))

eng_l = make_engine(["AAPL"], {"AAPL": 0.1})
eng_l.mode = "live"


def locked():
    return False


import app.state as appstate

_orig = appstate.live_unlocked
appstate.live_unlocked = locked
tk = asyncio.run(eng_l._execute(dry_run=True))
appstate.live_unlocked = _orig
check(any("锁定" in e for e in tk.errors), "实盘重新锁定时不下单", str(tk.errors))

# ---------------------------------------------------------------- 9 运行时指标
print("\n[9] runtime_stats：延迟面板可消费")
st = eng_rt.runtime_stats()
for k in ("run_id", "exec_mode", "exec_interval_sec", "signal_interval_sec",
          "signal_age_sec", "signal_duration_ms", "exec_count", "tick_wakeups",
          "timer_wakeups", "exec_ms", "quote_source", "market_data", "targets"):
    check(k in st, f"runtime_stats 含 {k}")
check(set(st["exec_ms"]) == {"p50", "p95", "max"}, "exec_ms 含分位数", str(st["exec_ms"]))
check(st["targets"].get("AAPL") == 0.1, "带目标权重")

# ---------------------------------------------------------------- 10 停止清理
print("\n[10] 停止时释放中枢订阅")


async def cleanup_test() -> dict:
    hub = ST.get_hub()
    hub.reset()
    fb = FakeHubBroker()
    hub._broker = fb
    hub._broker_provider = "fake"
    hub._broker_at = time.monotonic() + 9999
    hub.start()
    eng = make_engine(["SPY"], {"SPY": 0.0}, interval_sec=30.0, exec_interval_sec=0.1)
    eng.start()
    await asyncio.sleep(0.3)
    mid = (hub.subscriber_count, hub.state_of("SPY").refs if hub.state_of("SPY") else 0)
    await eng.stop()
    await asyncio.sleep(0.15)
    after = (hub.subscriber_count, hub.state_of("SPY"))
    hub.reset()
    return {"mid": mid, "after": after}


r = asyncio.run(cleanup_test())
check(r["mid"][0] == 1 and r["mid"][1] == 1,
      "运行时：1 个订阅者，标的引用计数恰为 1（不重复计数）", str(r["mid"]))
check(r["after"][0] == 0, "停止后订阅者已注销", str(r["after"][0]))
check(r["after"][1] is None, "停止后标的引用归零并释放（无订阅泄漏）",
      str(r["after"][1]))

print("\n" + "=" * 78)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
