"""交易路径延迟埋点与分位数统计。

为什么需要它
------------
重构前全仓只有 `app/main.py` 里两行 HTTP `X-Process-Time-ms`，
交易路径**零埋点**。于是「慢」只能靠猜：
是行情太旧？风控太慢？还是下单往返本来就 800ms？

没有分段度量，就无法回答「还要优化哪一段」——这恰恰是毫秒级目标的前提。

分段设计（每一段都能独立看到 p50/p95/p99）
------------------------------------------
    行情链路
      tick.recv        券商推送 → 进入本地 tick 缓存
      tick.publish     中枢 push → 投递到订阅者（含跨线程唤醒）
      quote.age        行情自身年龄（交易所时间 → 本地接收时刻），不是我们的开销

    信号链路
      signal.build     拉历史 + 跑策略（重，低频）

    执行链路
      engine.exec      单轮执行：读内存行情 + 止损 + 风控 + 下单（轻，高频）
      risk.check       穿过 guardrails 的耗时
      order.submit     下单提交到券商（不含等成交）
      order.roundtrip  下单 → 成交回报（含券商侧撮合，天然较大）
      exec.report      IB 回调处理（必须 <1ms，否则拖累事件线程）

统计方式：每个阶段一个固定长度环形缓冲（`deque(maxlen=window)`），
用**排序后取分位**而不是滑动平均 —— 平均会把 P99 的隐患抹平。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# ======================================================================
# 阶段名（字符串常量，避免各处写错拼写）
# ======================================================================
TICK_RECV = "tick.recv"
TICK_PUBLISH = "tick.publish"
QUOTE_AGE = "quote.age"
SIGNAL_BUILD = "signal.build"
ENGINE_EXEC = "engine.exec"
RISK_CHECK = "risk.check"
ORDER_SUBMIT = "order.submit"
ORDER_ROUNDTRIP = "order.roundtrip"
EXEC_REPORT = "exec.report"
HUB_POLL = "hub.poll"
SNAPSHOT = "snapshot"

STAGES: tuple[str, ...] = (
    TICK_RECV, TICK_PUBLISH, QUOTE_AGE, SIGNAL_BUILD, ENGINE_EXEC,
    RISK_CHECK, ORDER_SUBMIT, ORDER_ROUNDTRIP, EXEC_REPORT, HUB_POLL, SNAPSHOT,
)

STAGE_LABELS: dict[str, str] = {
    TICK_RECV: "行情接收（券商 → 本地缓存）",
    TICK_PUBLISH: "行情分发（中枢 → 订阅者）",
    QUOTE_AGE: "行情年龄（交易所时间 → 本地）",
    SIGNAL_BUILD: "信号计算（历史 + 策略）",
    ENGINE_EXEC: "执行单轮（行情 + 止损 + 风控 + 下单）",
    RISK_CHECK: "风控护栏穿越",
    ORDER_SUBMIT: "下单提交（不含等成交）",
    ORDER_ROUNDTRIP: "下单往返（含券商撮合）",
    EXEC_REPORT: "成交回报回调处理",
    HUB_POLL: "行情中枢轮询周期",
    SNAPSHOT: "券商快照请求",
}

# 延迟预算（毫秒）：超出即认为该段是瓶颈。用于前端标红与告警。
# 依据：本地内存/风控应为亚毫秒；提交到 IB 走本机 socket 应 <5ms；
# 券商撮合是外部因素，给到 500ms。
BUDGET_MS: dict[str, float] = {
    TICK_RECV: 1.0,
    TICK_PUBLISH: 1.0,
    QUOTE_AGE: 2000.0,
    SIGNAL_BUILD: 3000.0,
    ENGINE_EXEC: 50.0,
    RISK_CHECK: 1.0,
    ORDER_SUBMIT: 5.0,
    ORDER_ROUNDTRIP: 500.0,
    EXEC_REPORT: 1.0,
    HUB_POLL: 50.0,
    SNAPSHOT: 2000.0,
}


# ======================================================================
# 单个阶段
# ======================================================================
class StageStats:
    """一个阶段的环形缓冲 + 分位数。线程安全。"""

    __slots__ = ("name", "_buf", "_lock", "count", "total_ms", "last_ms",
                 "last_at", "min_ms", "max_ms", "over_budget")

    def __init__(self, name: str, window: int = 1024) -> None:
        self.name = name
        self._buf: deque[float] = deque(maxlen=max(16, int(window)))
        self._lock = threading.Lock()
        self.count = 0
        self.total_ms = 0.0
        self.last_ms = 0.0
        self.last_at = 0.0
        self.min_ms = float("inf")
        self.max_ms = 0.0
        self.over_budget = 0

    def record(self, ms: float) -> None:
        try:
            v = float(ms)
        except (TypeError, ValueError):
            return
        if v != v or v < 0:
            return
        with self._lock:
            self._buf.append(v)
            self.count += 1
            self.total_ms += v
            self.last_ms = v
            self.last_at = time.time()
            if v < self.min_ms:
                self.min_ms = v
            if v > self.max_ms:
                self.max_ms = v
            budget = BUDGET_MS.get(self.name)
            if budget is not None and v > budget:
                self.over_budget += 1

    @staticmethod
    def _quantile(xs: list[float], q: float) -> float:
        if not xs:
            return 0.0
        idx = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        return xs[idx]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            xs = sorted(self._buf)
            count = self.count
            total = self.total_ms
            last = self.last_ms
            last_at = self.last_at
            lo = 0.0 if self.min_ms == float("inf") else self.min_ms
            hi = self.max_ms
            over = self.over_budget
            n = len(xs)
        budget = BUDGET_MS.get(self.name)
        p95 = self._quantile(xs, 0.95)
        return {
            "stage": self.name,
            "label": STAGE_LABELS.get(self.name, self.name),
            "count": count,
            "samples": n,
            "last_ms": round(last, 3),
            "last_at": last_at,
            "avg_ms": round(total / count, 3) if count else 0.0,
            "p50_ms": round(self._quantile(xs, 0.50), 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(self._quantile(xs, 0.99), 3),
            "min_ms": round(lo, 3),
            "max_ms": round(hi, 3),
            "budget_ms": budget,
            "over_budget": over,
            "healthy": (budget is None) or (p95 <= budget),
        }


# ======================================================================
# 追踪器
# ======================================================================
class LatencyTracker:
    """全部阶段的集合。进程内单例通过 `get_latency()` 获取。"""

    def __init__(self, window: int = 1024) -> None:
        self.window = max(16, int(window))
        self._stages: dict[str, StageStats] = {}
        self._lock = threading.Lock()
        self.started_at = time.monotonic()

    def stage(self, name: str) -> StageStats:
        st = self._stages.get(name)
        if st is None:
            with self._lock:
                st = self._stages.get(name)
                if st is None:
                    st = StageStats(name, self.window)
                    self._stages[name] = st
        return st

    def record(self, name: str, ms: float) -> None:
        self.stage(name).record(ms)

    def record_ns(self, name: str, delta_ns: int) -> None:
        """从纳秒差值记录（`time.perf_counter_ns()` 的差）。"""
        self.record(name, delta_ns / 1e6)

    # ---------------- 计时上下文 ----------------
    def timer(self, name: str) -> "_Timer":
        """`with tracker.timer(STAGE): ...` —— 异常也会记录耗时。"""
        return _Timer(self, name)

    # ---------------- 读取 ----------------
    def snapshot(self, names: list[str] | None = None) -> dict[str, Any]:
        keys = names or (list(self._stages) or list(STAGES))
        out: dict[str, Any] = {}
        for k in keys:
            st = self._stages.get(k)
            out[k] = st.snapshot() if st is not None else _empty(k)
        return out

    def summary(self) -> dict[str, Any]:
        snaps = self.snapshot()
        tracked = {k: v for k, v in snaps.items() if v["count"] > 0}
        unhealthy = [v for v in tracked.values() if not v["healthy"]]
        return {
            "uptime_sec": round(time.monotonic() - self.started_at, 1),
            "window": self.window,
            "tracked_stages": len(tracked),
            "stages": snaps,
            "budget_ms": dict(BUDGET_MS),
            "unhealthy": [
                {"stage": v["stage"], "label": v["label"], "p95_ms": v["p95_ms"],
                 "budget_ms": v["budget_ms"]}
                for v in unhealthy
            ],
            "healthy": not unhealthy,
            "checked_at": _iso_now(),
        }

    def reset(self) -> None:
        with self._lock:
            self._stages.clear()
        self.started_at = time.monotonic()


class _Timer:
    __slots__ = ("_t", "_name", "_t0", "_extra")

    def __init__(self, tracker: LatencyTracker, name: str) -> None:
        self._t = tracker
        self._name = name
        self._t0 = 0

    def __enter__(self) -> "_Timer":
        self._t0 = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._t.record(self._name, (time.perf_counter_ns() - self._t0) / 1e6)
        return False


def _empty(name: str) -> dict[str, Any]:
    return {
        "stage": name, "label": STAGE_LABELS.get(name, name), "count": 0, "samples": 0,
        "last_ms": 0.0, "last_at": 0.0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0,
        "p99_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0,
        "budget_ms": BUDGET_MS.get(name), "over_budget": 0, "healthy": True,
    }


def _iso_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ======================================================================
# 行情延迟（需要交易所时间，单独处理）
# ======================================================================
def quote_age_ms(tick_ts: str, recv_ns: int) -> float | None:
    """由 tick 的交易所时间与本地接收时刻估算行情延迟（毫秒）。

    IB 的 `time` 字段通常是 UTC ISO 或 "YYYYMMDD HH:MM:SS"。解析失败返回 None
    （**不要**猜一个值 —— 假的延迟数字比没有数字更危险）。
    """
    if not tick_ts:
        return None
    import datetime as _dt

    t: _dt.datetime | None = None
    s = str(tick_ts).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y%m%d %H:%M:%S", "%Y%m%d-%H:%M:%S"):
        try:
            t = _dt.datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if t is None:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    try:
        local_age = (time.monotonic_ns() - recv_ns) / 1e6 if recv_ns else 0.0
        return (now_utc - t.astimezone(_dt.timezone.utc)).total_seconds() * 1000.0 - local_age
    except Exception:  # noqa: BLE001
        return None


# ======================================================================
# 单例
# ======================================================================
_tracker: LatencyTracker | None = None
_tracker_lock = threading.Lock()


def get_latency() -> LatencyTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = LatencyTracker()
    return _tracker


def reset_latency() -> None:
    global _tracker
    with _tracker_lock:
        if _tracker is not None:
            _tracker.reset()


__all__ = [
    "LatencyTracker", "StageStats", "get_latency", "reset_latency",
    "quote_age_ms", "STAGES", "STAGE_LABELS", "BUDGET_MS",
    "TICK_RECV", "TICK_PUBLISH", "QUOTE_AGE", "SIGNAL_BUILD", "ENGINE_EXEC",
    "RISK_CHECK", "ORDER_SUBMIT", "ORDER_ROUNDTRIP", "EXEC_REPORT",
    "HUB_POLL", "SNAPSHOT",
]
