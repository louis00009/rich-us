"""IBKR 连接/事件域 mixin（FILE_SIZE_DEBT Batch F-2 从 ibkr.py 拆出）。

只提供方法；实例属性（_loop/_loop_lock/_connected/_pacer/_breaker 等）由组装类
ibkr.py 的 `IBKRBroker.__init__` 初始化。
⚠️ 铁律：IBKR 事件循环线程唯一（`_ensure_loop` 带 `_loop_lock`，runner 绑定局部 loop）；
gate 拒绝时 `_submit` 显式 close 未 await 的协程。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import queue
import threading
import time
from typing import Any, Callable

import pandas as pd

from ..markets import symbols as mksym
from ..markets.registry import get_market
from .base import AccountSnapshot, Broker, BrokerError, OrderResult, PositionItem, Tick
from .ibkr_common import BAR_MAP, INDEX_MAP, _ContractSpec, _silent
from .pacing import CircuitBreaker, Pacer

# 连接失败冷却（类级共享：TWS 关闭时避免每个调用路径都打 2s 超时连接风暴）
_CONNECT_COOLDOWN = 30.0
_connect_fail_until = 0.0


class IbkrConnMixin:
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
