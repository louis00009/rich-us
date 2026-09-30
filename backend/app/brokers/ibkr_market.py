"""IBKR 行情/合约域 mixin（FILE_SIZE_DEBT Batch F-2 从 ibkr.py 拆出）。

流式订阅 + 本地 tick 缓存 + 快照 + 历史分页。
⚠️ broker.connected == True ≠ 数据农场可用：TWS 报 2103/2105 时 TCP 仍活，
`history()` 会静默返回空 —— 探活逻辑原样保留，不许动。
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


class IbkrMarketMixin:
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

    def quote(self, symbol: str) -> dict[str, Any]:
        rows = self.snapshot([symbol])
        return rows[0] if rows else {"symbol": symbol.upper(), "price": 0.0, "source": "ibkr"}

    def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        return self.snapshot(symbols)
