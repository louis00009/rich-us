"""
IBKR 券商适配层（基于 ib_async）
=================================
连接目标：
    TWS  纸面 127.0.0.1:7497   |  TWS  实盘 127.0.0.1:7496
    Gateway 纸面 127.0.0.1:4002 |  Gateway 实盘 127.0.0.1:4001

本文件负责五件事：
  1. 连接管理（专属事件循环线程，避免与 FastAPI 的 loop 互相干扰）
  2. **流式行情** —— reqMktData 推送 + 本地 tick 缓存（`get_tick` 无 IO，供事件驱动引擎高频调用）
     以及 reqTickers 快照兜底（无流式权限时）
  3. 历史 K 线 —— reqHistoricalData 自动分页突破 IB 单次时长限制
  4. 账户与持仓 —— ib.portfolio() 取真实市价/浮盈/已实现盈亏（多币种折算）
  5. 下单与回报 —— OCO 止盈止损、事件驱动成交确认、异步落库

市场覆盖
--------
合约一律经 `markets.symbols.parse()` 解析，支持美股与港股：
    0700.HK / 700 / 0700  →  Stock("700",  "SEHK", "HKD")  primaryExchange=SEHK
    AAPL                  →  Stock("AAPL", "SMART", "USD") primaryExchange=NASDAQ
不再硬编码 SMART + USD。

延迟设计（关键）
----------------
- `place_order` **不再 sleep**。旧实现每次下单固定 `sleep(0.8)`，一次 10 标的调仓
  就是 8 秒起步，与"毫秒级"完全矛盾。改为事件等待：订单号返回即可用，
  成交由 `orderStatusEvent` 异步回填。
- 所有 IB 调用经 `_call` / `_await` 提交到专属事件循环，超时大幅下调（默认 5s），
  并由 `pacing` 令牌桶限制消息速率（IB 硬限 50 msg/s，超限会被断连）。
- 事件回调内**只做内存更新**，持久化投递到后台写线程，避免阻塞 IB 事件线程。

实盘资金安全（三道锁）：
    锁 1  环境变量 QD_ALLOW_LIVE_TRADING=true（默认关闭）
    锁 2  风控表中的 live_unlocked 标记，需输入确认短语 + 账户口令解锁
    锁 3  每笔订单仍要穿过 risk.guardrails 的全部护栏
缺任意一道，实盘下单请求一律拒绝并写入审计日志。
"""
from __future__ import annotations


def _silent(exc: BaseException, where: str) -> None:
    """记录「几乎必然是代码缺陷」的异常（审查新-3）。

    本文件有十余处 `except Exception: pass/continue` —— 对券商 API 而言这是合理的
    容错策略（超时、限流、字段缺失都可能发生）。但它们会**连带吞掉代码缺陷**：
    项目历史上就因此漏掉过 `_from_yf` 的 NameError（静默、零输出、极难排查）。

    这里只对下面几类「基本只可能是 bug」的异常发声；网络/超时/业务异常保持静默，
    避免把日志刷成噪声。
    """
    if isinstance(exc, (NameError, UnboundLocalError, TypeError, AttributeError)):
        import logging

        logging.getLogger("quantdesk.ibkr").warning(
            "[ibkr] %s 吞掉疑似代码缺陷：%s: %s", where, type(exc).__name__, exc
        )

import asyncio
import concurrent.futures
import datetime as dt
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from ..markets import symbols as mksym
from ..markets.registry import get_market
from .base import AccountSnapshot, Broker, BrokerError, OrderResult, PositionItem, Tick
from .pacing import CircuitBreaker, Pacer

# ------------------------------------------------------------------
# 周期映射：我们的 interval → (IB barSize, 单次请求最大时长, 天数)
# IB 对「单次请求可覆盖的时长」有硬限制，超限会报错，因此需要分页拉取。
# ------------------------------------------------------------------
BAR_MAP: dict[str, tuple[str, str, int]] = {
    "1m": ("1 min", "1 D", 1),
    "2m": ("2 mins", "2 D", 2),
    "5m": ("5 mins", "1 W", 7),
    "15m": ("15 mins", "1 M", 30),
    "30m": ("30 mins", "1 M", 30),
    "1h": ("1 hour", "1 Y", 365),
    "1d": ("1 day", "1 Y", 365),
    "1wk": ("1 week", "1 Y", 365),
}

# 指数的 IB 合约标识（兼容旧的硬编码表；新代码走 markets.symbols）
INDEX_MAP: dict[str, tuple[str, str]] = {
    "^GSPC": ("SPX", "CBOE"),
    "^SPX": ("SPX", "CBOE"),
    "^NDX": ("NDX", "NASDAQ"),
    "^DJI": ("INDU", "CBOE"),
    "^VIX": ("VIX", "CBOE"),
    "^TNX": ("TNX", "CBOE"),
    "^RUT": ("RUT", "CBOE"),
}


@dataclass
class _ContractSpec:
    symbol: str
    sec_type: str
    exchange: str
    currency: str = "USD"
    primary_exchange: str | None = None
    market: str = "US"


def _apply_status_snapshot(row: Any, snap: dict) -> None:
    """把券商回报的状态快照写入订单行（仅覆盖非空字段）。"""
    if not snap:
        return
    if snap.get("status"):
        row.status = str(snap["status"])
    if snap.get("filled") is not None:
        row.filled_qty = float(snap["filled"])
    if snap.get("avg_price"):
        row.avg_fill_price = float(snap["avg_price"])


# 连接失败冷却（类级共享：TWS 关闭时避免每个调用路径都打 2s 超时连接风暴）
_CONNECT_COOLDOWN = 30.0
_connect_fail_until = 0.0


