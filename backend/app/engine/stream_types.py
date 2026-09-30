"""行情中枢的数据类型与工具函数（FILE_SIZE_DEBT Batch E-3 从 stream.py 拆出）。

只放「纯数据类型与纯工具」：SymbolState / Subscriber / HubStats、
报价字典 → Tick 的转换、模式常量。Hub 主体（MarketDataHub）留在 stream.py，
旧的 `from app.engine.stream import X` 路径通过 re-export 继续可用。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from ..brokers.base import Tick

# ----------------------------------------------------------------------
# 行情模式
# ----------------------------------------------------------------------
MODE_STREAM = "stream"
MODE_SNAPSHOT = "snapshot"
MODE_SYNTHETIC = "synthetic"
MODE_OFFLINE = "offline"

MODE_LABELS: dict[str, str] = {
    MODE_STREAM: "实时推送（reqMktData）",
    MODE_SNAPSHOT: "快照轮询",
    MODE_SYNTHETIC: "合成行情（非真实数据）",
    MODE_OFFLINE: "无行情",
}

# 中枢自身发出的流式 tick 用这个 source；券商的快照用 "ibkr"。
SOURCE_STREAM = "ibkr-stream"

# 连续多少次快照兜底都没等到流式数据，就正式降级
_DOWNGRADE_AFTER_STALE = 3


# ======================================================================
# 报价字典 → Tick
# ======================================================================
def _num(v: Any, default: float = 0.0) -> float:
    """数值转换，过滤 NaN / ±inf。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return f


def _price(v: Any) -> float | None:
    """价格类字段。

    IB 用 `-1`（以及 0）表示「该字段暂无数据」，旧实现的 `_ticker_row` 里
    有 `f not in (0.0, -1.0)` 这一判断。这里保留同等语义：非正数一律视为无数据，
    否则会把 `bid = -1` 当成真实买价，进而算出负的价差和错误的中间价。
    """
    f = _num(v, 0.0)
    return f if f > 0 else None


def tick_from_quote(row: dict, source: str = "") -> Tick:
    """把统一报价字典（券商快照 / data_provider 各源）转成 `Tick`。

    报价字典的字段约定在所有数据源里是一致的：
        symbol / price / prev_close / change / change_pct / volume /
        day_high / day_low / open / bid / ask / ts / source
    """
    raw = str(row.get("symbol") or "").strip()
    market, currency, symbol = "US", "USD", raw.upper()
    try:
        from ..markets import symbols as mksym

        ref = mksym.parse(raw)
        market, currency, symbol = ref.market, ref.currency, ref.symbol
    except Exception:  # noqa: BLE001  解析失败不阻断行情
        pass

    price = _price(row.get("price")) or 0.0
    bid = _price(row.get("bid"))
    ask = _price(row.get("ask"))
    prev_close = _price(row.get("prev_close")) or 0.0
    open_ = _price(row.get("open")) or price
    high = _price(row.get("day_high")) or price
    low = _price(row.get("day_low")) or price

    return Tick(
        symbol=symbol,
        price=price,
        bid=bid,
        ask=ask,
        bid_size=_num(row.get("bid_size")),
        ask_size=_num(row.get("ask_size")),
        last_size=_num(row.get("last_size")),
        volume=_num(row.get("volume")),
        open=open_,
        high=high,
        low=low,
        prev_close=prev_close,
        currency=currency,
        market=market,
        source=source or str(row.get("source") or "unknown"),
        ts=str(row.get("ts") or ""),
        recv_ns=time.monotonic_ns(),
    )


