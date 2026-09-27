"""券商抽象层。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class Tick:
    """一次行情更新。`engine/stream.py` 的内存缓存与广播都以它为单位。

    `recv_ns` 是**本地接收时刻**的单调纳秒，用于计算「行情延迟」
    （交易所/券商时间戳 − 本地接收时刻）。不要用墙上时钟做差值。
    """

    symbol: str
    price: float = 0.0
    bid: float | None = None
    ask: float | None = None
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_size: float = 0.0
    volume: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    currency: str = "USD"
    market: str = "US"
    source: str = "ibkr"
    ts: str = ""              # 交易所/券商时间（ISO）
    recv_ns: int = 0          # 本地单调纳秒
    seq: int = 0              # 自增序号，便于检测丢帧

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2.0
        return None

    @property
    def spread_bps(self) -> float:
        m = self.mid
        if not m or not self.bid or not self.ask:
            return 0.0
        return (self.ask - self.bid) / m * 10_000.0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mid"] = self.mid
        d["spread_bps"] = round(self.spread_bps, 3)
        return d


@dataclass
class AccountSnapshot:
    broker: str = "simulated"
    mode: str = "paper"
    connected: bool = False
    account_id: str = ""
    currency: str = "USD"                 # 账户计价币种
    base_currency: str = "USD"            # 统一折算基准币种
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    gross_position_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    day_pnl: float = 0.0
    day_pnl_pct: float = 0.0
    margin_used: float = 0.0
    fx_estimated: bool = False            # 是否使用了估算汇率（多币种折算时）
    message: str = ""

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PositionItem:
    symbol: str
    quantity: float = 0.0
    avg_cost: float = 0.0
    last_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pct: float = 0.0
    weight: float = 0.0
    strategy_id: int | None = None
    stop_price: float | None = None
    sec_type: str = "STK"
    currency: str = "USD"                 # 该持仓的计价币种
    market: str = "US"
    market_value_base: float = 0.0        # 折算到 base_currency 后的市值
    lot: int = 1                          # 每手股数（港股 >1）

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderResult:
    ok: bool
    order_id: str = ""
    status: str = "REJECTED"
    message: str = ""
    filled_qty: float = 0.0
    avg_price: float = 0.0
    commission: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0               # 提交往返耗时（毫秒）

    def dict(self) -> dict[str, Any]:
        return asdict(self)


class BrokerError(RuntimeError):
    pass


class Broker(ABC):
    name: str = "base"
    supports_live: bool = False
    supports_history: bool = False        # 能否从券商直接拉历史 K 线
    supports_streaming: bool = False      # 能否推送实时行情（reqMktData 级）

    def __init__(self, mode: str = "paper") -> None:
        self.mode = mode
        # 行情中枢注入的接收槽：券商在收到推送时调用它（不要在此做 IO）。
        # 用可赋值属性而非硬依赖，保证 brokers 包不反向依赖 engine 包。
        self.tick_sink: Callable[[Tick], None] | None = None

    def _emit_tick(self, tick: Tick) -> None:
        """把一条行情推给中枢。调用方必须处于 IO 已完成后的纯内存路径。"""
        sink = self.tick_sink
        if sink is None:
            return
        try:
            sink(tick)
        except Exception:  # noqa: BLE001  行情推送绝不能把券商线程拖垮
            pass

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def connect(self) -> tuple[bool, str]: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def account(self) -> AccountSnapshot: ...

    @abstractmethod
    def positions(self) -> list[PositionItem]: ...

    @abstractmethod
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
    ) -> OrderResult: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult: ...

    # ------------------------------------------------------------------
    # 以下为可选能力，默认实现退化为「用免费数据源」
    # ------------------------------------------------------------------
    def quote(self, symbol: str) -> dict[str, Any]:
        from ..data_provider import get_quote

        return get_quote(symbol)

    def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        from ..data_provider import get_quotes

        return get_quotes(symbols)

    def history(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> Any:
        """返回 DataFrame(open/high/low/close/volume)。无此能力时返回 None。"""
        return None

    def open_orders(self) -> list[dict[str, Any]]:
        return []

    def cancel_all(self) -> int:
        return 0

    def today_fills(self) -> list[dict[str, Any]]:
        return []

    def order_status_snapshot(self, order_id: str) -> dict[str, Any] | None:
        """返回该订单在券商侧的最新状态快照，用于订单落库时回填真实状态。

        存在的意义：券商可能在下单返回后、订单行写库前就推送成交回报，
        此时回调更新会因查不到行而丢失。默认实现返回 None（无此能力）。
        """
        return None

    # ---------------- 流式行情（可选能力）----------------
    def subscribe(self, symbols: list[str]) -> bool:
        """建立流式行情订阅。返回是否真正建立了流式（False 表示需降级为轮询）。"""
        return False

    def unsubscribe(self, symbols: list[str]) -> None:
        return None

    def get_tick(self, symbol: str) -> Tick | None:
        """读取本地缓存的最新 tick（**无 IO**，可高频调用）。"""
        return None

    def streamed_symbols(self) -> list[str]:
        return []

    def status(self) -> dict[str, Any]:
        return {
            "broker": self.name,
            "mode": self.mode,
            "connected": self.connected,
            "supports_history": self.supports_history,
            "supports_streaming": self.supports_streaming,
        }