class IBKRBroker(Broker):
    name = "ibkr"
    supports_live = True
    supports_history = True
    supports_streaming = True

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 17,
        account: str = "",
        mode: str = "paper",
        readonly: bool = True,
        timeout: float = 8.0,
        market_data_type: int = 3,
        use_rth: bool = True,
        call_timeout: float = 5.0,
        fill_timeout: float = 2.0,
    ) -> None:
        super().__init__(mode=mode)
        self.host = host
        self.port = int(port)
        self.client_id = int(client_id)
        self.account_id = account
        self.readonly = bool(readonly)
        self.timeout = float(timeout)
        # 单次 IB 请求的等待上限。旧实现是 timeout+12 = 20s，一次抖动就把
        # FastAPI 的 anyio 线程池（上限 40）吃掉一大半。5s 足够 IB 正常应答。
        self.call_timeout = max(1.0, float(call_timeout))
        # 下单后等待「已提交/已成交」的上限。毫秒级目标下不该等太久，
        # 超时不算失败 —— 订单有 orderId 就说明 IB 已受理。
        self.fill_timeout = max(0.2, float(fill_timeout))
        # 1=实时 2=冻结 3=延迟 4=延迟冻结（无实时行情订阅时用 3）
        self.market_data_type = int(market_data_type)
        self.use_rth = bool(use_rth)

        self._ib: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()     # P1：_ensure_loop 并发创建竞态保护
        self._thread: threading.Thread | None = None
        self._connected = False
        self._last_error = ""
        self._summary_cache: dict[str, float] = {}
        self._contracts: dict[str, Any] = {}
        self._orders: dict[str, Any] = {}          # orderId → Trade
        self._pending_status: dict[str, dict] = {}  # orderId → 回调快照（订单行未落库时的缓冲）
        self._md_type_verified: int | None = None
        self._hist_calls = 0

        # ---------------- 流式行情 ----------------
        self._streams: dict[str, Any] = {}          # 展示代码 → ib_async Ticker
        self._ticks: dict[str, Tick] = {}           # 展示代码 → 最新 Tick（无 IO 读取）
        self._stream_lock = threading.RLock()
        self._stream_errors: dict[str, str] = {}

        # ---------------- pacing / 熔断 ----------------
        self._pacer = Pacer(rate=float(40), burst=20, max_wait=2.0)
        self._breaker = CircuitBreaker(fail_threshold=6, cooldown=6.0, half_open_trials=2)
        self._sub_slot = threading.BoundedSemaphore(8)   # IB 并发调用上限

        # ---------------- 成交回报（异步落库，绝不阻塞 IB 事件线程） ----------------
        self._registered: list[str] = []
        self._last_error_code = 0
        self._last_fill: dict[str, Any] = {}
        self._base_currency = "USD"
        self._positions_fx_estimated = False
        self._last_order_latency_ms: dict[str, Any] = {}
        self._exec_seen: set[str] = set()           # 已处理的 execId，防重复记账
        self._exec_seen_order: list[str] = []
        self._exec_lock = threading.Lock()
        self._fill_events: dict[str, threading.Event] = {}
        self._write_q: queue.Queue = queue.Queue(maxsize=4096)
        self._writer: threading.Thread | None = None
        self._writer_stop = threading.Event()
        self.stats = {
            "orders_placed": 0, "orders_rejected": 0, "fills_seen": 0,
            "events_dropped": 0, "errors_seen": 0, "pacing_waits": 0,
            "breaker_trips": 0, "subscribe_calls": 0, "unsubscribe_calls": 0,
            "ticks_pushed": 0, "call_timeouts": 0,
        }

    # ================================================================
    # 事件循环线程
    # ================================================================
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """返回常驻 IB 事件循环（首次调用时创建专属线程）。

        P1 修复（2026-09-24 服务日志实证）：旧实现无锁且 runner 闭包读共享的
        `self._loop` —— 两个请求线程并发进来时各自 new loop 并 start thread，
        后创建者覆盖 self._loop，于是**两个线程 run_forever 同一个循环对象**
        → "This event loop is already running"，ibkr-loop 线程崩溃，
        之后所有 _submit 全部超时。现在：加锁 + runner 绑定局部变量。
        """
        with self._loop_lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            self._loop = loop

            def runner(lo: asyncio.AbstractEventLoop = loop) -> None:
                asyncio.set_event_loop(lo)
                try:
                    lo.run_forever()
                except Exception:  # noqa: BLE001 —— 循环线程绝不能带异常静默死亡
                    self._connected = False
                    self._loop = None
                    self._thread = None

            self._thread = threading.Thread(target=runner, name="ibkr-loop", daemon=True)
            self._thread.start()
            # 等循环真正转起来，避免紧跟的 run_coroutine_threadsafe 打在未运行的循环上
            for _ in range(100):
                if loop.is_running():
                    break
                time.sleep(0.01)
            return loop

    def _call(self, fn: Callable, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        """
        在 IB 事件循环线程上执行「同步版」调用。

        仅适用于 ib_async 内部不做等待的方法（placeOrder / cancelOrder /
        reqMarketDataType / positions / portfolio / openTrades / fills / managedAccounts…），
        它们只是发消息或读缓存，不会触发 run_until_complete。
        需要等待的方法（connect / qualifyContracts / reqTickers /
        reqHistoricalData / accountSummary）必须走 _await。

        走这条路径的都必须先过 `_gate`（限流 + 熔断 + 并发闸），
        否则一次 10 标的调仓的并发提交会打满 IB 的 50 msg/s 配额并被断连。
        """

        async def _job() -> Any:
            return fn(*args, **kwargs)

        return self._submit(_job(), timeout=timeout if timeout is not None else self.call_timeout)

    def _await(self, coro: Any, timeout: float | None = None) -> Any:
        """
        提交一个协程到 IB 事件循环并等待结果。

        ib_async 的同步方法（如 IB.accountSummary）内部会调用 run_until_complete，
        而我们的循环正在 run_forever 中运行，直接调用会抛
        "This event loop is already running"。因此这些方法一律使用 Async 变体。
        """
        return self._submit(coro, timeout=timeout if timeout is not None else self.call_timeout)

    def _submit(self, coro: Any, timeout: float) -> Any:
        """统一的提交点：限流 → 熔断 → 并发闸 → 提交到 IB 循环。"""
        try:
            self._gate()
        except Exception:
            # P1：限流/熔断拒绝时，调用方已创建的协程对象会被丢弃 ——
            # 不显式 close() 会留下一堆 "coroutine was never awaited" 泄漏
            #（服务日志里 connectAsync 的 RuntimeWarning 即此根因）。
            close = getattr(coro, "close", None)
            if close:
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
            raise
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            result = fut.result(timeout=timeout)
        except (TimeoutError, concurrent.futures.TimeoutError):
            fut.cancel()
            self.stats["call_timeouts"] += 1
            self._breaker.record_failure(f"IB 调用超时（{timeout:.1f}s）")
            raise
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure(f"{type(exc).__name__}: {exc}")
            raise
        self._breaker.record_success()
        return result

    def _gate(self) -> None:
        """全局限流 + 熔断。IB 的 50 msg/s 是硬限制，超限直接断连。"""
        if not self._breaker.allow():
            raise BrokerError(
                f"IBKR 调用被熔断（连续失败 {self._breaker._fails} 次，"
                f"冷却 {self._breaker.cooldown:.0f}s）：{self._breaker.last_error}"
            )
        if not self._pacer.acquire(1):
            self.stats["pacing_waits"] += 1
            raise BrokerError("IBKR 消息速率已达上限（50 msg/s），本请求被限流拒绝")

    def _sleep(self, secs: float) -> None:
        """在 IB 循环上安全 sleep（不能用 ib.sleep，它内部会 run_until_complete）。"""
        try:
            loop = self._ensure_loop()
            fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(float(secs)), loop)
            fut.result(timeout=float(secs) + 2.0)
        except Exception as exc:  # noqa: BLE001 —— 睡不成不致命，但缺陷要留痕
            _silent(exc, "_sleep")

    # ================================================================
    # 连接管理
    # ================================================================
    def _import_ib(self):
        try:
            import ib_async
        except ImportError as exc:  # pragma: no cover
            raise BrokerError("未安装 ib_async。请执行： pip install ib_async") from exc
        return ib_async

    @property
    def connected(self) -> bool:
        try:
            return bool(self._connected and self._ib is not None and self._ib.isConnected())
        except Exception as exc:  # noqa: BLE001 —— 失败按「未连接」处理，但缺陷要留痕
            _silent(exc, "connected")
            return False

    def connect(self) -> tuple[bool, str]:
        global _connect_fail_until
        ib_async = self._import_ib()
        self._ensure_loop()
        if self._ib is None:
            self._ib = ib_async.IB()
            self._register_events()
        if self.connected:
            return True, "已连接"

        # 连接失败冷却：TWS 未运行时，connectAsync 每次都要 2s 超时——
        # 行情/报价的每条路径都重试会形成连接风暴（曾把 watchlist 拖到 8s、scan 88s）。
        # 失败后 30s 内直接拒绝重试，到点自动恢复。
        global _connect_fail_until
        now = time.time()
        if now < _connect_fail_until:
            remain = int(_connect_fail_until - now)
            return False, f"IBKR 连接冷却中（{remain}s 前连接失败，TWS 未运行？）"

        try:
            self._await(
                self._ib.connectAsync(
                    self.host, self.port,
                    clientId=self.client_id, timeout=self.timeout, readonly=self.readonly,
                ),
                timeout=self.timeout + 15,
            )
            self._connected = bool(self._ib.isConnected())
            if not self._connected:
                self._last_error = "连接失败：请确认 TWS / IB Gateway 已启动并开启 API 权限"
                _connect_fail_until = time.time() + _CONNECT_COOLDOWN
                return False, self._last_error

            try:
                if not self.account_id:
                    accts = self._call(self._ib.managedAccounts)
                    self.account_id = accts[0] if accts else ""
            except Exception:  # noqa: BLE001
                pass

            # 设定行情类型（延迟/实时）
            md_msg = self._apply_market_data_type(self.market_data_type)

            mode_txt = "实盘" if self.mode == "live" else "纸面"
            return True, (
                f"已连接 IBKR {mode_txt}账户 {self.account_id or '(未知)'} @ {self.host}:{self.port} · {md_msg}"
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"连接 IBKR 失败：{type(exc).__name__}: {exc}"
            self._connected = False
            _connect_fail_until = time.time() + _CONNECT_COOLDOWN
            return False, self._last_error

    def _apply_market_data_type(self, md_type: int) -> str:
        labels = {1: "实时行情", 2: "冻结行情", 3: "延迟行情(15分钟)", 4: "延迟冻结行情"}
        try:
            self._call(self._ib.reqMarketDataType, int(md_type))
            self.market_data_type = int(md_type)
            self._md_type_verified = int(md_type)
            return labels.get(int(md_type), f"类型{md_type}")
        except Exception as exc:  # noqa: BLE001
            return f"行情类型设置失败({exc})"

    def disconnect(self) -> None:
        # 先退订全部流式行情，再关连接 —— 否则 IB 侧会保留订阅直到超时
        try:
            with self._stream_lock:
                symbols = list(self._streams)
            if symbols:
                self.unsubscribe(symbols)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._ib is not None:
                self._call(self._ib.disconnect, timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
        self._connected = False
        self._contracts.clear()
        with self._stream_lock:
            self._streams.clear()
            self._ticks.clear()
        # 停写线程前先把队列排空，避免丢掉最后的成交回报
        try:
            self.drain_writes(timeout=1.5)
        except Exception:  # noqa: BLE001
            pass
        self._writer_stop.set()

    def invalidate_caches(self) -> None:
        """清空合约 / 订单 / 回报缓存。连接目标变更后必须调用。"""
        self._contracts.clear()
        self._orders.clear()
        self._pending_status.clear()
        self._summary_cache.clear()
        self._exec_seen.clear()
        self._exec_seen_order.clear()
        self._fill_events.clear()
        self._md_type_verified = None
        with self._stream_lock:
            self._streams.clear()
            self._ticks.clear()
            self._stream_errors.clear()

    def _require(self) -> None:
        if not self.connected:
            ok, msg = self.connect()
            if not ok:
                raise BrokerError(msg)

    # ================================================================
    # 事件回调
    #
    # 设计铁律：**回调内只做内存操作**。
    # IB 的事件线程同时负责心跳与消息分发，回调里写 SQLite（旧实现的做法）
    # 会把整条连接的心跳一起卡住，表现为「订单迟迟不回报、连接莫名断开」。
    # 因此：内存更新 → 投递到有界写队列 → 由独立线程落库。
    # ================================================================
    def _register_events(self) -> None:
        if self._ib is None:
            return
        handlers = {
            "orderStatusEvent": self._on_order_status,
            "execDetailsEvent": self._on_exec_details,
            "commissionReportEvent": self._on_commission,
            "pendingTickersEvent": self._on_pending_tickers,
            "errorEvent": self._on_error,
            "disconnectedEvent": self._on_disconnected,
        }
        ok: list[str] = []
        for name, fn in handlers.items():
            try:
                getattr(self._ib, name).__iadd__(fn)
                ok.append(name)
            except Exception:  # noqa: BLE001
                continue
        self._registered = ok

    # ---------------- 流式行情 ----------------
    def _on_pending_tickers(self, tickers: Any) -> None:
        """reqMktData 推送批次 → 更新内存 tick 缓存并转发给中枢。"""
        t0 = time.perf_counter_ns()
        try:
            items = tickers if isinstance(tickers, (list, tuple, set)) else [tickers]
            for t in items:
                contract = getattr(t, "contract", None)
                if contract is None:
                    continue
                symbol, market, currency = self.display_symbol(contract)
                tick = self._tick_from_ticker(symbol, market, currency, t)
                if tick is None:
                    continue
                with self._stream_lock:
                    self._ticks[symbol] = tick
                    self._stream_errors.pop(symbol, None)
                self.stats["ticks_pushed"] += 1
                self._emit_tick(tick)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                from ..engine import latency as _lat

                _lat.get_latency().record_ns(_lat.TICK_RECV, time.perf_counter_ns() - t0)
            except Exception:  # noqa: BLE001
                pass

    def _tick_from_ticker(self, symbol: str, market: str, currency: str, t: Any) -> Tick | None:
        def px(v: Any) -> float | None:
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return f if f > 0 else None      # 过滤 NaN / IB 的 -1 占位

        def num(v: Any) -> float:
            try:
                f = float(v)
            except (TypeError, ValueError):
                return 0.0
            return f if f == f and f > 0 else 0.0

        last = px(getattr(t, "last", None))
        bid = px(getattr(t, "bid", None))
        ask = px(getattr(t, "ask", None))
        close = px(getattr(t, "close", None))
        mid = (bid + ask) / 2.0 if (bid and ask) else None
        price = last or mid or close
        if price is None:
            return None                       # 无有效价 → 不污染缓存
        return Tick(
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            bid_size=num(getattr(t, "bidSize", None)),
            ask_size=num(getattr(t, "askSize", None)),
            last_size=num(getattr(t, "lastSize", None)),
            volume=num(getattr(t, "volume", None)),
            open=px(getattr(t, "open", None)) or price,
            high=px(getattr(t, "high", None)) or price,
            low=px(getattr(t, "low", None)) or price,
            prev_close=close or 0.0,
            currency=currency,
            market=market,
            source="ibkr-stream",
            ts=str(getattr(t, "time", "") or dt.datetime.now(dt.timezone.utc).isoformat()),
            recv_ns=time.monotonic_ns(),
        )

    def get_tick(self, symbol: str) -> Tick | None:
        """读本地缓存的最新 tick —— 无 IO，可被事件驱动引擎每 tick 调用。"""
        try:
            ref = mksym.parse(symbol)
            key = ref.symbol
        except Exception as exc:  # noqa: BLE001 —— 回退原样大写，但缺陷要留痕
            _silent(exc, "get_tick")
            key = str(symbol or "").strip().upper()
        return self._ticks.get(key)

    def streamed_symbols(self) -> list[str]:
        with self._stream_lock:
            return sorted(self._streams)

    def subscribe(self, symbols: list[str]) -> bool:
        """建立 reqMktData 订阅。返回 False 表示调用方应降级为快照轮询。"""
        try:
            self._require()
        except BrokerError:
            return False
        want: list[tuple[str, Any]] = []
        for raw in symbols or []:
            try:
                ref = mksym.parse(raw)
            except Exception:  # noqa: BLE001
                continue
            with self._stream_lock:
                if ref.symbol in self._streams:
                    continue
            try:
                want.append((ref.symbol, self._contract(raw)))
            except Exception as exc:  # noqa: BLE001
                with self._stream_lock:
                    self._stream_errors[ref.symbol] = f"合约解析失败：{exc}"
        if not want:
            return bool(self.streamed_symbols() and set(
                str(s).upper() for s in symbols) & set(self.streamed_symbols()))
        self.stats["subscribe_calls"] += 1
        added = 0
        for sym, contract in want:
            try:
                ticker = self._call(
                    self._ib.reqMktData, contract, "", False, False,
                    timeout=self.call_timeout,
                )
            except Exception as exc:  # noqa: BLE001
                with self._stream_lock:
                    self._stream_errors[sym] = f"订阅失败：{type(exc).__name__}: {exc}"
                continue
            with self._stream_lock:
                self._streams[sym] = ticker
            added += 1
        return added > 0 or bool(self.streamed_symbols())

    def unsubscribe(self, symbols: list[str]) -> None:
        if self._ib is None:
            return
        self.stats["unsubscribe_calls"] += 1
        for raw in symbols or []:
            try:
                sym = mksym.parse(raw).symbol
            except Exception:  # noqa: BLE001
                sym = str(raw or "").strip().upper()
            with self._stream_lock:
                ticker = self._streams.pop(sym, None)
                self._ticks.pop(sym, None)
                self._stream_errors.pop(sym, None)
            if ticker is None:
                continue
            try:
                self._call(self._ib.cancelMktData, ticker.contract, timeout=2.0)
            except Exception:  # noqa: BLE001
                continue

    def stream_status(self) -> dict[str, Any]:
        with self._stream_lock:
            return {
                "streaming": sorted(self._streams),
                "stream_count": len(self._streams),
                "tick_cache": len(self._ticks),
                "errors": dict(self._stream_errors),
            }

    # ---------------- 错误 / 断连 ----------------
    def _on_error(self, reqId: Any, errorCode: Any = 0, errorString: str = "", *args: Any) -> None:
        """记录 IB 错误码。

        旧实现完全没有注册 `errorEvent`，于是「没有行情权限」「合约不合法」
        「pacing violation」这类关键信息全部丢失，只能表现为「价格一直是 0」。
        """
        try:
            code = int(errorCode)
        except (TypeError, ValueError):
            code = 0
        msg = f"[{code}] {errorString}"
        self.stats["errors_seen"] += 1
        # 2104/2106/2158 是「行情农场已连接」之类的信息性消息，不算错误
        if code not in (2104, 2106, 2158, 2107, 2100, 2108):
            self._last_error = msg
        if code in (1100, 1101, 1102, 2110, 1300):
            self._connected = False
            self._last_error = f"连接被 IB 中断：{msg}"
        try:
            self._last_error_code = code
        except Exception:  # noqa: BLE001
            pass

    def _on_disconnected(self) -> None:
        self._connected = False
        self._last_error = "与 TWS / IB Gateway 的连接已断开"
        with self._stream_lock:
            self._streams.clear()
            self._ticks.clear()

    # ---------------- 订单状态 ----------------
    def _on_order_status(self, trade: Any) -> None:
        """订单状态变化 → 更新内存 + 投递到写队列（**不在此处写数据库**）。

        注意「回调先于落库」的竞态：IBKR 可能在订单行写入数据库之前就推送状态，
        此时查不到行。这里把快照存进 `_pending_status`，由落库方回放
        （见 `order_status_snapshot` / `engine.live._persist_order`）。
        """
        t0 = time.perf_counter_ns()
        try:
            oid = str(getattr(trade.order, "orderId", ""))
            if not oid:
                return
            self._orders[oid] = trade
            snap = self._status_from_trade(trade)
            prev = self._pending_status.get(oid) or {}
            self._pending_status[oid] = snap

            # 成交进度达成 → 唤醒 place_order 的等待方（事件驱动，不再固定 sleep）
            filled = float(snap.get("filled", 0.0) or 0.0)
            status = str(snap.get("status", "") or "")
            if filled > 0 or status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                ev = self._fill_events.get(oid)
                if ev is not None:
                    ev.set()

            # 只有在「成交数量真的增加」时才投递落库任务
            if filled > float(prev.get("filled", 0.0) or 0.0):
                self._enqueue_write({"kind": "order_status", "order_id": oid, "snap": snap})
        except Exception as exc:  # noqa: BLE001
            self.stats["events_dropped"] += 1
            self._last_error = f"订单回报处理异常：{type(exc).__name__}: {exc}"
        finally:
            self._record_report_latency(t0)

    # ---------------- 成交明细 / 佣金 ----------------
    def _on_exec_details(self, trade: Any, fill: Any) -> None:
        """成交回报。回调内只做内存登记，落库交给写线程。"""
        t0 = time.perf_counter_ns()
        try:
            ex = getattr(fill, "execution", None)
            if ex is None:
                # ib_async 某些版本的签名是 (trade, fill)，fill 即 Execution
                ex = fill if getattr(fill, "execId", None) else None
            if ex is None:
                return
            exec_id = str(getattr(ex, "execId", "") or "")
            if exec_id and not self._remember_exec(exec_id):
                return      # 同一笔重复回报 → 丢弃（IB 会重放，去重是必须的）
            oid = str(getattr(ex, "orderId", "") or "")
            contract = getattr(trade, "contract", None) or getattr(fill, "contract", None)
            symbol, market, currency = (
                self.display_symbol(contract) if contract is not None else ("", "US", "USD")
            )
            snap = {
                "exec_id": exec_id,
                "order_id": oid,
                "symbol": symbol,
                "market": market,
                "currency": currency,
                "side": str(getattr(ex, "side", "") or ""),
                "shares": float(getattr(ex, "shares", 0.0) or 0.0),
                "price": float(getattr(ex, "price", 0.0) or 0.0),
                "time": str(getattr(ex, "time", "") or ""),
                "exchange": str(getattr(ex, "exchange", "") or ""),
            }
            self.stats["fills_seen"] += 1
            self._last_fill = snap
            self._enqueue_write({"kind": "exec", "snap": snap})
        except Exception as exc:  # noqa: BLE001
            self.stats["events_dropped"] += 1
            self._last_error = f"成交回报处理异常：{type(exc).__name__}: {exc}"
        finally:
            self._record_report_latency(t0)

    def _on_commission(self, trade: Any, fill: Any, report: Any) -> None:
        """佣金回报。IB 的佣金是**成交之后异步**推送的，所以本地订单行先落库、
        佣金到位后再补记。"""
        try:
            ex = getattr(fill, "execution", None) or fill
            exec_id = str(getattr(ex, "execId", "") or "")
            comm = float(getattr(report, "commission", 0.0) or 0.0)
            currency = str(getattr(report, "currency", "") or "")
            self._enqueue_write({
                "kind": "commission",
                "exec_id": exec_id,
                "order_id": str(getattr(ex, "orderId", "") or ""),
                "commission": comm,
                "currency": currency,
            })
        except Exception as exc:  # noqa: BLE001
            self.stats["events_dropped"] += 1
            self._last_error = f"佣金回报处理异常：{type(exc).__name__}: {exc}"

    def _remember_exec(self, exec_id: str) -> bool:
        """登记 execId；已见过返回 False。用列表做 FIFO 裁剪，避免集合无限增长。"""
        with self._exec_lock:
            if exec_id in self._exec_seen:
                return False
            self._exec_seen.add(exec_id)
            self._exec_seen_order.append(exec_id)
            while len(self._exec_seen_order) > 5000:
                old = self._exec_seen_order.pop(0)
                self._exec_seen.discard(old)
            return True

    # ================================================================
    # 延迟埋点（IB 回调线程内，必须极轻）
    # ================================================================
    def _record_report_latency(self, t0: int) -> None:
        """IB 回调处理耗时埋点。

        为什么必须测这一段：IB 的所有回调都跑在**同一个事件线程**上。
        回调里只要有一次卡 50ms（比如同步写 SQLite），后续所有行情与回报
        都会被排队推迟 —— 这是毫秒级目标最隐蔽的杀手。
        预算 1ms，超了就是代码在回调里干了重活。
        埋点自身必须零风险：任何异常都吞掉，绝不能因为埋点把回报链搞坏。
        """
        try:
            from ..engine import latency as _lat
            _lat.get_latency().record_ns(_lat.EXEC_REPORT, time.perf_counter_ns() - t0)
        except Exception:  # noqa: BLE001
            pass

    # ================================================================
    # 异步落库（IB 事件线程的唯一出口）
    # ================================================================
    def _ensure_writer(self) -> None:
        if self._writer and self._writer.is_alive():
            return
        self._writer_stop.clear()
        self._writer = threading.Thread(target=self._writer_loop, name="ibkr-writer", daemon=True)
        self._writer.start()

    def _enqueue_write(self, job: dict) -> None:
        self._ensure_writer()
        try:
            self._write_q.put_nowait(job)
        except queue.Full:
            # 队列满说明数据库跟不上；宁可丢回报也不能阻塞 IB 事件线程
            self.stats["events_dropped"] += 1

    def _writer_loop(self) -> None:
        while not self._writer_stop.is_set():
            try:
                job = self._write_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._apply_write(job)
            except Exception as exc:  # noqa: BLE001
                self.stats["events_dropped"] += 1
                self._last_error = f"回报落库失败：{type(exc).__name__}: {exc}"
            finally:
                try:
                    self._write_q.task_done()
                except Exception:  # noqa: BLE001
                    pass

    def _apply_write(self, job: dict) -> None:
        kind = job.get("kind")
        from ..database import session_scope
        from ..models import Fill, Order as OrderRow

        if kind == "order_status":
            # 只更新订单行状态；**成交明细由 execDetails 负责**。
            # 旧实现用「状态里的 filled 减去行里的 filled_qty」来推增量成交，
            # 一旦同一笔被多次回报（IB 会重放），就会重复记账。
            oid = job["order_id"]
            with session_scope() as s:
                row = (
                    s.query(OrderRow)
                    .filter(OrderRow.broker_order_id == oid, OrderRow.broker == "ibkr")
                    .order_by(OrderRow.id.desc())
                    .first()
                )
                if not row:
                    return          # 订单行尚未落库，等待落库后回放
                _apply_status_snapshot(row, job["snap"])
            return

        if kind == "exec":
            snap = job["snap"]
            oid = snap.get("order_id") or ""
            with session_scope() as s:
                row = (
                    s.query(OrderRow)
                    .filter(OrderRow.broker_order_id == str(oid), OrderRow.broker == "ibkr")
                    .order_by(OrderRow.id.desc())
                    .first()
                )
                if not row:
                    return
                s.add(Fill(
                    order_id=row.id,
                    quantity=float(snap.get("shares", 0.0) or 0.0),
                    price=float(snap.get("price", 0.0) or 0.0),
                    commission=0.0,
                ))
            return

        if kind == "commission":
            comm = float(job.get("commission", 0.0) or 0.0)
            if not comm:
                return
            oid = str(job.get("order_id") or "")
            with session_scope() as s:
                row = (
                    s.query(OrderRow)
                    .filter(OrderRow.broker_order_id == oid, OrderRow.broker == "ibkr")
                    .order_by(OrderRow.id.desc())
                    .first()
                )
                if not row:
                    return
                last = (
                    s.query(Fill).filter(Fill.order_id == row.id)
                    .order_by(Fill.id.desc()).first()
                )
                if last is None:
                    return
                last.commission = round(float(last.commission or 0.0) + comm, 4)
            return

    def drain_writes(self, timeout: float = 2.0) -> bool:
        """等待写队列清空（测试/关停时用）。"""
        if self._writer is None:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._write_q.empty():
                return True
            time.sleep(0.01)
        return self._write_q.empty()

    @staticmethod
    def _status_from_trade(trade: Any) -> dict[str, float | str]:
        st = getattr(trade, "orderStatus", None)
        if st is None:
            return {}
        return {
            "status": str(getattr(st, "status", "") or ""),
            "filled": float(getattr(st, "filled", 0.0) or 0.0),
            "avg_price": float(getattr(st, "avgFillPrice", 0.0) or 0.0),
            "remaining": float(getattr(st, "remaining", 0.0) or 0.0),
        }

    def order_status_snapshot(self, order_id: str) -> dict | None:
        """返回该订单在券商侧的最新状态快照（落库时回放用）。

        有活跃 trade 时取其当前状态；否则回退到最近一次回调暂存的快照。
        """
        oid = str(order_id or "")
        if not oid:
            return None
        trade = self._orders.get(oid)
        if trade is not None:
            snap = self._status_from_trade(trade)
            if snap:
                return snap
        return dict(self._pending_status.get(oid) or {}) or None

    # ================================================================
    # 合约解析
    # ================================================================
    def _spec(self, symbol: str) -> _ContractSpec:
        """解析任意写法 → 合约规格。

        唯一真源是 `markets.symbols.parse()`：
            AAPL / BRK-B           → Stock(SMART, USD, primary=NASDAQ/NYSE)
            0700.HK / 700 / 0700   → Stock(SEHK, HKD, primary=SEHK)
            ^HSI                   → Index(HKFE, HKD)
            ^GSPC                  → Index(CBOE, USD)
        旧实现一律 `SMART + USD` 且把 "0700.HK" 变成 "0700 HK"，港股永远解析不到。
        """
        ref = mksym.parse(symbol)          # 可能抛 SymbolError
        return _ContractSpec(
            symbol=ref.ib_symbol,
            sec_type=ref.sec_type,
            exchange=ref.exchange,
            currency=ref.currency,
            primary_exchange=ref.primary_exchange,
            market=ref.market,
        )

    def _contract(self, symbol: str):
        """取得（并缓存）已限定资格的合约对象。缓存键用规范化代码，多写法共享一份。"""
        try:
            ref = mksym.parse(symbol)
            key = ref.symbol
        except Exception:  # noqa: BLE001
            key = str(symbol or "").strip().upper()
        cached = self._contracts.get(key)
        if cached is not None:
            return cached

        ib_async = self._import_ib()
        spec = self._spec(symbol)
        if spec.sec_type == "IND":
            contract = ib_async.Index(spec.symbol, spec.exchange, spec.currency)
        else:
            contract = ib_async.Stock(spec.symbol, spec.exchange, spec.currency)
            if spec.primary_exchange:
                contract.primaryExchange = spec.primary_exchange
        try:
            self._await(self._ib.qualifyContractsAsync(contract), timeout=self.call_timeout + 3.0)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"合约限定失败（{key}）：{type(exc).__name__}: {exc}"
        self._contracts[key] = contract
        return contract

    # ------------------------------------------------------------------
    # 合约 → 展示代码（持仓/成交回报需要把 IB 的 "700" 还原成 "0700.HK"）
    # ------------------------------------------------------------------
    @staticmethod
    def display_symbol(contract: Any) -> tuple[str, str, str]:
        """返回 (展示代码, 市场, 币种)。"""
        sym = str(getattr(contract, "symbol", "") or "").strip().upper()
        currency = str(getattr(contract, "currency", "") or "USD").upper()
        local = str(getattr(contract, "localSymbol", "") or "")
        exchange = str(getattr(contract, "exchange", "") or "")
        primary = str(getattr(contract, "primaryExchange", "") or "")
        sec_type = str(getattr(contract, "secType", "STK") or "STK")

        is_hk = (
            currency == "HKD"
            or exchange == "SEHK"
            or primary == "SEHK"
            or exchange in ("HKFE", "HKEX")
        )
        if is_hk:
            if sec_type == "IND":
                return (f"^{sym}", "HK", "HKD")
            digits = "".join(ch for ch in (local or sym) if ch.isdigit())
            if digits:
                return (mksym.canonical_hk(digits), "HK", "HKD")
            return (sym, "HK", "HKD")
        if sec_type == "IND" and sym and not sym.startswith("^"):
            return (f"^{sym}", "US", currency or "USD")
        return (sym, "US", currency or "USD")

    # ================================================================
    # 实时行情
    # ================================================================
    def _ticker_row(self, requested: str, contract: Any, t: Any) -> dict[str, Any]:
        def fx(v: Any) -> float | None:
            try:
                f = float(v)
                return f if f == f and f not in (0.0, -1.0) else None   # 过滤 NaN / IB 的 -1 占位
            except (TypeError, ValueError):
                return None

        last = fx(getattr(t, "last", None))
        close = fx(getattr(t, "close", None))          # IB 的 close = 前一日收盘
        bid = fx(getattr(t, "bid", None))
        ask = fx(getattr(t, "ask", None))
        mid = (bid + ask) / 2 if (bid and ask) else None
        price = last or mid or close or fx(getattr(t, "marketPrice", lambda: None)() if callable(getattr(t, "marketPrice", None)) else None)
        if not price:
            price = 0.0
        change = (price - close) if (close and price) else 0.0
        return {
            "symbol": requested,
            "price": round(price, 4),
            "prev_close": round(close or 0.0, 4),
            "change": round(change, 4),
            "change_pct": round(change / close * 100, 3) if close else 0.0,
            "volume": float(fx(getattr(t, "volume", None)) or 0.0),
            "day_high": round(fx(getattr(t, "high", None)) or price, 4),
            "day_low": round(fx(getattr(t, "low", None)) or price, 4),
            "open": round(fx(getattr(t, "open", None)) or price, 4),
            "bid": bid,
            "ask": ask,
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "ibkr",
        }

    def snapshot(self, symbols: list[str], md_type: int | None = None) -> list[dict[str, Any]]:
        """批量实时快照。

        第一步先吃**流式缓存**：已经 reqMktData 订阅过的标的直接由内存返回，
        一个 IB 请求都不发。这消除了旧实现「每个消费者都要各自 reqTickers」的
        N 倍放大 —— 那正是打满 50 msg/s 配额、并把每次读取都拖到网络往返的主因。
        剩余标的才走 reqTickers，且失败时自动换行情类型重试一次。
        """
        cached_rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for raw in symbols:
            t = self.get_tick(raw)
            if t is not None and t.price > 0 and (time.monotonic_ns() - t.recv_ns) < 5e9:
                cached_rows.append(self._tick_row(t))
            else:
                missing.append(raw)
        if not missing:
            return cached_rows

        try:
            self._require()
        except BrokerError as exc:
            return cached_rows + [self._empty_row(s, str(exc)) for s in missing]

        md = int(md_type if md_type is not None else self.market_data_type)
        fresh = self._snapshot_once(missing, md)
        if fresh and all(r["price"] <= 0 for r in fresh):
            alt = 1 if md != 1 else 3
            retry = self._snapshot_once(missing, alt)
            if retry and any(r["price"] > 0 for r in retry):
                self._md_type_verified = alt
                for r in retry:
                    r["md_type"] = alt
                return cached_rows + retry
        for r in fresh:
            r["md_type"] = md
        return cached_rows + fresh

    @staticmethod
    def _tick_row(t: Tick) -> dict[str, Any]:
        """流式缓存 Tick → 统一报价字典（与 `_ticker_row` 字段一致）。"""
        change = (t.price - t.prev_close) if (t.prev_close and t.price) else 0.0
        return {
            "symbol": t.symbol, "display_symbol": t.symbol,
            "price": round(t.price, 4),
            "prev_close": round(t.prev_close, 4),
            "change": round(change, 4),
            "change_pct": round(change / t.prev_close * 100, 3) if t.prev_close else 0.0,
            "volume": t.volume,
            "day_high": round(t.high, 4), "day_low": round(t.low, 4),
            "open": round(t.open, 4),
            "bid": t.bid, "ask": t.ask,
            "bid_size": t.bid_size, "ask_size": t.ask_size,
            "currency": t.currency, "market": t.market,
            "ts": t.ts, "source": t.source, "mode": "stream",
        }

    @staticmethod
    def _empty_row(symbol: str, error: str = "") -> dict[str, Any]:
        return {
            "symbol": symbol.strip().upper(), "price": 0.0, "prev_close": 0.0,
            "change": 0.0, "change_pct": 0.0, "volume": 0.0,
            "day_high": 0.0, "day_low": 0.0, "open": 0.0, "bid": None, "ask": None,
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "ibkr", "error": error[:160],
        }

    def _snapshot_once(self, symbols: list[str], md_type: int) -> list[dict[str, Any]]:
        try:
            self._call(self._ib.reqMarketDataType, int(md_type))
        except Exception:  # noqa: BLE001
            pass
        out: list[dict[str, Any]] = []
        try:
            contracts = [self._contract(s) for s in symbols]
            # 旧实现 timeout=max(self.timeout+25, 40) —— 一次请求最坏拖 40 秒，
            # 足以把 FastAPI 的线程池（上限 40）连同用户请求一起拖死。6 秒足够。
            tickers = self._await(
                self._ib.reqTickersAsync(*contracts), timeout=max(self.call_timeout + 1.0, 6.0)
            )
            for sym, c, t in zip(symbols, contracts, tickers):
                row = self._ticker_row(sym.strip().upper(), c, t)
                display, market, currency = self.display_symbol(c)
                row["display_symbol"] = display
                row["market"] = market
                row["currency"] = currency
                out.append(row)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"实时行情获取失败：{type(exc).__name__}: {exc}"
            for s in symbols:
                out.append(self._empty_row(s, str(exc)))
        return out

    # ================================================================
    # 历史 K 线（自动分页）
    # ================================================================
    def history(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
        use_rth: bool | None = None,
        max_pages: int = 60,
    ) -> pd.DataFrame:
        """
        拉取历史 K 线。IB 对单次请求的时长有硬限制，这里按 BAR_MAP 的时长上限
        向后翻页拼接，直到覆盖 start 或达到 max_pages（也顺带规避 pacing 限制）。

        任何失败都返回空 DataFrame，由上层（data_provider）自动降级到其他数据源。
        """
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        try:
            self._require()
        except BrokerError:
            return empty
        bar_size, cap_dur, cap_days = BAR_MAP.get(interval, BAR_MAP["1d"])
        rth = self.use_rth if use_rth is None else bool(use_rth)

        start_ts = pd.Timestamp(start) if start else pd.Timestamp.now().normalize() - pd.Timedelta(days=cap_days * 5)
        end_ts = pd.Timestamp(end) if end else pd.Timestamp.now().normalize() + pd.Timedelta(days=1)

        cursor = end_ts
        frames: list[pd.DataFrame] = []
        for page in range(max_pages):
            if cursor <= start_ts:
                break
            end_str = (cursor + pd.Timedelta(days=1)).strftime("%Y%m%d %H:%M:%S")
            try:
                bars = self._await(
                    self._ib.reqHistoricalDataAsync(
                        self._contract(symbol), end_str, cap_dur, bar_size,
                        "TRADES", rth, 1, False, [],
                    ),
                    # 旧实现是 max(self.timeout*6, 90) —— 翻页请求本来就要等，
                    # 但 90s 的单次上限会让一个卡死的请求独占线程 1.5 分钟。
                    timeout=min(max(self.call_timeout * 6.0, 30.0), 60.0),
                )
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"历史数据请求失败：{type(exc).__name__}: {exc}"
                break
            if not bars:
                break
            df = pd.DataFrame([
                {"date": b.date, "open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume}
                for b in bars
            ])
            if df.empty:
                break
            df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=False)
            df = df.dropna(subset=["date"]).set_index("date")
            # P1-2：IB 返回的 bar 自带交易所时区（aware），而 start_ts / cursor 是 naive
            # —— 旧实现直接比较抛 TypeError，且该异常在 try 之外、被 data_provider 的
            # except 吞掉不写 _last_errors → 「IBKR 分钟级回溯数年」完全不可用且不可见。
            # 修法：把比较基准（start/cursor/end）统一 localize 到 bar 的时区再比。
            idx_tz = getattr(df.index, "tz", None)
            if idx_tz is not None:
                if start_ts.tzinfo is None:
                    start_ts = start_ts.tz_localize(idx_tz)
                if cursor.tzinfo is None:
                    cursor = cursor.tz_localize(idx_tz)
                if end_ts.tzinfo is None:
                    end_ts = end_ts.tz_localize(idx_tz)
            frames.append(df)
            self._hist_calls += 1

            oldest = df.index.min()
            if oldest <= start_ts or len(bars) < 2:
                break
            new_cursor = oldest - pd.Timedelta(days=1)
            if new_cursor >= cursor:
                break
            cursor = new_cursor
            if page and page % 6 == 0:
                try:      # 轻微让步，避免触发 IB 的 pacing 限制
                    self._sleep(2.0)
                except Exception:  # noqa: BLE001
                    pass

        if not frames:
            return empty

        out = pd.concat(frames).sort_index()
        out = out[~out.index.duplicated(keep="last")]
        # P1-2：最终裁剪同样要做 tz 对齐（首頁即失败break的场景 idx 可能与基准不一致）
        idx_tz = getattr(out.index, "tz", None)
        s_cmp = start_ts.tz_localize(idx_tz) if (idx_tz is not None and start_ts.tzinfo is None) else start_ts
        e_cmp = end_ts.tz_localize(idx_tz) if (idx_tz is not None and end_ts.tzinfo is None) else end_ts
        out = out[out.index >= s_cmp]
        if end:
            out = out[out.index <= e_cmp]
        out.index = pd.to_datetime(out.index)
        for c in ("open", "high", "low", "close", "volume"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
        return out.dropna(subset=["close"])

    # ================================================================
    # 账户与持仓
    # ================================================================
    def _summary(self) -> dict[str, float]:
        self._require()
        try:
            rows = self._await(
                self._ib.accountSummaryAsync(self.account_id or ""),
                timeout=max(self.call_timeout, 6.0),
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"账户摘要获取失败：{type(exc).__name__}: {exc}"
            return {}
        out: dict[str, float] = {}
        for r in rows:
            try:
                out[str(r.tag)] = float(r.value)
            except (TypeError, ValueError):
                continue

        # 账户基准币种：从本地缓存读 BaseCurrency（accountValues 是纯缓存读取，
        # 不发消息，因此不会占用 pacing 配额）。
        try:
            for v in self._call(self._ib.accountValues, timeout=2.0):
                if str(getattr(v, "tag", "")) == "BaseCurrency":
                    cur = str(getattr(v, "value", "") or "")
                    if cur:
                        self._base_currency = cur
                    break
        except Exception:  # noqa: BLE001
            pass
        return out

    def account(self) -> AccountSnapshot:
        try:
            self._require()
        except BrokerError as exc:
            return AccountSnapshot(
                broker=self.name, mode=self.mode, connected=False,
                account_id=self.account_id, message=str(exc),
            )
        s = self._summary()
        self._summary_cache = s

        equity = s.get("NetLiquidation", 0.0)
        cash = s.get("TotalCashValue", 0.0)
        unreal = s.get("UnrealizedPnL", 0.0)
        realized = s.get("RealizedPnL", 0.0)
        fx_est = bool(getattr(self, "_positions_fx_estimated", False))
        return AccountSnapshot(
            broker=self.name,
            mode=self.mode,
            connected=True,
            account_id=self.account_id or "IBKR",
            currency=self._base_currency,
            equity=round(equity, 2),
            cash=round(cash, 2),
            buying_power=round(s.get("BuyingPower", 0.0), 2),
            gross_position_value=round(s.get("GrossPositionValue", 0.0), 2),
            unrealized_pnl=round(unreal, 2),
            realized_pnl=round(realized, 2),
            day_pnl=round(unreal, 2),
            day_pnl_pct=round(unreal / equity * 100, 3) if equity else 0.0,
            margin_used=round(s.get("MaintMarginReq", 0.0), 2),
            fx_estimated=fx_est,
            message=(
                f"{'实盘' if self.mode == 'live' else '纸面'}账户 · {self.host}:{self.port}"
                f" · 行情类型 {self._md_type_verified or self.market_data_type}"
                + ("　· 含估算汇率" if fx_est else "")
            ),
        )

    def positions(self) -> list[PositionItem]:
        """使用 portfolio() 取真实市价与浮盈（而不是把成本当现价）。

        多市场处理：IB 返回的港股 symbol 是 "700"、币种 HKD，市场价值是**港币**。
        旧实现直接把港币市值当美元计入权重，港股仓位权重会被放大 7.8 倍。
        这里统一用 `display_symbol()` 还原代码，并折算到账户基准币种。
        """
        try:
            self._require()
        except BrokerError:
            return []
        try:
            rows = (
                self._call(self._ib.portfolio, self.account_id)
                if self.account_id
                else self._call(self._ib.portfolio)
            )
        except Exception:  # noqa: BLE001
            return []

        from ..markets.fx import convert
        from ..markets.lots import lot_of

        equity = self._summary_cache.get("NetLiquidation") or 0.0
        out: list[PositionItem] = []
        fx_estimated_any = False
        for p in rows:
            try:
                qty = float(p.position)
                if abs(qty) < 1e-9:
                    continue
                contract = p.contract
                symbol, market, currency = self.display_symbol(contract)
                avg = float(getattr(p, "averageCost", 0.0) or 0.0)
                px = float(getattr(p, "marketPrice", 0.0) or 0.0)
                if px <= 0:
                    px = avg
                mv = float(getattr(p, "marketValue", 0.0) or 0.0) or qty * px
                upl = float(getattr(p, "unrealizedPNL", 0.0) or 0.0)
                cost_basis = abs(avg * qty)
                mv_base, estimated = convert(mv, currency, "USD")
                fx_estimated_any = fx_estimated_any or estimated
                try:
                    lot = lot_of(symbol).lot
                except Exception:  # noqa: BLE001
                    lot = 1
                out.append(PositionItem(
                    symbol=symbol,
                    quantity=qty,
                    avg_cost=round(avg, 4),
                    last_price=round(px, 4),
                    market_value=round(mv, 2),
                    unrealized_pnl=round(upl, 2),
                    unrealized_pct=round(upl / cost_basis * 100, 3) if cost_basis else 0.0,
                    weight=round(abs(mv_base) / equity * 100, 2) if equity else 0.0,
                    sec_type=str(getattr(contract, "secType", "STK")),
                    currency=currency,
                    market=market,
                    market_value_base=round(mv_base, 2),
                    lot=lot,
                ))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda x: -abs(x.market_value_base or x.market_value))
        self._positions_fx_estimated = fx_estimated_any
        return out

    # ================================================================
    # 下单（支持 OCO 止盈止损）
    # ================================================================
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: str = "DAY",
        take_profit_price: float | None = None,
        stop_loss_price: float | None = None,
        wait_fill: bool = True,
    ) -> OrderResult:
        """下单。**不再有固定 sleep**。

        旧实现在提交后 `sleep(0.8)` 再读状态：一次 10 标的调仓就是 8 秒起步，
        与「毫秒级」完全矛盾。现在改为：
          1. `placeOrder` 返回（拿到 orderId）即为「已被 IB 受理」，立刻返回；
          2. 若 `wait_fill=True`，用 `orderStatusEvent` 事件等待成交，
             上限 `fill_timeout`（默认 2s），而不是固定阻塞；
          3. 超时不算失败 —— 后续成交由回调异步回填。

        往返耗时记入 `OrderResult.latency_ms` 与 `raw.submit_ms`，供延迟面板统计。

        多市场差异（此前一律按美股处理）：
          · 港股无原生市价单 → 自动转成「进取限价单」（买挂卖一之上 / 卖挂买一之下）
          · TIF 白名单随市场变化（港股只有 DAY / GTC）
          · 提示文案的币种符号随市场变化（HK$ / US$）
        """
        t_start = time.perf_counter()
        if self.readonly:
            return OrderResult(
                False,
                message="当前为只读模式（readonly=True），无法下单。请在「系统设置 → 券商连接」关闭只读。",
            )
        ib_async = self._import_ib()
        try:
            self._require()
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        try:
            ref = mksym.parse(symbol)
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, message=f"无法识别的标的：{symbol!r}（{exc}）")
        sym = ref.symbol
        mkt = get_market(ref.market)
        csym = mkt.currency_symbol

        side = side.upper()
        qty = abs(float(quantity))
        if qty <= 0:
            return OrderResult(False, message="数量必须大于 0")
        if order_type == "STP" and not stop_price:
            return OrderResult(False, message="止损单必须提供 stop_price")
        if order_type in ("LMT", "STP_LMT") and not limit_price:
            return OrderResult(False, message="限价单必须提供 limit_price")

        # ---- 港股：市价单 → 进取限价单 ----
        market_order_simulated = False
        eff_type = order_type
        eff_limit = limit_price
        if order_type == "MKT" and not mkt.native_market_order:
            tick = self.get_tick(sym)
            if tick is None:
                try:
                    rows = self._snapshot_once([sym], self.market_data_type)
                    tick = None if not rows else Tick(
                        symbol=sym,
                        price=float(rows[0].get("price") or 0.0),
                        bid=rows[0].get("bid"),
                        ask=rows[0].get("ask"),
                    )
                except Exception:  # noqa: BLE001
                    tick = None
            px = None
            if tick is not None:
                px = (tick.ask if side == "BUY" else tick.bid) or (tick.price or None)
            if not px or px <= 0:
                return OrderResult(
                    False,
                    message=(
                        f"{mkt.name}不支持市价单，且当前拿不到盘口价，无法构造进取限价单。"
                        f"请改用限价单并显式指定价格。"
                    ),
                )
            from ..markets.lots import round_price as _round_price

            buffer = max(px * 0.003, mkt.tick_size * 5)
            eff_limit = _round_price(
                sym, px + buffer if side == "BUY" else max(px - buffer, mkt.tick_size)
            )
            eff_type = "LMT"
            market_order_simulated = True

        # ---- TIF 白名单随市场变化 ----
        tif_u = str(tif or "DAY").upper()
        if tif_u not in mkt.allowed_tif:
            return OrderResult(
                False,
                message=f"{mkt.name}不支持 TIF={tif_u}（允许：{'、'.join(sorted(mkt.allowed_tif))}）",
            )

        try:
            contract = self._contract(sym)

            def build(side_: str, qty_: float, kind: str) -> Any:
                if kind == "MKT":
                    return ib_async.MarketOrder(side_, qty_)
                if kind == "LMT":
                    return ib_async.LimitOrder(side_, qty_, float(eff_limit))
                if kind == "STP":
                    return ib_async.StopOrder(side_, qty_, float(stop_price))
                return ib_async.StopLimitOrder(side_, qty_, float(limit_price), float(stop_price))

            parent = build(side, qty, eff_type)
            parent.tif = tif_u
            parent.outsideRth = not self.use_rth
            parent.transmit = not (take_profit_price or stop_loss_price)

            parent_trade = self._call(self._ib.placeOrder, contract, parent)
            trades: list[Any] = [parent_trade]
            oid = str(getattr(parent_trade.order, "orderId", ""))

            # 括号单：主单成交后挂出止盈与止损（OCO 互斥）
            if take_profit_price or stop_loss_price:
                opp = "SELL" if side == "BUY" else "BUY"
                tag = ref.ib_symbol.replace(" ", "")
                oca = f"QD-{tag}-{dt.datetime.now().strftime('%H%M%S%f')[:12]}"
                children: list[Any] = []
                if take_profit_price:
                    tp = ib_async.LimitOrder(opp, qty, float(take_profit_price))
                    tp.tif = "GTC"
                    tp.parentId = parent.orderId
                    tp.ocaGroup = oca
                    tp.ocaType = 1
                    tp.outsideRth = not self.use_rth
                    tp.transmit = bool(stop_loss_price)
                    children.append(self._call(self._ib.placeOrder, contract, tp))
                if stop_loss_price:
                    sl = ib_async.StopOrder(opp, qty, float(stop_loss_price))
                    sl.tif = "GTC"
                    sl.parentId = parent.orderId
                    sl.ocaGroup = oca
                    sl.ocaType = 1
                    sl.outsideRth = not self.use_rth
                    sl.transmit = True
                    children.append(self._call(self._ib.placeOrder, contract, sl))
                if not take_profit_price and stop_loss_price and children:
                    parent.transmit = True
                    self._call(self._ib.placeOrder, contract, parent)
                trades.extend(children)

            for t in trades:
                tid = str(getattr(t.order, "orderId", ""))
                if tid:
                    self._orders[tid] = t

            submitted_ms = (time.perf_counter() - t_start) * 1000.0
            # 埋点：本地构造 + 提交到 IB（不含券商撮合）。预算 5ms。
            try:
                from ..engine import latency as _lat
                _lat.get_latency().record(_lat.ORDER_SUBMIT, submitted_ms)
            except Exception:  # noqa: BLE001
                pass

            st = parent_trade.orderStatus
            status = str(getattr(st, "status", "Submitted") or "Submitted")
            filled = float(getattr(st, "filled", 0.0) or 0.0)
            avg = float(getattr(st, "avgFillPrice", 0.0) or 0.0)

            # ---- 事件驱动等待成交（替代固定 sleep(0.8)）----
            waited = False
            if wait_fill and oid and filled <= 0 and status not in ("Cancelled", "Inactive"):
                ev = self._fill_events.setdefault(oid, threading.Event())
                deadline = time.monotonic() + self.fill_timeout
                while not ev.wait(timeout=0.02):
                    if time.monotonic() >= deadline:
                        break
                waited = True
                st = parent_trade.orderStatus
                status = str(getattr(st, "status", status) or status)
                filled = float(getattr(st, "filled", 0.0) or 0.0)
                avg = float(getattr(st, "avgFillPrice", 0.0) or 0.0)

            latency_ms = (time.perf_counter() - t_start) * 1000.0
            self.stats["orders_placed"] += 1
            self._last_order_latency_ms = {
                "submit_ms": round(submitted_ms, 2),
                "total_ms": round(latency_ms, 2),
                "waited_for_fill": waited,
                "filled": filled,
            }
            if oid:
                self._fill_events.pop(oid, None)

            extras = []
            if take_profit_price:
                extras.append(f"止盈 {csym}{take_profit_price:g}")
            if stop_loss_price:
                extras.append(f"止损 {csym}{stop_loss_price:g}")
            type_txt = f"MKT→进取限价 {csym}{eff_limit:g}" if market_order_simulated else order_type
            return OrderResult(
                True, order_id=oid, status=status,
                message=(
                    f"已提交 IBKR 订单 {side} {qty:g} {sym}（{type_txt}"
                    + ("，" + "，".join(extras) if extras else "")
                    + f"）· 提交 {submitted_ms:.0f}ms / 往返 {latency_ms:.0f}ms"
                ),
                filled_qty=filled, avg_price=avg,
                latency_ms=round(latency_ms, 2),
                raw={
                    "permId": str(getattr(parent_trade.order, "permId", "")),
                    "tif": tif_u,
                    "oca": bool(extras),
                    "childOrders": len(trades) - 1,
                    "market": ref.market,
                    "currency": ref.currency,
                    "market_order_simulated": market_order_simulated,
                    "submit_ms": round(submitted_ms, 2),
                },
            )
        except BrokerError as exc:
            self.stats["orders_rejected"] += 1
            return OrderResult(False, message=str(exc))
        except Exception as exc:  # noqa: BLE001
            self.stats["orders_rejected"] += 1
            return OrderResult(False, message=f"下单失败：{type(exc).__name__}: {exc}")

    def cancel_order(self, order_id: str) -> OrderResult:
        try:
            self._require()
        except BrokerError as exc:
            return OrderResult(False, order_id=order_id, message=str(exc))
        try:
            for t in self._call(self._ib.openTrades):
                cands = {str(t.order.orderId), str(getattr(t.order, "permId", ""))}
                if str(order_id) in cands:
                    self._call(self._ib.cancelOrder, t.order)
                    return OrderResult(True, order_id=order_id, status="Cancelled", message="撤单已提交")
            return OrderResult(False, order_id=order_id, message="未找到该订单（可能已成交或已撤销）")
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, order_id=order_id, message=f"撤单失败: {exc}")

    def cancel_all(self) -> int:
        """撤销该客户端下的全部挂单。紧急情况下很有用。"""
        try:
            self._require()
            trades = self._call(self._ib.openTrades)
            n = 0
            for t in trades:
                try:
                    self._call(self._ib.cancelOrder, t.order)
                    n += 1
                except Exception:  # noqa: BLE001
                    continue
            return n
        except Exception:  # noqa: BLE001
            return 0

    def open_orders(self) -> list[dict[str, Any]]:
        try:
            self._require()
            out: list[dict[str, Any]] = []
            for t in self._call(self._ib.openTrades):
                st = t.orderStatus
                symbol, market, currency = self.display_symbol(t.contract)
                out.append({
                    "order_id": str(t.order.orderId),
                    "perm_id": str(getattr(t.order, "permId", "")),
                    "symbol": symbol,
                    "market": market,
                    "currency": currency,
                    "action": str(t.order.action),
                    "quantity": float(t.order.totalQuantity),
                    "type": str(t.order.orderType),
                    "lmt_price": float(getattr(t.order, "lmtPrice", 0.0) or 0.0),
                    "aux_price": float(getattr(t.order, "auxPrice", 0.0) or 0.0),
                    "status": str(st.status),
                    "filled": float(st.filled or 0.0),
                    "remaining": float(st.remaining or 0.0),
                    "oca_group": str(getattr(t.order, "ocaGroup", "") or ""),
                })
            return out
        except Exception:  # noqa: BLE001
            return []

    def today_fills(self) -> list[dict[str, Any]]:
        """今日成交回报（用于与本地订单表对账）。"""
        try:
            self._require()
            out = []
            for f in self._call(self._ib.fills):
                ex = f.execution
                symbol, market, currency = self.display_symbol(f.contract)
                out.append({
                    "exec_id": str(ex.execId),
                    "order_id": str(ex.orderId),
                    "perm_id": str(getattr(ex, "permId", "")),
                    "symbol": symbol,
                    "market": market,
                    "currency": currency,
                    "side": str(ex.side),
                    "shares": float(ex.shares),
                    "price": float(ex.price),
                    "time": str(getattr(ex, "time", "")),
                    "commission": float(getattr(f.commissionReport, "commission", 0.0) or 0.0)
                    if getattr(f, "commissionReport", None) else 0.0,
                })
            return out
        except Exception:  # noqa: BLE001
            return []

    # ================================================================
    def quote(self, symbol: str) -> dict[str, Any]:
        rows = self.snapshot([symbol])
        return rows[0] if rows else {"symbol": symbol.upper(), "price": 0.0, "source": "ibkr"}

    def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        return self.snapshot(symbols)

    def status(self) -> dict[str, Any]:
        md_labels = {1: "实时", 2: "冻结", 3: "延迟", 4: "延迟冻结"}
        md = self._md_type_verified or self.market_data_type
        stream = self.stream_status()
        return {
            "broker": self.name,
            "mode": self.mode,
            "connected": self.connected,
            "host": self.host,
            "port": self.port,
            "client_id": self.client_id,
            "account": self.account_id,
            "base_currency": self._base_currency,
            "readonly": self.readonly,
            "market_data_type": md,
            "market_data_label": md_labels.get(md, "未知"),
            "use_rth": self.use_rth,
            "contracts_cached": len(self._contracts),
            "historical_requests": self._hist_calls,
            # ---- 流式行情 ----
            "supports_streaming": self.supports_streaming,
            "stream_method": "reqMktData",
            "streamed_symbols": stream["stream_count"],
            "tick_cache": stream["tick_cache"],
            "stream_sample": stream["streaming"][:12],
            # ---- 延迟 / 限流 / 熔断 ----
            "call_timeout_sec": self.call_timeout,
            "fill_timeout_sec": self.fill_timeout,
            "pacing": self._pacer.snapshot(),
            "breaker": self._breaker.snapshot(),
            "event_handlers": list(self._registered),
            "last_order_latency_ms": dict(self._last_order_latency_ms),
            "stats": dict(self.stats),
            "last_error": self._last_error,
            "last_error_code": self._last_error_code,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }


