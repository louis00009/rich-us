"""EngineTask 的信号层 mixin（FILE_SIZE_DEBT Batch F-4 从 live.py 拆出）。

⚠️ 铁律 2（无未来函数）：`_build_signals` 的时序语义原样搬 ——
第 t 根收盘信号第 t+1 根开盘成交；末根 bar 未完成时退到上一根已完成 bar。
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

import numpy as np
import pandas as pd
from starlette.concurrency import run_in_threadpool

from ..data_provider import fetch_many, get_quotes
from ..strategies import SignalContext
from ..strategies.indicators import atr
from . import latency as lat
from .live_types import BacktestSpecLite
from .backtest import build_strategy


class _LiveSignalMixin:
    """信号层（重，低频）：拉历史 + 跑策略 → 目标权重。"""

    def _quotes(self, symbols: list[str]) -> dict[str, dict]:
        """取报价。优先级：中枢内存 → 券商 → 免费源。

        实盘必须用券商/中枢的价，否则会出现「看到的价格 ≠ 成交的价格」。
        """
        out: dict[str, dict] = {}
        hub_hits = broker_hits = fb_hits = 0

        # 1) 中枢内存（零 IO）
        hub = self._hub
        if hub is not None:
            for s in symbols:
                t = hub.latest(s)
                if t is None or t.price <= 0:
                    continue
                out[s.upper()] = {
                    "symbol": t.symbol, "price": t.price,
                    "prev_close": t.prev_close, "volume": t.volume,
                    "day_high": t.high, "day_low": t.low, "open": t.open,
                    "bid": t.bid, "ask": t.ask,
                    "currency": t.currency, "market": t.market,
                    "source": t.source,
                    "mode": "stream" if t.source == "ibkr-stream" else "snapshot",
                    "ts": t.ts, "recv_ns": t.recv_ns,
                }
                hub_hits += 1

        # 2) 券商直取（仅补中枢没有的）
        missing = [s for s in symbols if s.upper() not in out]
        if missing:
            try:
                broker = self._broker()
                for r in broker.quotes(missing) or []:
                    if r.get("price", 0) > 0:
                        out[str(r["symbol"]).upper()] = r
                        broker_hits += 1
            except Exception:  # noqa: BLE001
                pass

        # 3) 免费源兜底
        missing = [s for s in symbols if s.upper() not in out]
        if missing:
            try:
                for r in get_quotes(missing):
                    if r.get("price", 0) > 0:
                        out[str(r["symbol"]).upper()] = r
                        fb_hits += 1
            except Exception:  # noqa: BLE001
                pass

        if hub_hits:
            self.last_quotes_source = "hub-stream" if broker_hits == fb_hits == 0 else "hub+网络"
        elif broker_hits:
            self.last_quotes_source = "broker"
        elif fb_hits:
            self.last_quotes_source = "fallback"
        else:
            self.last_quotes_source = "none"
        return out

    def _build_signals(self) -> tuple[pd.DataFrame | None, list[str], dict[str, float]]:
        """返回 (最新目标权重, 有效标的, 各标的 ATR)。

        ATR 与信号同源同批计算，避免止损用「持仓价差」冒充波动率——
        那会让 atr_trailing / chandelier 的止损距离变成固定百分比甚至接近 0。
        """
        end = dt.date.today().isoformat()
        start = (dt.date.today() - dt.timedelta(days=self.warmup_days)).isoformat()
        data, _ = fetch_many(self.symbols, start, end, "1d")
        if not data:
            return None, [], {}
        symbols = [s for s in self.symbols if s in data]

        # P1-1：策略 bar 序号推进 —— 末根 bar 的时间戳变化即「进入新的一根 bar」。
        # 时间止损（StopTracker.time_stop_bars）依赖它，必须按 bar 而非 tick 计。
        try:
            ref = data.get(symbols[0]) if symbols else None
            key = str(ref.index[-1]) if ref is not None and len(ref) else None
            if key and key != self._last_bar_key:
                self._last_bar_key = key
                self._bar_seq += 1
        except Exception:  # noqa: BLE001 —— bar 序号推进失败不得影响信号生成
            pass

        atr_map: dict[str, float] = {}
        for s in symbols:
            df = data[s]
            try:
                a = atr(df["high"], df["low"], df["close"], int(self.stop_cfg.atr_period) or 14)
                val = float(a.iloc[-1])
                atr_map[s] = val if np.isfinite(val) and val > 0 else 0.0
            except Exception:  # noqa: BLE001
                atr_map[s] = 0.0

        ctx = SignalContext(data=data, symbols=symbols, timeframe="1d")
        spec = BacktestSpecLite(
            strategy_key=self.spec_key, symbols=symbols, params=self.params,
            rule=self.rule, code=self.code,
        )
        try:
            strategy = build_strategy(spec)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"策略加载失败: {exc}"
            return None, [], atr_map
        w = strategy.run(ctx)
        if w.empty:
            return None, [], atr_map
        # P1-2：消除「同 bar 前视」，与回测口径对齐。
        # 回测刻意用第 t 根收盘信号在第 t+1 根开盘成交（backtest.py:224-247），
        # 而实盘旧实现取 w.iloc[[-1]]（可能就是当日**尚未收盘**的 bar）后立刻按当前价
        # 下单 —— 等于「用 bar t 的收盘价在 bar t 成交」，系统性优于回测，
        # 导致回测验证过的策略在实盘表现完全不同。
        # 这里：末根 bar 的日期若已是「今天」（即当日未完成），退到上一根已完成的 bar。
        idx = -1
        try:
            ref = data.get(symbols[0]) if symbols else None
            # len(w) >= 2 必须一并判断：idx=-2 在只有一根 bar 时会 IndexError
            if ref is not None and len(ref) >= 2 and len(w) >= 2:
                from zoneinfo import ZoneInfo

                tzname = "Asia/Hong_Kong" if str(symbols[0]).upper().endswith(".HK") else "America/New_York"
                if ref.index[-1].date() >= dt.datetime.now(ZoneInfo(tzname)).date():
                    idx = -2
        except Exception:  # noqa: BLE001 —— 时区判断失败时保守取末根（与旧行为一致）
            idx = -1
        return w.iloc[[idx]], symbols, atr_map

    # ------------------------------------------------------------------
    def _atr_for(self, sym: str) -> float:
        """取该标的的 ATR。

        信号阶段已按策略标的算过就直接复用；若持仓不在策略标的里
        （例如手动建仓 / 引擎重启后接管），按需拉一次日线补算并缓存。
        """
        v = self._atr_map.get(sym) or self._atr_map.get(sym.upper())
        if v and v > 0:
            return float(v)
        try:
            from ..data_provider import fetch_history

            end = dt.date.today().isoformat()
            start = (dt.date.today() - dt.timedelta(days=max(self.warmup_days, 120))).isoformat()
            df, _ = fetch_history(sym, start=start, end=end, interval="1d")
            period = int(self.stop_cfg.atr_period) or 14
            if df is not None and len(df) > period + 1:
                val = float(atr(df["high"], df["low"], df["close"], period).iloc[-1])
                if np.isfinite(val) and val > 0:
                    self._atr_map[sym] = val
                    return val
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    async def _refresh_signals(self) -> None:
        """信号层：拉历史 + 跑策略 → 目标权重。**不涉及下单，不进风控。**"""
        t0 = time.perf_counter()
        try:
            weights, symbols, atr_map = await run_in_threadpool(self._build_signals)
            self._atr_map.update(atr_map)
            if weights is None or not symbols:
                self.last_signal_error = self.last_error or "策略未产生有效信号"
                return
            w_row = weights.iloc[0].reindex(symbols).fillna(0.0)
            self.last_targets = {s: round(float(v), 4) for s, v in w_row.items()}
            self._signal_symbols = list(symbols)
            self.last_signal_at = dt.datetime.now(dt.timezone.utc).isoformat()
            self.last_signal_error = ""
        except Exception as exc:  # noqa: BLE001
            self.last_signal_error = f"信号计算失败：{type(exc).__name__}: {exc}"
        finally:
            self._signal_duration_ms = (time.perf_counter() - t0) * 1000.0
            lat.get_latency().record(lat.SIGNAL_BUILD, self._signal_duration_ms)

    def _signal_age_sec(self) -> float:
        if not self.last_signal_at:
            return float("inf")
        try:
            t = dt.datetime.fromisoformat(self.last_signal_at)
        except ValueError:
            return float("inf")
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
