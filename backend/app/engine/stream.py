"""行情中枢（MarketDataHub）—— 全进程唯一的流式行情订阅、缓存与分发。

为什么需要它
------------
重构前的行情路径是「谁要用谁去问券商」：

    WebSocket 每个客户端 → broker.quotes(syms) → IB reqTickersAsync（超时 40s）
    实时引擎每个 tick    → broker.quotes(syms) → 再来一次
    前端 REST 轮询       → 再来一次

同一份 AAPL 报价，三个消费者就是三次 IB 往返。10 个标的 × 3 个消费者 × 每次
最坏 4 次请求，几百毫秒内就能打满 IB 的 50 msg/s 配额并触发断连。
更致命的是：**每次都要等网络往返**，与「毫秒级完成交易」完全不相容。

中枢把这件事收敛成一条路径：

    reqMktData 一次订阅 ──► 券商推送 ──► hub.push(tick) ──► 内存缓存（唯一真源）
                                                      └──► 广播给所有订阅者

于是：
  · `latest(symbol)` 是**纯内存字典读取**，实测 < 1µs，可被事件驱动引擎每 tick 调用；
  · WebSocket 不再逐个请求券商，只做「读缓存 + 推送」；
  · 新增消费者不产生任何新的 IB 请求（引用计数管理订阅生命周期）。

三种模式
--------
| 模式       | 含义                                       | 触发条件                       |
|-----------|--------------------------------------------|-------------------------------|
| `stream`  | 券商主动推送（IBKR reqMktData）             | broker.supports_streaming 且订阅成功 |
| `snapshot`| 快照轮询（延迟行情 / 只会快照的券商）        | 无流式权限，或流式长时间失联       |
| `synthetic`| 合成行情（**非真实数据**，前端必须告警）     | 所有真实数据源都不可用            |

`mode` 是逐标的的，不是全局的 —— 港股可能没有 L2 权限而美股有，这很常见。

线程模型
--------
中枢拥有一个后台轮询线程（`qd-mdhub`），它负责：
  · 为还没流式的标的申请流式订阅
  · 为流式失联的标的做快照兜底
  · 为纯快照标的定期刷新

推送路径（`push`）完全无锁：读字典 + 更新对象字段 + 遍历订阅者，
每步都是 GIL 下的原子操作，因此可以从 IB 事件线程直接高频调用。
只有「订阅生命周期」（新增/释放标的）才会拿锁，那是一条低频路径。
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from ..brokers.base import Tick
from . import latency as _lat

# 行情年龄计算含多次 strptime，较贵（µs 级）；在热路径上按 1/64 采样，
# 分布形状不会失真，但不会拖慢推送本身。
_AGE_SAMPLE_MASK = 63

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


# ======================================================================
# 中枢
# ======================================================================
class MarketDataHub:
    """行情中枢。正常使用方式是 `get_hub()` 取进程内单例。"""

    def __init__(
        self,
        poll_interval: float = 2.0,
        stale_after: float = 8.0,
        broker_ttl: float = 5.0,
        max_snapshot_batch: int = 40,
    ) -> None:
        self.poll_interval = max(0.2, float(poll_interval))
        self.stale_after = max(1.0, float(stale_after))
        self.broker_ttl = max(0.5, float(broker_ttl))
        self.max_snapshot_batch = max(1, int(max_snapshot_batch))

        self._symbols: dict[str, SymbolState] = {}
        self._subs: dict[str, Subscriber] = {}
        self._subs_by_symbol: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._seq_lock = threading.Lock()

        self._broker: Any = None
        self._broker_provider = ""
        self._broker_at = 0.0
        self._attached_tick_sink: Any = None

        self.stats = HubStats()

    # ================================================================
    # 生命周期
    # ================================================================
    def start(self) -> "MarketDataHub":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self.stats.started_at = time.monotonic()
        self._thread = threading.Thread(target=self._poller, name="qd-mdhub", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ================================================================
    # 券商绑定
    # ================================================================
    def _resolve_broker(self) -> tuple[Any, str]:
        """取当前券商（带 TTL 缓存，避免每轮都读设置表）。"""
        now = time.monotonic()
        if self._broker is not None and now - self._broker_at < self.broker_ttl:
            return self._broker, self._broker_provider
        broker, provider = None, ""
        try:
            from .. import state as appstate
            from ..brokers import get_broker

            cfg = appstate.get_broker_settings()
            provider = str(cfg.get("provider", "simulated"))
            broker, _mode = get_broker(cfg)
        except Exception as exc:  # noqa: BLE001
            self.stats.broker_errors += 1
            self.stats.last_error = f"券商解析失败：{type(exc).__name__}: {exc}"
            broker, provider = None, ""
        self._broker, self._broker_provider, self._broker_at = broker, provider, now
        self._attach_sink(broker)
        return broker, provider

    def _attach_sink(self, broker: Any) -> None:
        """把 `self.push` 注入券商的 tick 回调槽，实现推送直达（零轮询）。"""
        if broker is None:
            return
        if broker is self._attached_tick_sink:
            return
        try:
            if hasattr(broker, "tick_sink"):
                broker.tick_sink = self.push
                self._attached_tick_sink = broker
        except Exception:  # noqa: BLE001
            pass

    def invalidate_broker(self) -> None:
        """券商设置变更后调用，下一轮立即重新解析。"""
        self._broker = None
        self._broker_at = 0.0

    # ================================================================
    # 订阅生命周期（低频路径，加锁）
    # ================================================================
    def ensure(self, symbols: list[str], market: bool = True) -> list[str]:
        """确保这些标的已被订阅（引用计数 +1）。返回**规范化后**的标的列表。

        `market=False` 时只登记不建行情（用于「只是想记住」的场景）。
        """
        from ..markets import symbols as mksym

        canonical: list[str] = []
        with self._lock:
            for raw in symbols or []:
                market_code, currency = "US", "USD"
                try:
                    ref = mksym.parse(raw)
                    sym = ref.symbol
                    market_code, currency = ref.market, ref.currency
                except Exception:  # noqa: BLE001
                    sym = str(raw or "").strip().upper()
                if not sym:
                    continue
                st = self._symbols.get(sym)
                if st is None:
                    st = SymbolState(symbol=sym, market=market_code, currency=currency)
                    self._symbols[sym] = st
                st.refs += 1
                canonical.append(sym)
        if market and canonical:
            self._wake.set()
        return canonical

    def release(self, symbols: list[str]) -> None:
        """引用计数 -1；归零后真正退订并释放内存。"""
        from ..markets import symbols as mksym

        drop: list[str] = []
        with self._lock:
            for raw in symbols or []:
                try:
                    sym = mksym.parse(raw).symbol
                except Exception:  # noqa: BLE001
                    sym = str(raw or "").strip().upper()
                st = self._symbols.get(sym)
                if st is None:
                    continue
                st.refs = max(0, st.refs - 1)
                if st.refs == 0:
                    drop.append(sym)
        if drop:
            self._unsubscribe(drop)
            with self._lock:
                for sym in drop:
                    self._symbols.pop(sym, None)

    def _unsubscribe(self, symbols: list[str]) -> None:
        broker, _ = self._resolve_broker()
        if broker is None:
            return
        try:
            broker.unsubscribe(symbols)
        except Exception as exc:  # noqa: BLE001
            self.stats.broker_errors += 1
            self.stats.last_error = f"退订失败：{type(exc).__name__}: {exc}"

    def tracked_symbols(self) -> list[str]:
        with self._lock:
            return sorted(self._symbols)

    # ================================================================
    # 读路径（高频，无锁）
    # ================================================================
    def latest(self, symbol: str) -> Tick | None:
        """读本地缓存的最新 tick —— **纯内存，无 IO，无锁**。"""
        sym = str(symbol or "").strip().upper()
        st = self._symbols.get(sym)
        if st is not None:
            return st.tick
        # 容忍未规范化的写法（0700 / 0700.HK / 700）
        try:
            from ..markets import symbols as mksym

            ref = mksym.parse(symbol)
            st = self._symbols.get(ref.symbol)
            if st is not None:
                return st.tick
        except Exception:  # noqa: BLE001
            pass
        return None

    def latest_many(self, symbols: list[str]) -> dict[str, Tick]:
        out: dict[str, Tick] = {}
        for s in symbols or []:
            t = self.latest(s)
            if t is not None:
                out[t.symbol] = t
        return out

    def price(self, symbol: str, fallback: float = 0.0) -> float:
        t = self.latest(symbol)
        if t is None or t.price <= 0:
            return fallback
        return t.price

    def age_ms(self, symbol: str) -> float:
        st = self._symbols.get(str(symbol or "").strip().upper())
        return st.age_ms() if st is not None else float("inf")

    def mode_of(self, symbol: str) -> str:
        st = self._symbols.get(str(symbol or "").strip().upper())
        return st.mode if st is not None else MODE_OFFLINE

    def state_of(self, symbol: str) -> SymbolState | None:
        return self._symbols.get(str(symbol or "").strip().upper())

    # ================================================================
    # 写路径（IB 事件线程高频调用 → 必须无锁）
    # ================================================================
    def push(self, tick: Tick) -> None:
        """接收一条行情。

        这是热路径：只在字典里查一次、更新对象字段、遍历少量订阅者。
        任何异常都必须吞掉 —— 券商线程不能被行情消费方拖垮。
        """
        sym = tick.symbol
        st = self._symbols.get(sym)
        if st is None:
            # 未登记的标的（例如券商推送了我们没订阅的）→ 丢弃，不计入任何埋点
            return
        t0 = time.perf_counter_ns()
        try:
            with self._seq_lock:
                self._seq += 1
                tick.seq = self._seq

            if not tick.recv_ns:
                tick.recv_ns = time.monotonic_ns()
            if not tick.currency:
                tick.currency = st.currency
            if not tick.market:
                tick.market = st.market

            prev_ns = st.last_push_ns
            if prev_ns:
                self.stats.tick_gap_ms.append((tick.recv_ns - prev_ns) / 1e6)

            src = tick.source
            if src != SOURCE_STREAM:
                # 新鲜流式数据优先：快照 / 合成行情不得覆盖它。
                # 存在的必要性：`_cycle` 在 T 时刻判定「需要兜底」，`_fetch_now` 返回时
                # 可能已经过去了几十毫秒，期间券商可能已推来新价 —— 那条快照是**更旧**
                # 的信息，却因为创建时间更晚而看似更新，会把实时价冲成延迟价。
                cur = st.tick
                if (cur is not None and cur.source == SOURCE_STREAM
                        and st.age_ms() <= self.stale_after * 1000.0):
                    return

            if src == SOURCE_STREAM:
                st.mode = MODE_STREAM
                st.stale_polls = 0
                st.snapshot_fallbacks = 0
                st.error = ""
            elif src == "synthetic":
                st.mode = MODE_SYNTHETIC
                st.error = "所有真实数据源均不可用，当前为合成行情"
            else:
                # 快照来源：如果之前是流式，累计「失联」次数，达阈值才降级
                if st.mode == MODE_STREAM:
                    st.snapshot_fallbacks += 1
                    if st.snapshot_fallbacks >= _DOWNGRADE_AFTER_STALE:
                        st.mode = MODE_SNAPSHOT
                        st.error = "流式行情长时间无推送，已降级为快照轮询"
                elif st.mode in (MODE_OFFLINE, MODE_SYNTHETIC):
                    st.mode = MODE_SNAPSHOT
                    if src == "synthetic":
                        st.mode = MODE_SYNTHETIC

            st.tick = tick
            st.last_push_ns = tick.recv_ns
            st.pushes += 1
            self.stats.ticks_in += 1

            ids = self._subs_by_symbol.get(sym)
            if ids:
                subs = self._subs
                for sid in list(ids):
                    sub = subs.get(sid)
                    if sub is None:
                        continue
                    if not sub.symbols:
                        continue
                    sub.offer(tick)
                    self.stats.ticks_pushed += 1
        except Exception:  # noqa: BLE001
            pass
        finally:
            # ---- 延迟埋点 ----
            try:
                _lat.get_latency().record_ns(
                    _lat.TICK_PUBLISH, time.perf_counter_ns() - t0
                )
                n = self.stats.ticks_in
                if n & _AGE_SAMPLE_MASK == 0:
                    age = _lat.quote_age_ms(tick.ts, tick.recv_ns)
                    if age is not None and -1000.0 < age < 86_400_000.0:
                        _lat.get_latency().record(_lat.QUOTE_AGE, age)
            except Exception:  # noqa: BLE001
                pass

    # ================================================================
    # 订阅者管理
    # ================================================================
    def subscribe_events(
        self,
        symbols: list[str],
        loop: asyncio.AbstractEventLoop | None = None,
        on_tick: Callable[[Tick], None] | None = None,
        sid: str = "",
        maxlen: int = 256,
        ensure: bool = True,
    ) -> Subscriber:
        """创建一个订阅者。

        `ensure=True`（默认）会顺带把这些标的加进中枢订阅（引用计数 +1）。
        **调用方不要再额外调 `ensure()`** —— 那会让计数加两次，退订只减一次，
        订阅就永久泄漏。若你已经自己 `ensure()` 过，传 `ensure=False`。
        无论哪种情况，`unsubscribe_events(release=True)` 都会对称地释放。
        """
        canonical = self.ensure(symbols) if ensure else [
            str(s or "").strip().upper() for s in symbols or []
        ]
        if not sid:
            sid = f"sub-{int(time.time()*1000)}-{len(self._subs)+1}"
        sub = Subscriber(sid, canonical, loop=loop, on_tick=on_tick, maxlen=maxlen)
        with self._lock:
            self._subs[sid] = sub
            for sym in canonical:
                self._subs_by_symbol.setdefault(sym, set()).add(sid)
            # 把已有的缓存立刻推一份给新订阅者，避免首帧空白
            for sym in canonical:
                st = self._symbols.get(sym)
                if st is not None and st.tick is not None:
                    sub._offer(st.tick)
        self.start()
        return sub

    def unsubscribe_events(self, sid: str, release: bool = True) -> None:
        with self._lock:
            sub = self._subs.pop(sid, None)
            if sub is None:
                return
            syms = sorted(sub.symbols)
            for sym in syms:
                ids = self._subs_by_symbol.get(sym)
                if ids:
                    ids.discard(sid)
                    if not ids:
                        self._subs_by_symbol.pop(sym, None)
        sub.close()
        if release:
            self.release(syms)

    def subscriber_stats(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.stats() for s in self._subs.values()]

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    # ================================================================
    # 对外报价查询（兼容旧接口的字典格式）
    # ================================================================
    def quotes(self, symbols: list[str], ensure: bool = True, allow_fetch: bool = True) -> list[dict]:
        """返回统一报价字典列表。

        优先用内存缓存；对完全没有数据的标的，必要时同步取一次（`allow_fetch`）。
        这样前端首屏不会被「等第一帧推送」拖住。
        """
        if ensure:
            self.ensure(symbols)
        rows: list[dict] = []
        missing: list[str] = []
        for s in symbols or []:
            t = self.latest(s)
            if t is None or (t.price <= 0 and t.mode != MODE_STREAM):
                missing.append(str(s))
                continue
            rows.append(self._tick_to_quote(t))
        if missing and allow_fetch:
            for t in self._fetch_now(missing):
                rows.append(self._tick_to_quote(t))
        return rows

    def quote(self, symbol: str) -> dict:
        rows = self.quotes([symbol])
        if rows:
            return rows[0]
        return {
            "symbol": str(symbol or "").strip().upper(), "price": 0.0,
            "source": "none", "mode": MODE_OFFLINE,
        }

    @staticmethod
    def _tick_to_quote(t: Tick) -> dict[str, Any]:
        """Tick → 旧版报价字典（保持前端字段兼容）。"""
        change = (t.price - t.prev_close) if (t.prev_close and t.price) else 0.0
        return {
            "symbol": t.symbol,
            "price": round(t.price, 4),
            "prev_close": round(t.prev_close, 4),
            "change": round(change, 4),
            "change_pct": round(change / t.prev_close * 100, 3) if t.prev_close else 0.0,
            "volume": t.volume,
            "day_high": round(t.high, 4),
            "day_low": round(t.low, 4),
            "open": round(t.open, 4),
            "bid": t.bid,
            "ask": t.ask,
            "bid_size": t.bid_size,
            "ask_size": t.ask_size,
            "spread_bps": round(t.spread_bps, 3),
            "currency": t.currency,
            "market": t.market,
            "ts": t.ts or "",
            "recv_ns": t.recv_ns,
            "source": t.source,
            "mode": MODE_SNAPSHOT if t.source != SOURCE_STREAM else MODE_STREAM,
        }

    def _fetch_now(self, symbols: list[str]) -> list[Tick]:
        """同步取一次报价（券商优先 → data_provider 降级链）。"""
        out: list[Tick] = []
        if not symbols:
            return out
        t0 = time.perf_counter()
        self.stats.snapshot_calls += 1
        broker, _prov = self._resolve_broker()
        rows: list[dict] = []
        if broker is not None and getattr(broker, "connected", False):
            try:
                rows = broker.snapshot(list(symbols)) or []
            except Exception as exc:  # noqa: BLE001
                self.stats.broker_errors += 1
                self.stats.last_error = f"券商快照失败：{type(exc).__name__}: {exc}"
        have = {str(r.get("symbol", "")).upper() for r in rows if _num(r.get("price")) > 0}
        missing = [s for s in symbols if str(s).upper() not in have]
        if missing:
            try:
                from ..data_provider import get_quotes

                rows = list(rows) + list(get_quotes(missing) or [])
            except Exception as exc:  # noqa: BLE001
                self.stats.last_error = f"备用行情源失败：{type(exc).__name__}: {exc}"
        for r in rows:
            try:
                out.append(tick_from_quote(r))
            except Exception:  # noqa: BLE001
                continue
        self.stats.snapshot_rows += len(out)
        ms = (time.perf_counter() - t0) * 1000
        self.stats.snapshot_ms.append(ms)
        _lat.get_latency().record(_lat.SNAPSHOT, ms)
        return out

    def refresh(self, symbols: list[str] | None = None) -> int:
        """主动拉一次快照并写入缓存（阻塞）。返回写入条数。"""
        syms = symbols if symbols is not None else self.tracked_symbols()
        ticks = self._fetch_now(syms)
        for t in ticks:
            if self._symbols.get(t.symbol) is not None:
                self.push(t)
        return len(ticks)

    # ================================================================
    # 后台轮询线程
    # ================================================================
    def _poller(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                self._cycle()
            except Exception as exc:  # noqa: BLE001
                self.stats.cycles_failed += 1
                self.stats.last_error = f"轮询异常：{type(exc).__name__}: {exc}"
            self.stats.cycles += 1
            self.stats.poll_ms.append((time.perf_counter() - t0) * 1000)
            _lat.get_latency().record(_lat.HUB_POLL, (time.perf_counter() - t0) * 1000)
            self._wake.wait(self.poll_interval)
            self._wake.clear()

    def _cycle(self) -> None:
        syms = self.tracked_symbols()
        if not syms:
            return

        # 1) 为还没建立流式的标的申请推送订阅
        want = [s for s in syms if self._symbols[s].mode != MODE_STREAM]
        if want:
            got = self._try_stream(want)
            for sym in got:
                st = self._symbols.get(sym)
                if st is not None and st.mode != MODE_STREAM:
                    st.mode = MODE_STREAM
                    st.error = ""

        # 2) 收集需要快照刷新/兜底的标的
        stale_ms = self.stale_after * 1000
        need = []
        for sym in syms:
            st = self._symbols.get(sym)
            if st is None:
                continue
            if st.mode == MODE_STREAM and st.age_ms() <= stale_ms:
                continue
            if st.tick is not None and st.mode != MODE_OFFLINE and st.age_ms() <= self.poll_interval * 1000 * 0.4:
                continue      # 刚取过，别浪费 IB 配额
            need.append(sym)
        if not need:
            return

        # 3) 分批取快照（避免一次几十个标的把 IB 打满）
        for i in range(0, len(need), self.max_snapshot_batch):
            chunk = need[i:i + self.max_snapshot_batch]
            for t in self._fetch_now(chunk):
                st = self._symbols.get(t.symbol)
                if st is None:
                    continue
                if st.mode == MODE_STREAM:
                    st.snapshot_fallbacks += 1
                    if st.snapshot_fallbacks >= _DOWNGRADE_AFTER_STALE:
                        st.mode = MODE_SNAPSHOT
                        st.error = "流式行情长时间无推送，已降级为快照轮询"
                self.push(t)

    def _try_stream(self, symbols: list[str]) -> set[str]:
        """向券商申请流式订阅，返回真正建立成功的标的集合。"""
        broker, _prov = self._resolve_broker()
        if broker is None:
            return set()
        if not getattr(broker, "supports_streaming", False):
            return set()
        if not getattr(broker, "connected", False):
            return set()
        self.stats.subscribe_calls += 1
        try:
            ok = bool(broker.subscribe(list(symbols)))
        except Exception as exc:  # noqa: BLE001
            self.stats.broker_errors += 1
            self.stats.last_error = f"流式订阅失败：{type(exc).__name__}: {exc}"
            return set()
        if not ok:
            return set()
        self.stats.subscribe_ok += 1
        try:
            got = {str(s).upper() for s in (broker.streamed_symbols() or [])}
        except Exception:  # noqa: BLE001
            got = set()
        return got & {str(s).upper() for s in symbols}

    # ================================================================
    # 状态
    # ================================================================
    def status(self) -> dict[str, Any]:
        with self._lock:
            states = list(self._symbols.values())
            subs = len(self._subs)
        by_mode: dict[str, list[str]] = {MODE_STREAM: [], MODE_SNAPSHOT: [],
                                         MODE_SYNTHETIC: [], MODE_OFFLINE: []}
        for st in states:
            by_mode.setdefault(st.mode, []).append(st.symbol)
        broker, provider = self._resolve_broker()
        warnings: list[str] = []
        if by_mode.get(MODE_SYNTHETIC):
            warnings.append(
                f"{len(by_mode[MODE_SYNTHETIC])} 个标的为合成行情（非真实数据）："
                + "、".join(by_mode[MODE_SYNTHETIC][:6])
            )
        if by_mode.get(MODE_STREAM) and broker is not None and not getattr(broker, "connected", False):
            warnings.append("券商已断开，流式行情随时可能中断")
        return {
            "running": self.running,
            "poll_interval_sec": self.poll_interval,
            "stale_after_sec": self.stale_after,
            "subscribers": subs,
            "symbol_count": len(states),
            "streaming": sorted(by_mode.get(MODE_STREAM, [])),
            "snapshot": sorted(by_mode.get(MODE_SNAPSHOT, [])),
            "synthetic": sorted(by_mode.get(MODE_SYNTHETIC, [])),
            "offline": sorted(by_mode.get(MODE_OFFLINE, [])),
            "mode_labels": MODE_LABELS,
            "broker": {
                "provider": provider,
                "connected": bool(getattr(broker, "connected", False)) if broker else False,
                "supports_streaming": bool(getattr(broker, "supports_streaming", False)) if broker else False,
            },
            "warnings": warnings,
            "stats": self.stats.as_dict(),
            "checked_at": _iso_now(),
        }

    def symbol_table(self) -> list[dict[str, Any]]:
        with self._lock:
            return [st.as_dict() for st in sorted(self._symbols.values(), key=lambda x: x.symbol)]

    def reset(self) -> None:
        """清空全部订阅状态（测试/切换券商时用）。"""
        with self._lock:
            for sub in self._subs.values():
                sub.close()
            self._subs.clear()
            self._subs_by_symbol.clear()
            self._symbols.clear()
        self.stats = HubStats()
        self.stats.started_at = time.monotonic()


def _iso_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ======================================================================
# 进程内单例
# ======================================================================
_hub: MarketDataHub | None = None
_hub_lock = threading.Lock()


def get_hub() -> MarketDataHub:
    global _hub
    if _hub is None:
        with _hub_lock:
            if _hub is None:
                _hub = MarketDataHub()
                _hub.start()
    return _hub


def shutdown_hub() -> None:
    global _hub
    with _hub_lock:
        if _hub is not None:
            _hub.stop()
            _hub = None


__all__ = [
    "MarketDataHub", "Subscriber", "SymbolState", "HubStats",
    "get_hub", "shutdown_hub", "tick_from_quote",
    "MODE_STREAM", "MODE_SNAPSHOT", "MODE_SYNTHETIC", "MODE_OFFLINE",
    "MODE_LABELS", "SOURCE_STREAM",
]