# ======================================================================
# 逐标的订阅状态
# ======================================================================
@dataclass
class SymbolState:
    symbol: str
    market: str = "US"
    currency: str = "USD"
    mode: str = MODE_OFFLINE
    refs: int = 0                 # 引用计数：0 时才会真正取消订阅
    tick: Tick | None = None
    error: str = ""
    opened_at: float = 0.0
    last_push_ns: int = 0
    pushes: int = 0
    snapshot_fallbacks: int = 0   # 流式失联后用快照兜底的次数
    stale_polls: int = 0          # 连续多少次轮询没拿到新数据

    def age_ms(self) -> float:
        if not self.last_push_ns:
            return float("inf")
        return (time.monotonic_ns() - self.last_push_ns) / 1e6

    def as_dict(self) -> dict[str, Any]:
        d = {
            "symbol": self.symbol, "market": self.market, "currency": self.currency,
            "mode": self.mode, "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "refs": self.refs, "pushes": self.pushes,
            "age_ms": None if not self.last_push_ns else round(self.age_ms(), 1),
            "error": self.error,
        }
        if self.tick is not None:
            d["tick"] = self.tick.as_dict()
        return d


# ======================================================================
# 订阅者（可推可拉）
# ======================================================================
class Subscriber:
    """一个行情消费者。

    · 给了 `loop` → 推送模式：`_offer` 通过 `call_soon_threadsafe` 投递到该 loop，
      用 `await sub.get()` 消费。
    · 没给 `loop` → 拉取模式：`_offer` 直接写内存，用 `sub.drain()` 消费。

    无论哪种模式，**同一标的只保留最新一条**（last-value-wins）。
    行情是「当前状态」而不是「消息流」，积压旧报价毫无意义且会放大延迟。
    """

    __slots__ = (
        "id", "symbols", "loop", "on_tick", "maxlen", "created_ns", "closed",
        "_pending", "_signal", "delivered", "coalesced", "overflow",
    )

    def __init__(
        self,
        sid: str,
        symbols: list[str],
        loop: asyncio.AbstractEventLoop | None = None,
        on_tick: Callable[[Tick], None] | None = None,
        maxlen: int = 256,
    ) -> None:
        self.id = sid
        self.symbols: set[str] = {str(s).upper() for s in symbols}
        self.loop = loop
        self.on_tick = on_tick
        self.maxlen = max(1, int(maxlen))
        self.created_ns = time.monotonic_ns()
        self.closed = False
        self._pending: dict[str, Tick] = {}
        self._signal: asyncio.Queue | None = None
        if loop is not None:
            self._signal = asyncio.Queue(maxsize=1)
        self.delivered = 0
        self.coalesced = 0
        self.overflow = 0

    # ---------------- 投递 ----------------
    def offer(self, tick: Tick) -> None:
        """线程安全投递入口（可能从 IB 事件线程调用）。"""
        if self.closed:
            return
        loop = self.loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self._offer, tick)
            except RuntimeError:
                # 目标 loop 已关闭（WebSocket 断开）→ 自动回收
                self.closed = True
            return
        self._offer(tick)

    def _offer(self, tick: Tick) -> None:
        if self.closed:
            return
        symbol = tick.symbol
        if symbol in self._pending:
            self._pending[symbol] = tick
            self.coalesced += 1
            return
        if len(self._pending) >= self.maxlen:
            try:
                self._pending.pop(next(iter(self._pending)))
            except (StopIteration, KeyError):  # pragma: no cover
                pass
            self.overflow += 1
        self._pending[symbol] = tick
        sig = self._signal
        if sig is not None:
            try:
                sig.put_nowait(1)
            except asyncio.QueueFull:
                # 已有唤醒信号在队列里，消费方醒来时会看到 _pending 非空
                pass
        if self.on_tick is not None:
            try:
                self.on_tick(tick)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- 消费 ----------------
    async def get(self, timeout: float | None = None) -> Tick | None:
        """取一条最新 tick；超时返回 None（不是异常，便于 `while` 循环里做心跳）。"""
        if self._signal is None:
            raise RuntimeError("该订阅者以拉取模式创建（无事件循环），请改用 drain()")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._pending:
                sym = next(iter(self._pending))
                t = self._pending.pop(sym, None)
                if t is not None:
                    self.delivered += 1
                    return t
                continue
            if self.closed:
                return None
            wait = None
            if deadline is not None:
                wait = deadline - time.monotonic()
                if wait <= 0:
                    return None
            try:
                await asyncio.wait_for(self._signal.get(), wait)
            except asyncio.TimeoutError:
                return None

    def drain(self) -> list[Tick]:
        """拉取全部待消费 tick（按接收时间排序）。拉取模式下的消费方式。"""
        if not self._pending:
            return []
        items = sorted(self._pending.values(), key=lambda t: t.recv_ns)
        self._pending.clear()
        self.delivered += len(items)
        return items

    def discard(self) -> int:
        """丢弃尚未消费的 tick（不计入 delivered）。

        用途：消费者只关心「从此刻起」的行情。例如前端刚连上时先收到一帧基线快照，
        随后只想看增量推送，就可以先 `discard()` 一次。
        """
        n = len(self._pending)
        self._pending.clear()
        return n

    def __aiter__(self) -> "Subscriber":
        return self

    async def __anext__(self) -> Tick:
        while True:
            t = await self.get(timeout=15.0)
            if t is not None:
                return t
            if self.closed:
                raise StopAsyncIteration

    def close(self) -> None:
        self.closed = True
        self._pending.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "id": self.id, "symbols": sorted(self.symbols),
            "mode": "push" if self._signal is not None else "pull",
            "delivered": self.delivered, "coalesced": self.coalesced,
            "overflow": self.overflow, "pending": len(self._pending),
            "closed": self.closed,
            "age_sec": round((time.monotonic_ns() - self.created_ns) / 1e9, 1),
        }


