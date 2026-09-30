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

FILE_SIZE_DEBT Batch E-3：数据类型与工具（SymbolState / Subscriber / HubStats /
tick_from_quote 等）拆至 `stream_types.py`，旧 import 路径经 re-export 保持不变；
轮询线程（_poller/_cycle/_try_stream）与报价查询（quotes/_fetch_now/refresh）
分别拆至 `stream_poll.py` / `stream_quotes.py` 的 mixin。
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable

from ..brokers.base import Tick
from . import latency as _lat
from .stream_types import (  # noqa: F401  re-export 保持旧 import 路径
    MODE_LABELS,
    MODE_OFFLINE,
    MODE_SNAPSHOT,
    MODE_STREAM,
    MODE_SYNTHETIC,
    SOURCE_STREAM,
    HubStats,
    Subscriber,
    SymbolState,
    _DOWNGRADE_AFTER_STALE,
    _iso_now,
    _num,
    _price,
    tick_from_quote,
)
from .stream_poll import _PollMixin
from .stream_quotes import _QuoteMixin

# 行情年龄计算含多次 strptime，较贵（µs 级）；在热路径上按 1/64 采样，
# 分布形状不会失真，但不会拖慢推送本身。
_AGE_SAMPLE_MASK = 63


# ======================================================================
# 中枢
# ======================================================================
class MarketDataHub(_PollMixin, _QuoteMixin):
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
