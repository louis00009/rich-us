"""券商适配包与工厂。"""
from __future__ import annotations

from typing import Any

from .base import AccountSnapshot, Broker, BrokerError, OrderResult, PositionItem  # noqa: F401
from .ibkr import IBKRBroker, get_ibkr  # noqa: F401
from .simulated import SimulatedBroker  # noqa: F401

_sim_singleton: SimulatedBroker | None = None


def get_simulated() -> SimulatedBroker:
    global _sim_singleton
    if _sim_singleton is None:
        _sim_singleton = SimulatedBroker()
        _sim_singleton.connect()
    return _sim_singleton


def get_broker(settings_row: dict[str, Any] | None = None) -> tuple[Broker, str]:
    """
    根据当前券商设置返回 (Broker, 当前模式)。
    provider = simulated → 模拟券商（零资金风险）
    provider = ibkr      → IBKR（端口决定纸面/实盘）
    """
    cfg = settings_row or {}
    provider = str(cfg.get("provider", "simulated"))
    port = int(cfg.get("port", 7497))
    if provider == "ibkr":
        mode = "live" if port in (7496, 4001) else "paper"
        broker = get_ibkr({**cfg, "mode": mode})
        return broker, mode
    return get_simulated(), "paper"


# ==================================================================
# 把 IBKR 注册为数据层可选的优先数据源
# ==================================================================
class IBKRDataProvider:
    """
    适配器：让 data_provider 能把 IBKR 当作历史 K 线 / 实时报价来源。

    仅在「券商已配置为 ibkr 且连接可用」时生效；否则返回空，
    data_provider 会自动降级到 yfinance → Stooq → 合成行情。
    不在回测线程里主动发起连接（避免阻塞），需要用户先在「系统设置」点「测试连接」。
    """

    name = "ibkr"

    def _broker(self) -> IBKRBroker | None:
        try:
            from .. import state as appstate

            cfg = appstate.get_broker_settings()
            if str(cfg.get("provider")) != "ibkr":
                return None
            broker, _ = get_broker(cfg)
            if not isinstance(broker, IBKRBroker) or not broker.connected:
                return None
            return broker
        except Exception:  # noqa: BLE001
            return None

    def history(self, symbol: str, start: str | None, end: str | None, interval: str):
        b = self._broker()
        if b is None:
            return None
        try:
            df = b.history(symbol, start, end, interval)
            return df if df is not None and len(df) > 20 else None
        except Exception:  # noqa: BLE001
            return None

    def snapshot(self, symbols) -> list[dict]:
        b = self._broker()
        if b is None:
            return []
        try:
            return b.snapshot(list(symbols))
        except Exception:  # noqa: BLE001
            return []

    def status(self) -> dict:
        b = self._broker()
        if b is None:
            return {
                "name": "ibkr",
                "available": False,
                "reason": "未连接到 IBKR（请先在系统设置中测试连接）",
            }
        st = b.status()
        st["available"] = True
        return st


def register_data_providers() -> None:
    from ..data_provider import (
        register_history_provider,
        register_local_provider,
        register_twelvedata_provider,
    )

    register_history_provider("ibkr", IBKRDataProvider())
    # TwelveData（多 Key 轮询池）也进注册表：这样它会出现在
    # 「设置 → 数据与缓存 → 源健康状态」里，并能被选为优先数据源。
    register_twelvedata_provider()
    # 本地历史库（IBKR 灌库产物）—— 非空才注册
    register_local_provider()


register_data_providers()


__all__ = [
    "Broker", "BrokerError", "AccountSnapshot", "PositionItem", "OrderResult",
    "IBKRBroker", "SimulatedBroker", "IBKRDataProvider",
    "get_broker", "get_simulated", "get_ibkr", "register_data_providers",
]