# 进程内单例（避免重复建立 IB 连接）
_singleton: IBKRBroker | None = None


_singleton_lock = threading.Lock()


def get_ibkr(cfg: dict[str, Any] | None = None) -> IBKRBroker:
    # P1：首个并发请求窗口内两个线程可能各建一个实例（各自持 IB 连接与事件循环，
    # clientId 冲突互踢）。单例创建加锁。
    global _singleton
    cfg = cfg or {}
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = IBKRBroker(
                    host=cfg.get("host", "127.0.0.1"),
                    port=int(cfg.get("port", 7497)),
                    client_id=int(cfg.get("client_id", 17)),
                    account=cfg.get("account", ""),
                    mode=cfg.get("mode", "paper"),
                    readonly=bool(cfg.get("readonly", True)),
                    timeout=float(cfg.get("timeout", 8.0)),
                    call_timeout=float(cfg.get("call_timeout", 5.0)),
                    fill_timeout=float(cfg.get("fill_timeout", 2.0)),
                    market_data_type=int(cfg.get("market_data_type", 3)),
                    use_rth=bool(cfg.get("use_rth", True)),
                )
    if _singleton is None:  # pragma: no cover —— 理论不可达，防御兜底
        raise BrokerError("IBKRBroker 初始化失败")
    # 配置更新路径（单例已存在）：不加锁原地更新字段 —— 与旧行为一致，
    # 仅消除「并发首次创建出双实例」的竞态。
    if _singleton.host != cfg.get("host", _singleton.host) or _singleton.port != int(
        cfg.get("port", _singleton.port)
    ) or _singleton.client_id != int(cfg.get("client_id", _singleton.client_id)):
        changed = True
    else:
        changed = False
    _singleton.host = cfg.get("host", _singleton.host)
    _singleton.port = int(cfg.get("port", _singleton.port))
    _singleton.client_id = int(cfg.get("client_id", _singleton.client_id))
    _singleton.account_id = cfg.get("account", _singleton.account_id)
    _singleton.mode = cfg.get("mode", _singleton.mode)
    _singleton.readonly = bool(cfg.get("readonly", _singleton.readonly))
    _singleton.call_timeout = float(cfg.get("call_timeout", _singleton.call_timeout))
    _singleton.fill_timeout = float(cfg.get("fill_timeout", _singleton.fill_timeout))
    _singleton.market_data_type = int(cfg.get("market_data_type", _singleton.market_data_type))
    _singleton.use_rth = bool(cfg.get("use_rth", _singleton.use_rth))
    if changed:
        # 连接目标变了 → 旧的订阅与合约缓存全部失效
        try:
            _singleton.disconnect()
        except Exception:  # noqa: BLE001
            pass
        _singleton.invalidate_caches()
        try:
            from ..engine.stream import get_hub

            get_hub().invalidate_broker()
        except Exception:  # noqa: BLE001
            pass
    return _singleton