# ======================================================================
# 统计
# ======================================================================
class HubStats:
    """中枢运行统计。环形缓冲保存最近 N 个采样，用于算延迟分位数。"""

    def __init__(self, window: int = 512) -> None:
        self.ticks_in = 0
        self.ticks_pushed = 0
        self.cycles = 0
        self.cycles_failed = 0
        self.subscribe_calls = 0
        self.subscribe_ok = 0
        self.snapshot_calls = 0
        self.snapshot_rows = 0
        self.broker_errors = 0
        self.last_error = ""
        self.started_at = 0.0
        self.poll_ms: deque[float] = deque(maxlen=window)
        self.snapshot_ms: deque[float] = deque(maxlen=window)
        self.tick_gap_ms: deque[float] = deque(maxlen=window)

    @staticmethod
    def _pct(buf: deque[float], q: float) -> float:
        if not buf:
            return 0.0
        xs = sorted(buf)
        idx = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        return round(xs[idx], 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticks_in": self.ticks_in,
            "ticks_pushed": self.ticks_pushed,
            "cycles": self.cycles,
            "cycles_failed": self.cycles_failed,
            "subscribe_calls": self.subscribe_calls,
            "subscribe_ok": self.subscribe_ok,
            "snapshot_calls": self.snapshot_calls,
            "snapshot_rows": self.snapshot_rows,
            "broker_errors": self.broker_errors,
            "last_error": self.last_error,
            "uptime_sec": round(time.monotonic() - self.started_at, 1) if self.started_at else 0.0,
            "poll_ms": {
                "p50": self._pct(self.poll_ms, 0.50),
                "p95": self._pct(self.poll_ms, 0.95),
                "max": round(max(self.poll_ms), 2) if self.poll_ms else 0.0,
            },
            "snapshot_ms": {
                "p50": self._pct(self.snapshot_ms, 0.50),
                "p95": self._pct(self.snapshot_ms, 0.95),
                "max": round(max(self.snapshot_ms), 2) if self.snapshot_ms else 0.0,
            },
            "tick_gap_ms": {
                "p50": self._pct(self.tick_gap_ms, 0.50),
                "p95": self._pct(self.tick_gap_ms, 0.95),
                "max": round(max(self.tick_gap_ms), 2) if self.tick_gap_ms else 0.0,
            },
        }


def _iso_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()
