"""
实时交易引擎
=============
把「策略信号」变成「真实订单」的最后一公里，全程受风控护栏约束。

一个 tick 的流程：
    1. 拉取持仓与账户（含当日开盘权益、历史峰值权益，用于日亏/回撤熔断）
    2. 拉取行情，构造 SignalContext，跑策略得到最新目标权重
    3. 与当前持仓做差分，得到需要调仓的标的与目标名义金额
    4. 逐单通过 risk.guardrails.check_order —— 任一不通过则跳过并审计
    5. 通过则下单，记录 Order 与 Fill，并写入审计日志
    6. 为新建仓位登记 StopTracker（价格触及由 tick 内的止损检查负责平仓）
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..brokers import get_broker
from ..brokers.base import Broker
from ..data_provider import fetch_many, get_quote, get_quotes
from ..markets import symbols as mksym
from ..risk.guardrails import RiskLimits, check_order
from ..risk.sizing import cap_targets, weights_to_notionals
from ..risk.stops import StopConfig, StopTracker
from ..strategies import SignalContext
from ..strategies.indicators import atr
from . import latency as lat
from .backtest import build_strategy

ACTIVE_ENGINES: dict[int, "EngineTask"] = {}


@dataclass
class EngineTick:
    ts: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    target_weights: dict[str, float] = field(default_factory=dict)
    account_equity: float = 0.0
    # 执行元数据（延迟面板 / 前端状态展示用）
    signal_age_sec: float = 0.0        # 这份目标权重距今多久
    signal_recomputed: bool = False    # 本 tick 是否重算了信号
    exec_ms: float = 0.0                # 本轮执行耗时
    quote_source: str = ""             # hub-stream | hub-snapshot | broker | fallback
    phase: str = "exec"                # signal | exec


class EngineTask:
    """单个策略的实时运行任务。"""

    def __init__(
        self,
        engine_run_id: int,
        strategy_id: int,
        strategy_name: str,
        spec_key: str,
        params: dict,
        rule: dict | None,
        code: str,
        symbols: list[str],
        mode: str,
        interval_sec: float,
        stop_cfg: StopConfig,
        limits: RiskLimits,
        sizing_method: str = "weight",
        risk_per_trade_pct: float = 1.0,
        max_position_pct: float = 20.0,
        gross_pct: float = 100.0,
        warmup_days: int = 400,
        place_protective: bool = True,
        exec_interval_sec: float = 1.0,
        exec_mode: str = "event",
        rebalance_deadband_pct: float = 0.5,
    ) -> None:
        self.engine_run_id = engine_run_id
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.spec_key = spec_key
        self.params = params
        self.rule = rule
        self.code = code
        # 符号规范化：`0700` / `700` / `0700.HK` 在引擎内部统一成 `0700.HK`，
        # 否则行情缓存、持仓匹配、手数规则、费用模型会各按各的写法去找，永远对不上。
        self.symbols = [mksym.normalize(s) for s in (symbols or []) if str(s or "").strip()]
        self.mode = mode
        # ---------- 双层节奏 ----------
        # 信号层：重算目标权重（拉历史 + 跑策略，重）。旧实现把它和执行绑死，
        # 于是「想快点下单」只能连历史数据一起重拉，根本快不了。
        self.interval_sec = max(0.05, float(interval_sec))
        # 执行层：读内存行情 + 风控 + 下单（轻，可亚秒级）
        self.exec_interval_sec = max(0.02, float(exec_interval_sec))
        # event：有推送就立刻执行；poll：固定节奏
        self.exec_mode = str(exec_mode or "event").lower()
        # 调仓死区（占权益百分比）：差额低于它就完全不动仓
        self.rebalance_deadband_pct = max(0.0, float(rebalance_deadband_pct))
        self.stop_cfg = stop_cfg
        self.limits = limits
        self.sizing_method = sizing_method
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.gross_pct = gross_pct
        self.warmup_days = warmup_days
        # 实盘时为每笔持仓挂交易所侧的保护性止损/止盈单（防止引擎掉线后无保护）
        self.place_protective = bool(place_protective)
        self.protective_orders: dict[str, dict[str, str]] = {}

        self.task: asyncio.Task | None = None
        self.running = False
        self.tick_count = 0
        self.last_tick: str | None = None
        self.last_error = ""
        self.trackers: dict[str, StopTracker] = {}
        self.last_targets: dict[str, float] = {}
        self.last_tick_detail: EngineTick | None = None
        self._peak_equity = 0.0
        self._atr_map: dict[str, float] = {}
        # 券商名称用于订单落库后的状态回写匹配（ibkr | simulated），
        # 不能用 mode 判断：IBKR 的纸面账户同样是 mode="paper"。
        self._broker_name = "simulated"

        # ---------- 事件驱动相关 ----------
        self._hub = None                      # 行情中枢
        self._sub = None                      # 中枢订阅者（拉取模式）
        self._wake_event: asyncio.Event | None = None
        self._wake_loop: asyncio.AbstractEventLoop | None = None
        self._next_signal_at = 0.0            # loop.time() 截止点，消除累积漂移
        self._signal_duration_ms = 0.0
        self._signal_symbols: list[str] = []
        self.last_signal_at: str | None = None
        self.last_signal_error = ""
        self.exec_count = 0
        self.tick_wakeups = 0                 # 因行情推送被唤醒的次数
        self.timer_wakeups = 0                # 因定时器被唤醒的次数
        self.exec_loop_ms: deque[float] = deque(maxlen=256)
        self.last_quotes_source = ""
        # P1-7：止损离场冷却（symbol -> epoch 秒）。
        # 旧实现平仓后立刻 reset tracker，若券商尚未回填新持仓，下一 tick 接管逻辑
        # 会重建同参数止损并可能再次触发 —— 隔 tick 重复下市价卖单。
        self._stop_exit_at: dict[str, float] = {}
        # P1-1：策略 bar 序号 —— 时间止损必须按 **bar** 计，不能按执行 tick 计。
        # 旧实现把 tick_count（每个执行周期 +1，exec_interval_sec 可低至 0.02s）
        # 当 bar_index 传给 StopTracker，于是「5 bar 时间止损」在实盘 = 0.1~5 秒平仓，
        # 而回测里同样的 5 = 5 个交易日 —— 回测结论完全无法外推。
        # 这里改为：只有出现新的策略 bar（末根时间戳变化）才 +1。
        self._bar_seq = 0
        self._last_bar_key: str | None = None

    # ------------------------------------------------------------------
    def _live_limits(self) -> tuple[RiskLimits, bool]:
        """每 tick 重读风控配置。

        EngineTask 构造时拷贝的 limits 是快照，若一直沿用，运行中启用熔断
        或收紧限额将完全无效——这会让「熔断」在引擎运行期间形同虚设。
        """
        try:
            row = appstate.get_risk_row()
            limits = RiskLimits.from_config(row)
            # 止损配置同步热加载：原地改字段，已存在的 StopTracker 持有同一对象引用
            self.stop_cfg.stop_type = getattr(row, "stop_type", self.stop_cfg.stop_type) or "none"
            self.stop_cfg.stop_value = float(getattr(row, "stop_value", self.stop_cfg.stop_value) or self.stop_cfg.stop_value)
            self.stop_cfg.take_profit_r = float(getattr(row, "take_profit_r", self.stop_cfg.take_profit_r) or 0.0)
            self.stop_cfg.time_stop_bars = int(getattr(row, "time_stop_bars", self.stop_cfg.time_stop_bars) or 0)
            self.limits = limits
            # 仓位算法参数同样热加载，否则「改了风控但引擎还在按旧上限下单」
            self.sizing_method = getattr(row, "sizing_method", self.sizing_method) or "weight"
            self.risk_per_trade_pct = float(getattr(row, "risk_per_trade_pct", self.risk_per_trade_pct) or 1.0)
            self.max_position_pct = limits.max_position_pct
            self.gross_pct = limits.max_gross_exposure_pct
            return limits, bool(row.kill_switch)
        except Exception:  # noqa: BLE001
            return self.limits, bool(getattr(self.limits, "kill_switch", False))

    # ------------------------------------------------------------------
    def _broker(self) -> Broker:
        broker, _ = get_broker(appstate.get_broker_settings())
        # 记录真实券商名：订单状态回写依赖它匹配（IBKR 纸面账户也是 mode=paper）
        self._broker_name = getattr(broker, "name", "simulated") or "simulated"
        return broker

    # ------------------------------------------------------------------
    # 行情中枢接入
    #
    # 这是「毫秒级」的地基：旧实现每个 tick 都调 broker.quotes() → 一次 IB
    # 网络往返（最坏 40s 超时）。现在改成中枢内存读取（实测 < 1µs），
    # 只在内存彻底没数据时才落回网络。
    # ------------------------------------------------------------------
    def _attach_hub(self) -> None:
        try:
            from .stream import get_hub

            hub = get_hub()
            self._hub = hub
            self._wake_loop = asyncio.get_running_loop()
            self._wake_event = asyncio.Event()
            # 拉取模式 + on_tick 回调：回调在发布线程执行，只做一个线程安全的唤醒，
            # 真正的行情读取仍在事件循环里从内存取。
            #
            # 注意：`subscribe_events` 内部已经会 `ensure()`（引用计数 +1），
            # 这里**不能**再单独调一次 `hub.ensure()` —— 那会让计数变成 2，
            # 而退订时只减 1，订阅就永久泄漏在进程里。
            self._sub = hub.subscribe_events(
                self.symbols, loop=None, on_tick=self._on_hub_tick, sid=f"engine-{self.engine_run_id}",
            )
            appstate.log(
                "engine_hub", "INFO",
                f"引擎 #{self.engine_run_id} 已接入行情中枢（{', '.join(self.symbols)}）· "
                f"执行模式={self.exec_mode} 执行周期={self.exec_interval_sec:g}s "
                f"信号周期={self.interval_sec:g}s",
            )
        except Exception as exc:  # noqa: BLE001
            self._hub = None
            self.last_error = f"接入行情中枢失败（将退回逐次请求行情）：{exc}"

    def _detach_hub(self) -> None:
        try:
            if self._hub is not None and self._sub is not None:
                self._hub.unsubscribe_events(self._sub.id, release=True)
        except Exception:  # noqa: BLE001
            pass
        self._sub = None
        self._hub = None
        self._wake_event = None
        self._wake_loop = None

    def _on_hub_tick(self, tick: Any) -> None:
        """中枢推送回调（运行在发布线程）。只做唤醒，绝不做业务逻辑。"""
        loop = self._wake_loop
        ev = self._wake_event
        if loop is None or ev is None:
            return
        try:
            loop.call_soon_threadsafe(ev.set)
        except RuntimeError:
            pass

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

    def _check_stops(self, broker: Broker, equity: float) -> list[dict[str, Any]]:
        """对已有持仓执行止损检查（用券商或免费源的实时行情）。"""
        actions: list[dict[str, Any]] = []
        plist = broker.positions()
        if not plist:
            return actions
        qmap = self._quotes([p.symbol for p in plist])

        for p in plist:
            sym = p.symbol
            if abs(p.quantity) < 1e-9:
                continue
            # P1-7：止损离场冷却 —— 刚提交过止损市价单的标的，在券商回填新持仓前
            # 不再重复触发（exec_interval_sec 可低至 0.05s，旧实现会隔 tick 重复平仓）。
            if time.time() - self._stop_exit_at.get(sym, 0.0) < 30.0:
                continue
            q = qmap.get(sym.upper())
            if not q:
                continue
            px = float(q.get("price") or 0)
            if px <= 0:
                continue
            high = float(q.get("day_high") or px)
            low = float(q.get("day_low") or px)

            tr = self.trackers.get(sym)
            needs_takeover = tr is None or not tr.s.active
            if needs_takeover:
                # 接管引擎外已存在的持仓：用成本价建仓 + 真实 ATR 定初始止损。
                # 旧实现这里直接 continue 且从不 open()，导致 s.active 永远为 False，
                # 下一 tick 又新建一个 tracker —— 止损对这类持仓永不生效。
                if tr is None:
                    tr = StopTracker(self.stop_cfg, sym)
                    self.trackers[sym] = tr
                entry = float(p.avg_cost or px)
                # P1-1：传策略 bar 序号（_bar_seq），不是执行 tick 数
                tr.open(1 if p.quantity > 0 else -1, entry, self._bar_seq, self._atr_for(sym) or None)
                actions.append({
                    "type": "STOP_TAKEOVER", "symbol": sym, "side": "BUY" if p.quantity > 0 else "SELL",
                    "quantity": abs(p.quantity), "entry": round(entry, 4),
                    "stop_price": round(tr.current_stop(), 4), "ok": True,
                    "reason": f"接管持仓并建立止损跟踪（{self.stop_cfg.stop_type}）",
                })
                # 接管当 tick 不判定：避免用接管前的日内极值立刻误触
                continue

            cfg = self.stop_cfg
            atr_val = self._atr_for(sym) or None if cfg.stop_type in (
                "atr_fixed", "atr_trailing", "chandelier", "volatility"
            ) else None

            hit, reason, stop_px = tr.update(high, low, px, atr_val, self._bar_seq)
            if not hit:
                continue

            # 先撤掉保护性挂单，避免重复平仓
            self._cancel_protective(broker, sym)

            side = "SELL" if p.quantity > 0 else "BUY"
            self._stop_exit_at[sym] = time.time()   # P1-7：无论成败都进入冷却，防重复市价单
            res = broker.place_order(sym, side, abs(p.quantity), "MKT")
            actions.append({
                "type": "STOP_EXIT", "symbol": sym, "side": side,
                "quantity": abs(p.quantity), "reason": reason,
                "stop_price": round(stop_px, 4),
                "ok": res.ok, "message": res.message,
            })
            appstate.log(
                "stop_exit", "WARN" if res.ok else "CRITICAL",
                f"{sym} 止损离场 {side} {abs(p.quantity):.4f} @ 触发价 {stop_px:.4f}（{reason}）",
                detail=res.message,
            )
            if res.ok:
                self._persist_order(
                    sym, side, abs(p.quantity), res, stop_px,
                    order_type="MKT", reason=f"止损离场 · {reason}", broker=broker,
                )
                tr.s.reset()
        return actions

    # ------------------------------------------------------------------
    # 保护性挂单（实盘专用）：把止损/止盈挂到交易所侧，
    # 这样即使引擎进程掉线，持仓依然有保护。
    # ------------------------------------------------------------------
    def _place_protective(self, broker: Broker, sym: str, qty: float, side: str, ref_px: float) -> None:
        if not (self.place_protective and self.mode == "live"):
            return
        if sym in self.protective_orders and self.protective_orders[sym]:
            return
        tr = self.trackers.get(sym)
        stop_px = tr.current_stop() if tr and tr.s.active else 0.0
        cfg = self.stop_cfg
        opp = "SELL" if side.upper() == "BUY" else "BUY"
        placed: dict[str, str] = {}

        if cfg.stop_type != "none" and stop_px > 0:
            res = broker.place_order(sym, opp, qty, "STP", stop_price=round(stop_px, 2), tif="GTC")
            if res.ok:
                placed["stop"] = res.order_id

        if cfg.take_profit_r > 0 and tr and tr.s.active and tr.s.r_distance > 0:
            # P2-10：止盈必须锚定**实际建仓价**。旧实现用 ref_px（调用方传的是
            # res.avg_price or px），而 IBKR 异步下单时 avg_price 常为 0 →
            # 退化成用「当前价」锚定 R 距离，交易所侧止盈价随之偏移。
            # StopTracker 里的 entry_price 才是真实建仓价。
            anchor = tr.s.entry_price if tr.s.entry_price > 0 else ref_px
            tp = anchor + (1 if side.upper() == "BUY" else -1) * tr.s.r_distance * cfg.take_profit_r
            res = broker.place_order(sym, opp, qty, "LMT", limit_price=round(tp, 2), tif="GTC")
            if res.ok:
                placed["target"] = res.order_id

        if placed:
            self.protective_orders[sym] = placed
            appstate.log("protective_orders", "INFO",
                         f"已为 {sym} 挂保护性委托：{placed}（止损价 {stop_px:.2f}）")

    def _cancel_protective(self, broker: Broker, sym: str) -> None:
        ids = self.protective_orders.pop(sym, None)
        if not ids:
            return
        for kind, oid in ids.items():
            try:
                res = broker.cancel_order(oid)
                if res.ok:
                    appstate.log("protective_cancel", "INFO", f"已撤销 {sym} 的保护性委托（{kind} {oid}）")
            except Exception:  # noqa: BLE001
                continue

    def _cancel_all_protective(self, broker: Broker | None = None) -> int:
        """撤销本引擎挂出的**全部**保护性委托（P1-4）。

        引擎停止 / 进程掉线前必须清场。旧实现的 `_loop` finally 与 `stop()` 都不撤销，
        残留的 GTC STP/LMT 单在持仓已被平掉后触发会**反向开仓**
        （无持仓时 STP 成交即成裸空/裸多）—— 与「保护性委托」的设计意图相反。

        返回尝试撤销的标的数。券商不可用时**显式告警**而不是静默丢弃。
        """
        syms = list(self.protective_orders.keys())
        if not syms:
            return 0
        if broker is None:
            try:
                broker = self._broker()
            except Exception:  # noqa: BLE001
                broker = None
        if broker is None:
            appstate.log(
                "protective_cancel_failed", "CRITICAL",
                f"引擎停止时无法连接券商，{len(syms)} 个标的的保护性委托未撤销："
                f"{', '.join(syms)}（请在券商端手工撤单）",
            )
            self.protective_orders.clear()
            return 0
        for sym in syms:
            try:
                self._cancel_protective(broker, sym)
            except Exception:  # noqa: BLE001 —— 单个标的失败不影响其余
                continue
        return len(syms)

    # ------------------------------------------------------------------
    # 信号层（重，低频）与执行层（轻，高频）解耦
    #
    # 旧实现把两者绑在同一个 `while: run_once(); sleep(interval)` 里：
    #   · 想提高下单频率 → 每轮都要重拉 400 天历史 + 重跑策略（秒级开销）
    #   · interval 被 `max(10, int(...))` 与 schema 的 `ge=10` 双重钳死
    #   · `asyncio.sleep(interval)` 是「执行完再睡」，每轮把执行耗时累加进去，
    #     误差不断累积（做 1s 周期实际能漂到 1.5s+）
    # 现在：信号按 interval_sec 重算，执行按 exec_interval_sec（或行情事件）触发，
    #      截止点用 `loop.time()` 绝对时间表示，漂移不再累积。
    # ------------------------------------------------------------------
    async def run_once(self, dry_run: bool = False) -> EngineTick:
        """完整跑一轮（重算信号 + 执行）。用于「立即执行一次」与试运行。"""
        await self._refresh_signals()
        return await self._execute(dry_run=dry_run)

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

    async def _execute(self, dry_run: bool = False) -> EngineTick:
        """执行层：读内存行情 + 止损 + 风控 + 下单。**不拉历史、不跑策略。**"""
        t_exec = time.perf_counter()
        ts = dt.datetime.now(dt.timezone.utc).isoformat()
        tick = EngineTick(ts=ts, phase="exec")
        tick.signal_age_sec = round(self._signal_age_sec(), 3)
        tick.target_weights = dict(self.last_targets)
        try:
            # --- 风控热加载：熔断与限额调整必须即时生效 ---
            limits, kill = self._live_limits()
            if kill:
                tick.errors.append("⛔ 熔断开关已启用，本 tick 跳过全部下单（配置解除后自动恢复）")
                self._update_run_row("RUNNING", msg="熔断中：暂停下单")
                return tick
            if self.mode == "live" and not appstate.live_unlocked():
                tick.errors.append("⛔ 实盘已重新锁定，本 tick 跳过下单")
                self._update_run_row("RUNNING", msg="实盘已锁定：暂停下单")
                return tick

            symbols = list(getattr(self, "_signal_symbols", []) or [])
            if not self.last_targets or not symbols:
                tick.errors.append(self.last_signal_error or "策略尚未产生有效信号")
                return tick
            w_row = pd.Series({s: float(self.last_targets.get(s, 0.0)) for s in symbols})

            broker = self._broker()
            acc = await run_in_threadpool(broker.account)
            tick.account_equity = acc.equity
            if acc.equity <= 0:
                tick.errors.append(
                    getattr(acc, "message", "") or "账户权益为 0，无法计算仓位；请检查券商连接"
                )
                return tick

            # --- 止损优先 ---
            if not dry_run:
                stops = await run_in_threadpool(self._check_stops, broker, acc.equity)
                tick.actions.extend(stops)
                if stops:
                    acc = await run_in_threadpool(broker.account)

            plist = await run_in_threadpool(broker.positions)
            positions = {p.symbol: p for p in plist}
            peak = max(acc.equity, self._peak_equity, acc.equity - acc.day_pnl)
            self._peak_equity = peak

            # P0-5/P1-5：护栏上下文中心化构造 —— 计数器（日内/每分钟笔数）与
            # 分市场敞口（HKD→base 折算）此前从未赋值，三条风控形同虚设。
            ctx = appstate.build_guard_context(acc, plist)

            # 取行情：中枢内存优先（µs 级），缺的才走网络
            qmap = await run_in_threadpool(self._quotes, symbols)
            tick.quote_source = self.last_quotes_source

            def px_of(s: str) -> float:
                q = qmap.get(s.upper())
                if q and float(q.get("price") or 0) > 0:
                    return float(q["price"])
                p = positions.get(s)
                return float(p.last_price) if p and p.last_price else 0.0

            if self.sizing_method and self.sizing_method != "weight":
                prices = pd.Series({s: px_of(s) for s in symbols})
                targets = weights_to_notionals(
                    w_row, acc.equity, prices, self.sizing_method,
                    max_position_pct=self.max_position_pct, gross_pct=self.gross_pct,
                    risk_per_trade_pct=self.risk_per_trade_pct, stop_mult=self.stop_cfg.stop_value,
                )
            else:
                # P0-1：weight 模式同样必须施加两级组合约束。
                # 旧实现 targets = 权重 × 权益，无单标的上限、无总敞口约束 ——
                # 多标的策略输出逐标的 ±1 权重时会凭空放大杠杆。
                targets = cap_targets(
                    {s: float(w_row[s]) * acc.equity for s in symbols},
                    acc.equity, self.max_position_pct, self.gross_pct,
                )

            for sym in symbols:
                target_notional = targets.get(sym, 0.0)
                cur = positions.get(sym)
                cur_qty = cur.quantity if cur else 0.0
                px = px_of(sym)
                if px <= 0:
                    continue
                cur_notional = cur_qty * px
                delta_notional = target_notional - cur_notional
                # 调仓死区：低于权益的这个比例就不动，避免为几块钱反复交易。
                # 旧实现是硬编码的 0.005 且**静默跳过** —— 用户看到「策略有信号但没下单」
                # 完全无从排查。现在把死区做成常量，并对「明显有信号但被死区挡下」的情况
                # 显式记录一条 skipped，让界面能解释清楚。
                deadband = acc.equity * self.rebalance_deadband_pct / 100.0
                if abs(delta_notional) < deadband:
                    if abs(delta_notional) >= deadband * 0.2:
                        tick.skipped.append({
                            "symbol": sym, "side": "BUY" if delta_notional > 0 else "SELL",
                            "quantity": 0.0, "code": "BELOW_DEADBAND",
                            "reason": (
                                f"目标名义差额 {abs(delta_notional):,.0f} 低于调仓死区 "
                                f"{deadband:,.0f}（权益的 {self.rebalance_deadband_pct:g}%），"
                                f"本次不动仓"
                            ),
                        })
                    continue

                delta_qty = delta_notional / px
                side = "BUY" if delta_qty > 0 else "SELL"
                qty = abs(delta_qty)

                # ---- 手数取整（港股每手可能 100/200/400 股，必须取整）----
                lot = 1
                lot_note = ""
                try:
                    from ..markets.lots import round_qty

                    qty_r, lot, lot_note = round_qty(sym, qty, side=side)
                    qty = qty_r
                except Exception as exc:  # noqa: BLE001
                    lot_note = f"手数规则不可用：{exc}"
                if qty <= 0:
                    tick.skipped.append({
                        "symbol": sym, "side": side, "quantity": round(qty, 4),
                        "code": "LOT_TOO_SMALL",
                        "reason": f"按每手 {lot} 股取整后不足 1 手（目标名义 {target_notional:,.0f}）"
                                  + (f"；{lot_note}" if lot_note else ""),
                    })
                    continue

                t_risk = time.perf_counter()
                guard = check_order(
                    symbol=sym, side=side, quantity=qty, price=px,
                    limits=limits, ctx=ctx,
                )
                lat.get_latency().record(lat.RISK_CHECK, (time.perf_counter() - t_risk) * 1000.0)
                if not guard.ok:
                    tick.skipped.append({"symbol": sym, "side": side, "quantity": round(qty, 4),
                                         "code": guard.code, "reason": guard.reason})
                    appstate.log("guardrail_block", "WARN",
                                 f"{sym} {side} {qty:.4f} 被护栏拒绝: {guard.reason}", detail=guard.code)
                    continue
                if guard.adjusted_qty:
                    qty = guard.adjusted_qty

                if dry_run:
                    tick.actions.append({"type": "DRY_RUN", "symbol": sym, "side": side,
                                         "quantity": round(qty, 4), "lot": lot,
                                         "target_notional": round(target_notional, 2)})
                    continue

                t_order = time.perf_counter()
                res = await run_in_threadpool(broker.place_order, sym, side, qty, "MKT")
                order_ms = (time.perf_counter() - t_order) * 1000.0
                lat.get_latency().record(lat.ORDER_ROUNDTRIP, order_ms)
                tick.actions.append({
                    "type": "ORDER", "symbol": sym, "side": side, "quantity": round(qty, 4),
                    "lot": lot, "ok": res.ok, "status": res.status, "order_id": res.order_id,
                    "avg_price": res.avg_price, "message": res.message,
                    "latency_ms": getattr(res, "latency_ms", 0.0) or round(order_ms, 2),
                })
                appstate.log(
                    "engine_order", "INFO" if res.ok else "WARN",
                    f"引擎下单 {sym} {side} {qty:.4f} → {res.status}", detail=res.message,
                )
                if res.ok:
                    self._persist_order(sym, side, qty, res, px, broker=broker)
                    # P2-11：优先用券商回填的**实际成交量**推进持仓与止损规模。
                    # 旧实现一律用请求量 qty —— 未成交/部分成交时，敞口护栏与
                    # StopTracker 都按「未成交的单」计算，规模失真。
                    filled = float(getattr(res, "filled_qty", 0.0) or 0.0)
                    eff_qty = filled if filled > 0 else qty   # 券商未回填时按请求量保守估计
                    pos_after = cur_qty + (eff_qty if side == "BUY" else -eff_qty)
                    # P1-6：同一 tick 内回写风控上下文 —— 后续标的的护栏判定必须看到
                    # 本笔订单之后的敞口。旧实现 ctx 从不更新，10 只标的各 20% 目标
                    # 会全部通过检查，实际建出 200% 敞口。
                    signed_qty = qty if side == "BUY" else -qty
                    prev_mv = float(ctx.open_positions.get(sym, 0.0))
                    px_base = px
                    if sym.upper().endswith(".HK"):
                        try:
                            from ..markets import fx

                            px_base = fx.to_base(px, "HKD", "USD")
                        except Exception:  # noqa: BLE001 —— 折算失败按原值（宁高估不低估）
                            px_base = px
                    new_mv = prev_mv + signed_qty * px_base
                    ctx.open_positions[sym] = new_mv
                    ctx.gross_exposure = max(ctx.gross_exposure + abs(new_mv) - abs(prev_mv), 0.0)
                    mk = "HK" if sym.upper().endswith(".HK") else "US"
                    ctx.market_exposure[mk] = max(
                        ctx.market_exposure.get(mk, 0.0) + abs(new_mv) - abs(prev_mv), 0.0
                    )
                    ctx.orders_today += 1
                    ctx.orders_last_minute += 1
                    if abs(pos_after) < 1e-9:
                        # 已清仓 → 撤掉保护性委托，并重置止损状态
                        await run_in_threadpool(self._cancel_protective, broker, sym)
                        if sym in self.trackers:
                            self.trackers[sym].s.reset()
                    elif cur_qty == 0 or (pos_after > 0) != (cur_qty > 0):
                        # 新开仓（含反手）→ 建立止损跟踪 + 实盘挂保护性委托
                        tr = StopTracker(self.stop_cfg, sym)
                        # P1-1：传策略 bar 序号（_bar_seq），不是执行 tick 数
                        tr.open(1 if pos_after > 0 else -1, res.avg_price or px, self._bar_seq,
                                self._atr_for(sym) or None)
                        self.trackers[sym] = tr
                        await run_in_threadpool(
                            self._place_protective, broker, sym, abs(pos_after), side, res.avg_price or px
                        )
            if not dry_run:
                await run_in_threadpool(self._snapshot_positions, broker)
        except Exception as exc:  # noqa: BLE001
            tick.errors.append(f"{type(exc).__name__}: {exc}")
            self.last_error = tick.errors[-1]
        finally:
            tick.exec_ms = round((time.perf_counter() - t_exec) * 1000.0, 2)
            self.exec_loop_ms.append(tick.exec_ms)
            lat.get_latency().record(lat.ENGINE_EXEC, tick.exec_ms)
            self.exec_count += 1
            self.tick_count += 1
            self.last_tick = ts
            self.last_tick_detail = tick
            self._log_exec_decision(tick, dry_run)
        return tick

    def _log_exec_decision(self, tick: EngineTick, dry_run: bool) -> None:
        """把本 tick 的每个决策落 decision_logs（可回溯；绝不抛异常影响交易）。"""
        try:
            from ..decisions import log_decision

            ctx = {
                "equity": tick.account_equity,
                "quote_source": tick.quote_source,
                "signal_age_sec": tick.signal_age_sec,
                "signal_recomputed": tick.signal_recomputed,
                "target_weights": tick.target_weights,
                "exec_ms": tick.exec_ms,
                "errors": tick.errors,
            }
            # 每笔实际下单单独一条（含订单号）
            for a in tick.actions:
                if a.get("type") == "ORDER":
                    log_decision(
                        actor=f"engine:{self.engine_run_id}",
                        action=a.get("side", "?"),
                        decision=f"{a.get('side')} {a.get('quantity')} {a.get('symbol')} → {a.get('status')}",
                        reasoning=(
                            f"目标权重 {tick.target_weights.get(a.get('symbol'), 0):.4f}；"
                            f"行情源 {tick.quote_source}；信号年龄 {tick.signal_age_sec}s；"
                            f"每手 {a.get('lot')} 股"
                        ),
                        symbol=a.get("symbol", ""),
                        context={**ctx, "action": a},
                        engine_run_id=self.engine_run_id,
                    )
                elif a.get("type") == "DRY_RUN":
                    log_decision(
                        actor=f"engine:{self.engine_run_id}",
                        action="DRY_RUN",
                        decision=f"（dry-run）{a.get('side')} {a.get('quantity')} {a.get('symbol')}",
                        symbol=a.get("symbol", ""),
                        context={**ctx, "action": a},
                        engine_run_id=self.engine_run_id,
                    )
            # 止损动作
            for a in tick.actions:
                if a.get("type") == "STOP":
                    log_decision(
                        actor=f"engine:{self.engine_run_id}",
                        action="STOP",
                        decision=str(a),
                        symbol=a.get("symbol", ""),
                        context=ctx,
                        engine_run_id=self.engine_run_id,
                    )
            # 被跳过的决策批量记一条（SKIP 原因是可回溯性的关键）
            if tick.skipped:
                log_decision(
                    actor=f"engine:{self.engine_run_id}",
                    action="SKIP",
                    decision="；".join(
                        f"{s.get('symbol')} {s.get('side')} {s.get('code')}" for s in tick.skipped[:10]
                    ),
                    reasoning="；".join(
                        f"[{s.get('code')}] {s.get('reason', '')[:120]}" for s in tick.skipped[:10]
                    ),
                    context={**ctx, "skipped": tick.skipped[:20]},
                    engine_run_id=self.engine_run_id,
                )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def _persist_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        res: Any,
        ref_px: float,
        order_type: str = "MKT",
        reason: str = "",
        broker: Broker | None = None,
    ) -> None:
        """落库订单与成交。

        关键：**不使用请求股数/参考价冒充成交**。IBKR 下单是异步的，返回时
        往往还是 Submitted 且 filled_qty=0；写成"已成交 qty 股 @ 参考价"会让
        用户在界面上看到与券商完全不符的成交价。

        状态取值优先级：券商最新快照 > 下单返回 > 兜底 Submitted。
        """
        from ..database import session_scope
        from ..models import Fill, Order as OrderRow

        oid = str(getattr(res, "order_id", "") or "")
        snap: dict[str, Any] = {}
        if broker is not None and oid:
            try:
                snap = broker.order_status_snapshot(oid) or {}
            except Exception:  # noqa: BLE001
                snap = {}

        filled = float(snap.get("filled", 0.0) or 0.0) or float(getattr(res, "filled_qty", 0.0) or 0.0)
        avg_px = float(snap.get("avg_price", 0.0) or 0.0) or float(getattr(res, "avg_price", 0.0) or 0.0)
        commission = float(getattr(res, "commission", 0.0) or 0.0)
        status = str(snap.get("status") or getattr(res, "status", "") or "SUBMITTED")
        # 已确认成交但券商未回价时，用参考价兜底估值（仅影响展示，不改变成交事实）
        est_price = avg_px or (float(ref_px) if filled > 0 else 0.0)

        with session_scope() as s:
            row = OrderRow(
                client_order_id=f"ENG-{uuid.uuid4().hex[:12].upper()}",
                broker_order_id=oid,
                mode=self.mode,
                broker=self._broker_name,
                symbol=symbol, side=side, quantity=qty, order_type=order_type,
                status=status,
                filled_qty=filled,
                avg_fill_price=est_price,
                commission=commission,
                strategy_id=self.strategy_id,
                reason=reason or f"实时引擎 · {self.strategy_name}",
            )
            s.add(row)
            s.flush()
            if filled > 0 and est_price > 0:
                s.add(Fill(order_id=row.id, quantity=filled, price=est_price, commission=commission))

    # ------------------------------------------------------------------
    def _snapshot_positions(self, broker: Broker) -> None:
        """把当前持仓快照落库，供跨重启对账与历史展示。"""
        from sqlalchemy import select

        from ..database import session_scope
        from ..models import PositionSnapshot

        try:
            plist = broker.positions()
        except Exception:  # noqa: BLE001
            return
        try:
            with session_scope() as s:
                for p in plist:
                    row = s.execute(
                        select(PositionSnapshot).where(
                            PositionSnapshot.mode == self.mode,
                            PositionSnapshot.symbol == p.symbol,
                        )
                    ).scalar_one_or_none()
                    if abs(p.quantity) < 1e-9:
                        if row is not None:
                            s.delete(row)
                        continue
                    if row is None:
                        row = PositionSnapshot(mode=self.mode, symbol=p.symbol)
                        s.add(row)
                    row.quantity = p.quantity
                    row.avg_cost = p.avg_cost
                    row.last_price = p.last_price
                    row.strategy_id = self.strategy_id
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    async def _loop(self) -> None:
        """执行主循环。

        与旧实现的三个关键差别：
          1. **绝对截止点**：用 `loop.time()` 记录下次信号/下次执行的绝对时刻，
             而不是「执行完再 sleep(interval)」。后者会把每轮执行耗时累加进周期，
             1s 配置实际跑成 1.5s+；前者不会累积漂移。
          2. **事件驱动**：`exec_mode=event` 时等待「新行情推送」或「兜底定时器」，
             先到者先唤醒。有新 tick 就立刻评估，没有就按 exec_interval 兜底重评
             （用于止损检查、护栏倒计时、账户变化等非行情触发的情形）。
          3. **信号层与执行层分开计时**：重活（拉历史+跑策略）只在信号周期内跑一次。
        """
        self.running = True
        self._attach_hub()
        loop = asyncio.get_running_loop()
        self._wake_loop = loop
        if self._wake_event is None:
            self._wake_event = asyncio.Event()
        self._next_signal_at = loop.time()          # 启动即先算一次信号
        appstate.log(
            "engine_start", "INFO",
            f"引擎启动 #{self.engine_run_id} 策略={self.strategy_name} 模式={self.mode}"
            f" · 执行={self.exec_mode} 执行周期={self.exec_interval_sec:g}s"
            f" 信号周期={self.interval_sec:g}s",
        )
        try:
            while self.running:
                try:
                    now = loop.time()
                    # ---- 信号层 ----
                    if now >= self._next_signal_at:
                        await self._refresh_signals()
                        # 截止点基于「本轮信号完成时刻」推进，避免信号耗时把节奏拖长
                        self._next_signal_at = loop.time() + self.interval_sec

                    # ---- 执行层 ----
                    tick = await self._execute()
                    self._update_run_row("RUNNING", msg="")
                    if tick.errors and "熔断" in tick.errors[0]:
                        continue

                except asyncio.CancelledError:
                    break
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self._update_run_row("ERROR", msg=self.last_error)
                    appstate.log("engine_error", "CRITICAL", f"引擎异常: {self.last_error}")

                # ---- 等待：新行情 or 下次信号 or 执行兜底 ----
                now = loop.time()
                deadline = min(self._next_signal_at, now + self.exec_interval_sec)
                timeout = max(0.0, deadline - loop.time())
                if self.exec_mode != "event":
                    await asyncio.sleep(timeout)
                    self.timer_wakeups += 1
                    continue
                ev = self._wake_event
                if ev is None:
                    await asyncio.sleep(timeout)
                    continue
                ev.clear()
                # 清掉订阅积压，避免「有推送但事件已被消费」造成的空转
                try:
                    if self._sub is not None:
                        self._sub.discard()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await asyncio.wait_for(ev.wait(), timeout=timeout)
                    self.tick_wakeups += 1
                except asyncio.TimeoutError:
                    self.timer_wakeups += 1
        finally:
            self._detach_hub()
            self.running = False
            # P1-4：停止前撤销交易所侧保护性委托，避免残留单在无持仓时反向开仓。
            # shield 保证撤单不被取消信号打断；失败绝不影响停止流程。
            try:
                await asyncio.shield(run_in_threadpool(self._cancel_all_protective))
            except BaseException:  # noqa: BLE001 —— 含 CancelledError：停止流程不得被阻断
                pass
            self._update_run_row("STOPPED", msg="已停止")
            appstate.log("engine_stop", "INFO", f"引擎停止 #{self.engine_run_id}")

    def runtime_stats(self) -> dict[str, Any]:
        """运行时可观测性（前端状态面板 / 延迟面板用）。"""
        xs = sorted(self.exec_loop_ms)
        p50 = xs[len(xs) // 2] if xs else 0.0
        p95 = xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else 0.0
        hub_mode = "off"
        if self._hub is not None and self.symbols:
            modes = {self._hub.mode_of(s) for s in self.symbols}
            hub_mode = "stream" if modes == {"stream"} else ("snapshot" if "snapshot" in modes else "mixed")
        return {
            "run_id": self.engine_run_id,
            "strategy": self.strategy_name,
            "mode": self.mode,
            "symbols": list(self.symbols),
            "exec_mode": self.exec_mode,
            "exec_interval_sec": self.exec_interval_sec,
            "signal_interval_sec": self.interval_sec,
            "signal_age_sec": None if self._signal_age_sec() == float("inf")
                              else round(self._signal_age_sec(), 1),
            "signal_duration_ms": round(self._signal_duration_ms, 1),
            "signal_error": self.last_signal_error,
            "exec_count": self.exec_count,
            "tick_wakeups": self.tick_wakeups,
            "timer_wakeups": self.timer_wakeups,
            "exec_ms": {"p50": round(p50, 2), "p95": round(p95, 2),
                        "max": round(max(xs), 2) if xs else 0.0},
            "quote_source": self.last_quotes_source,
            "market_data": hub_mode,
            "targets": dict(self.last_targets),
        }

    def _update_run_row(self, status: str, msg: str = "") -> None:
        from ..database import session_scope
        from ..models import EngineRun

        try:
            with session_scope() as s:
                row = s.get(EngineRun, self.engine_run_id)
                if row:
                    row.status = status
                    row.tick_count = self.tick_count
                    row.last_tick = dt.datetime.now(dt.timezone.utc)
                    if msg:
                        row.message = msg
                    if status in ("STOPPED", "ERROR"):
                        row.stopped_at = dt.datetime.now(dt.timezone.utc)
        except Exception:  # noqa: BLE001
            pass

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        # P1-4：**先**撤保护性委托（此刻任务尚未取消，await 可正常完成），再停循环。
        # 顺序很关键：若先 cancel，_loop 的 finally 里再 await 会立刻抛 CancelledError，
        # 撤单就做不成了 —— 而残留的 GTC 止损单在无持仓时会反向开仓。
        try:
            await run_in_threadpool(self._cancel_all_protective)
        except Exception:  # noqa: BLE001
            pass
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


@dataclass
class BacktestSpecLite:
    """仅用于复用 build_strategy 的轻量载体。"""
    strategy_key: str
    symbols: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    rule: dict[str, Any] | None = None
    code: str = ""
