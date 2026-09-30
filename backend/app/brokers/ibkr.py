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


from .ibkr_account import IbkrAccountMixin
from .ibkr_common import (  # noqa: F401  re-export 保持旧 import 路径
    BAR_MAP,
    INDEX_MAP,
    _ContractSpec,
    _silent,
)
from .ibkr_conn import IbkrConnMixin
from .ibkr_market import IbkrMarketMixin
from .ibkr_orders import IbkrOrderMixin, _apply_status_snapshot  # noqa: F401  re-export


class IBKRBroker(IbkrConnMixin, IbkrMarketMixin, IbkrAccountMixin, IbkrOrderMixin, Broker):
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
