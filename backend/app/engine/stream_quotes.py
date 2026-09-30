"""MarketDataHub 的报价查询 mixin（FILE_SIZE_DEBT Batch E-3 从 stream.py 拆出）。

把内存缓存的 `Tick` 转成前端兼容的报价字典；对完全没有数据的标的必要时同步取一次
（券商优先 → data_provider 降级链），让前端首屏不必等「第一帧推送」。

⚠️ mixin 只提供方法：`_symbols` / `stats` / `_lock` 等属性一律由
   `MarketDataHub.__init__` 创建，mixin 绝不自行创建。
"""
from __future__ import annotations

import time
from typing import Any

from ..brokers.base import Tick
from . import latency as _lat
from .stream_types import (
    MODE_OFFLINE,
    MODE_SNAPSHOT,
    MODE_STREAM,
    SOURCE_STREAM,
    _num,
    tick_from_quote,
)


class _QuoteMixin:
    """报价查询：内存优先，缺失时同步兜底取一次。"""

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
