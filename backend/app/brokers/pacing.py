"""IBKR 消息限流与调用熔断。

为什么必须限流
--------------
IB 有一条**硬性**限制：客户端发送消息速率不得超过 50 msg/s。
超限后 IB 会直接断开连接，并且在同一时间窗口内反复超限会被暂时拒绝重连。
一次 10 标的的调仓，如果每个标的要 qualify 合约（1）+ 下单（1）+ 可能的下单前请求，
再叠加止盈止损子单，很容易在几百毫秒内打满配额 —— 尤其是在事件驱动、
多标的并发的执行模式下（这正是我们要达到的目标）。

所以：**并发提交必须以限流为前提**，否则"并发"换来的是断连。

熔断
----
IB 抖动时，所有调用都阻塞到超时（默认 5s），会把上层的 anyio 线程池吃干。
熔断器在连续失败后进入 OPEN，短时间**快速失败**，让上层立刻降级到缓存/合成数据，
而不是排队等死。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# IB 硬性限制 50 msg/s；留出余量，默认 42
DEFAULT_RATE = 42.0
DEFAULT_BURST = 24


@dataclass
class PacerStats:
    allowed: int = 0          # 累计放行消息数
    waited: int = 0           # 发生过等待的 acquire 调用次数
    rejected: int = 0         # 累计拒绝消息数（超 max_wait 放弃）
    total_wait_ms: float = 0.0
    peak_per_sec: int = 0

    def as_dict(self, rate: float, burst: int) -> dict:
        return {
            "allowed": self.allowed, "waited": self.waited, "rejected": self.rejected,
            "avg_wait_ms": round(self.total_wait_ms / self.waited, 2) if self.waited else 0.0,
            "total_wait_ms": round(self.total_wait_ms, 2),
            "peak_per_sec": self.peak_per_sec,
            "configured_rate_per_sec": rate, "burst": burst,
            "ib_hard_limit_per_sec": 50,
            "utilisation_pct": round(self.peak_per_sec / 50.0 * 100, 1),
        }


class Pacer:
    """线程安全令牌桶。

    `acquire()` 在令牌不足时**等待**而不是丢弃 —— 下单消息绝不能被静默吞掉。
    等待上限由 `max_wait` 控制，超时后返回 False，由调用方决定是否放弃。
    """

    def __init__(self, rate: float = DEFAULT_RATE, burst: int = DEFAULT_BURST,
                 max_wait: float = 2.0) -> None:
        self.rate = float(max(1.0, rate))
        self.burst = float(max(1.0, burst))
        self.max_wait = float(max_wait)
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self.stats = PacerStats()
        self._sec_window_start = time.monotonic()
        self._sec_count = 0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last = now

    def _roll_window(self, now: float | None = None) -> None:
        """把「每秒峰值」统计窗口向前滚动。必须在持锁状态下调用。

        早期实现只在「成功取到令牌」的分支里滚动窗口，导致窗口跨越等待期时
        计数被错误累加、峰值被低估。这里改为独立方法，`acquire` 与 `snapshot` 都调用。
        """
        now = time.monotonic() if now is None else now
        elapsed = now - self._sec_window_start
        if elapsed >= 1.0:
            self.stats.peak_per_sec = max(self.stats.peak_per_sec, self._sec_count)
            self._sec_window_start = now
            self._sec_count = 0

    def acquire(self, n: int = 1, max_wait: float | None = None) -> bool:
        limit = self.max_wait if max_wait is None else float(max_wait)
        deadline = time.monotonic() + limit
        counted_wait = False
        while True:
            with self._lock:
                self._refill()
                self._roll_window()
                if self._tokens >= n:
                    self._tokens -= n
                    self.stats.allowed += n
                    self._sec_count += n
                    return True
                need = n - self._tokens
                wait = need / self.rate
            if time.monotonic() + wait > deadline:
                # 已经可以判定「即使等满也拿不到」→ 快速失败，不做无谓的阻塞。
                with self._lock:
                    self.stats.rejected += n
                return False
            if not counted_wait:
                counted_wait = True
                with self._lock:
                    self.stats.waited += 1
            time.sleep(min(wait, 0.005))
            with self._lock:
                self.stats.total_wait_ms += wait * 1000.0

    def try_acquire(self, n: int = 1) -> bool:
        """不等待版本：拿不到就返回 False。"""
        with self._lock:
            self._refill()
            self._roll_window()
            if self._tokens >= n:
                self._tokens -= n
                self.stats.allowed += n
                self._sec_count += n
                return True
            self.stats.rejected += n
            return False

    def snapshot(self) -> dict:
        with self._lock:
            self._refill()
            self._roll_window()
            free = self._tokens
        d = self.stats.as_dict(self.rate, int(self.burst))
        d["tokens_free"] = round(free, 2)
        return d


class CircuitBreaker:
    """连续失败 → OPEN（快速失败）→ 冷却后 HALF_OPEN 试探 → 成功则 CLOSED。"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, fail_threshold: int = 5, cooldown: float = 8.0,
                 half_open_trials: int = 2) -> None:
        self.fail_threshold = int(max(1, fail_threshold))
        self.cooldown = float(max(0.1, cooldown))
        self.half_open_trials = int(max(1, half_open_trials))
        self._fails = 0
        self._opened_at = 0.0
        self._trials = 0
        self._state = self.CLOSED
        self._lock = threading.Lock()
        self.last_error = ""
        self.trip_count = 0
        self.history: list[dict] = []

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN and time.monotonic() - self._opened_at >= self.cooldown:
                self._state = self.HALF_OPEN
                self._trials = 0
            return self._state

    def allow(self) -> bool:
        st = self.state
        if st == self.CLOSED:
            return True
        if st == self.OPEN:
            return False
        with self._lock:
            if self._trials < self.half_open_trials:
                self._trials += 1
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._fails = 0
            self._state = self.CLOSED
            self._trials = 0
            self.last_error = ""

    def record_failure(self, err: str = "") -> None:
        with self._lock:
            self._fails += 1
            self.last_error = str(err)[:200]
            if self._state == self.HALF_OPEN or self._fails >= self.fail_threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                self.trip_count += 1
                self.history.append({
                    "at": dt_now(), "error": self.last_error, "failures": self._fails,
                })
                self.history = self.history[-20:]

    def snapshot(self) -> dict:
        return {
            "state": self.state, "consecutive_failures": self._fails,
            "trip_count": self.trip_count, "cooldown_sec": self.cooldown,
            "last_error": self.last_error, "recent_trips": self.history[-5:],
        }

    def reset(self) -> None:
        with self._lock:
            self._fails = 0
            self._state = self.CLOSED
            self._trials = 0


def dt_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


__all__ = [
    "Pacer", "PacerStats", "CircuitBreaker",
    "DEFAULT_RATE", "DEFAULT_BURST",
]
