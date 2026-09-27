"""
事件驱动回测引擎
==================
核心保证：
  1. 无未来函数 —— 第 t 根 bar 收盘生成的信号，只在第 t+1 根 bar 开盘成交。
  2. 真实成本  —— 双边佣金 + 滑点，滑点方向永远对己不利。
  3. 止损一致  —— 使用与实盘完全相同的 StopTracker（移动止损/保本/R 倍止盈/时间止损）。
  4. 逐 bar 撮合 —— 止损以 bar 内 high/low 判定，而非仅看收盘价，避免高估收益。
  5. FIFO 配对  —— 多笔加仓/减仓按先进先出配对，盈亏归属清晰可审计。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..data_provider import fetch_history, fetch_many
from ..risk.sizing import cap_targets, weights_to_notionals
from ..risk.stops import StopConfig, StopTracker
from ..strategies import SignalContext, create_strategy
from ..strategies.custom import CodeStrategy, RuleStrategy
from .metrics import compute_metrics, periods_per_year

MIN_TRADE_FRACTION = 0.002   # 小于权益 0.2% 的调仓忽略，抑制无意义换手


@dataclass
class BacktestSpec:
    strategy_key: str
    symbols: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    rule: dict[str, Any] | None = None
    code: str = ""
    start: str = "2019-01-01"
    end: str | None = None
    interval: str = "1d"
    initial_capital: float = 100_000.0
    commission_bps: float = 1.0
    slippage_bps: float = 2.0
    fee_model: str = "bps"           # bps（统一万分比）| market（markets/fees.py 分项真实费用：US SEC/TAF、HK 印花税等）
    execution: str = "close"         # close（止损按触发价成交）| intra（跳空穿越止损按开盘价成交 —— 保守口径，T-110）
    benchmark: str = "SPY"
    stop: StopConfig = field(default_factory=StopConfig)
    sizing_method: str = "weight"
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    gross_pct: float = 100.0
    data_source: str = "auto"        # auto | ibkr（需已连接 IBKR）


class TradeBook:
    """FIFO 仓位配对簿：把一串成交合并成「从空仓到空仓」的往返交易。"""

    def __init__(self) -> None:
        self.lots: deque[list[float]] = deque()
        self.cur: dict[str, Any] | None = None

    @property
    def flat(self) -> bool:
        return not self.lots

    def add_entry(self, symbol: str, qty: float, price: float, bar: int, ts: str) -> None:
        if abs(qty) < 1e-12:
            return
        if self.cur is None:
            self.cur = {
                "symbol": symbol, "side": "LONG" if qty > 0 else "SHORT",
                "entry_time": ts, "entry_bar": bar,
                "qty": 0.0, "notional": 0.0, "realized": 0.0,
            }
        self.cur["qty"] += abs(qty)
        self.cur["notional"] += abs(qty) * price
        self.lots.append([abs(qty), price])

    def reduce(self, qty: float, price: float) -> float:
        """qty 为正数，表示按当前方向平掉的数量。返回本次实现盈亏。"""
        if self.cur is None:
            return 0.0
        sign = 1 if self.cur["side"] == "LONG" else -1
        remaining, realized = abs(qty), 0.0
        while remaining > 1e-12 and self.lots:
            lot = self.lots[0]
            take = min(lot[0], remaining)
            realized += (price - lot[1]) * take * sign
            lot[0] -= take
            remaining -= take
            if lot[0] <= 1e-12:
                self.lots.popleft()
        self.cur["realized"] += realized
        return realized

    def finalize(self, exit_price: float, exit_bar: int, exit_time: str, reason: str) -> dict[str, Any] | None:
        if self.cur is None:
            return None
        t = self.cur
        avg_entry = t["notional"] / max(t["qty"], 1e-12)
        rec = {
            "symbol": t["symbol"], "side": t["side"],
            "entry_time": t["entry_time"], "exit_time": exit_time,
            "entry_price": round(avg_entry, 4), "exit_price": round(exit_price, 4),
            "qty": round(t["qty"], 4), "pnl": round(t["realized"], 2),
            "return_pct": round(t["realized"] / max(avg_entry * t["qty"], 1e-9), 5),
            "bars_held": exit_bar - t["entry_bar"], "exit_reason": reason,
        }
        self.cur = None
        return rec


def build_strategy(spec: BacktestSpec):
    if spec.strategy_key == "custom_rule":
        return RuleStrategy(rule=spec.rule or {}, **spec.params)
    if spec.strategy_key == "custom_code":
        return CodeStrategy(code=spec.code or "", **spec.params)
    return create_strategy(spec.strategy_key, spec.params)


def _align(data: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    """把多标的行情对齐到统一时间轴（并集 + 前向填充，最多 5 根）。"""
    frames = {s: df for s, df in data.items() if df is not None and len(df) > 0}
    if not frames:
        return {}, pd.DatetimeIndex([])
    idx = next(iter(frames.values())).index
    for df in frames.values():
        idx = idx.union(df.index)
    idx = idx.sort_values()
    return {s: df.reindex(idx).ffill(limit=5) for s, df in frames.items()}, idx


def run_backtest(spec: BacktestSpec) -> dict[str, Any]:
    prefer = None if spec.data_source in ("", "auto") else spec.data_source
    raw_data, sources = fetch_many(spec.symbols, spec.start, spec.end, spec.interval, prefer=prefer)
    if not raw_data:
        return {"ok": False, "error": "未获取到任何行情数据，请检查标的代码或网络连接"}
    if prefer:
        got_ibkr = any(v == prefer for v in sources.values())
        if not got_ibkr:
            # 数据源不可用（未连接/未订阅）→ 已自动降级，需要告知用户
            pass

    bench_df = pd.DataFrame()
    if spec.benchmark:
        bench_df, _ = fetch_history(
            spec.benchmark.strip().upper(), spec.start, spec.end, spec.interval, prefer=prefer
        )

    data, idx = _align(raw_data)
    if len(idx) < 30:
        return {"ok": False, "error": f"对齐后仅有 {len(idx)} 根 bar，不足以回测（建议放宽时间范围或减少标的）"}

    symbols = [s for s in spec.symbols if s in data]
    if not symbols:
        return {"ok": False, "error": "所选标的无有效数据"}

    closes = pd.DataFrame({s: data[s]["close"] for s in symbols})
    opens = pd.DataFrame({s: data[s]["open"] for s in symbols})
    highs = pd.DataFrame({s: data[s]["high"] for s in symbols})
    lows = pd.DataFrame({s: data[s]["low"] for s in symbols})

    bench_close = bench_df["close"].reindex(idx).ffill() if not bench_df.empty else None
    ctx = SignalContext(data={s: data[s] for s in symbols}, symbols=symbols, bench=bench_close, timeframe=spec.interval)

    strategy = build_strategy(spec)
    weights = strategy.run(ctx).reindex(idx).ffill().fillna(0.0)
    weights = weights.reindex(columns=symbols).fillna(0.0)

    from ..strategies.frames import atr as atr_df

    atr_prev = atr_df(highs, lows, closes, spec.stop.atr_period).shift(1)

    # ---------------- 逐 bar 撮合 ----------------
    cash = float(spec.initial_capital)
    pos = {s: 0.0 for s in symbols}
    books = {s: TradeBook() for s in symbols}
    trackers = {s: StopTracker(spec.stop, s) for s in symbols}
    trades: list[dict[str, Any]] = []
    equity_list: list[float] = []
    exposure_list: list[float] = []
    turnover_notional = 0.0

    n = len(idx)
    o_np = opens.to_numpy(dtype=float)
    h_np = highs.to_numpy(dtype=float)
    l_np = lows.to_numpy(dtype=float)
    c_np = closes.to_numpy(dtype=float)
    a_np = atr_prev.to_numpy(dtype=float)
    w_np = weights.to_numpy(dtype=float)
    last_valid_px = {s: 0.0 for s in symbols}   # 停牌/缺价时沿用最近有效收盘价（P2）
    comm_rate = spec.commission_bps / 10_000.0
    slip_rate = spec.slippage_bps / 10_000.0
    use_market_fees = getattr(spec, "fee_model", "bps") == "market"

    def fill(k: int, sym: str, ref_price: float, qty: float) -> float:
        """按参考价 + 不利滑点成交，扣佣金，更新现金与持仓。返回成交价。"""
        nonlocal cash, turnover_notional
        if abs(qty) < 1e-12 or not np.isfinite(ref_price) or ref_price <= 0:
            return ref_price
        px = ref_price * (1 + slip_rate) if qty > 0 else ref_price * (1 - slip_rate)
        notional = abs(qty * px)
        if use_market_fees:
            try:
                from ..markets.fees import total_fee

                fee = total_fee(sym, "BUY" if qty > 0 else "SELL", abs(qty), px)
            except Exception:  # noqa: BLE001
                fee = notional * comm_rate
        else:
            fee = notional * comm_rate
        cash -= qty * px + fee
        turnover_notional += notional
        pos[sym] += qty
        if abs(pos[sym]) < 1e-9:
            pos[sym] = 0.0
        return px

    def atr_at(i: int, k: int) -> float | None:
        v = a_np[i][k]
        return float(v) if np.isfinite(v) else None

    for i in range(n):
        # ============ 1) 开盘按上一根 bar 的信号调仓 ============
        if i >= 1:
            prev_equity = equity_list[-1] if equity_list else spec.initial_capital
            w_prev = pd.Series(w_np[i - 1], index=symbols)

            if spec.sizing_method and spec.sizing_method != "weight":
                px = pd.Series(o_np[i], index=symbols)
                atr_map = {s: atr_at(i, k) for k, s in enumerate(symbols)}
                targets = weights_to_notionals(
                    w_prev, prev_equity, px, spec.sizing_method,
                    max_position_pct=spec.max_position_pct, gross_pct=spec.gross_pct,
                    atr_map=atr_map, risk_per_trade_pct=spec.risk_per_trade_pct,
                    stop_mult=spec.stop.stop_value,
                )
            else:
                # P0-1：weight 模式必须施加两级组合级约束。
                # 旧实现 targets = 逐标的权重 × 权益，只做逐元素 clip 不做 Σ 归一 ——
                # 多标的策略输出逐标的 ±1 权重时跑出 6 倍免费杠杆（实测 +6771% / 夏普 14），
                # 所有历史回测与网格寻优结论整体失真。
                targets = cap_targets(
                    {s: float(w_prev[s]) * prev_equity for s in symbols},
                    prev_equity, spec.max_position_pct, spec.gross_pct,
                )

            for k, sym in enumerate(symbols):
                ref = o_np[i][k]
                if not np.isfinite(ref) or ref <= 0:
                    continue
                delta_notional = targets.get(sym, 0.0) - pos[sym] * ref
                if abs(delta_notional) < prev_equity * MIN_TRADE_FRACTION:
                    continue

                # --- 1a) 先处理减仓 / 平仓（与当前持仓反向的部分）---
                delta_qty = delta_notional / ref
                if pos[sym] != 0 and np.sign(delta_qty) != np.sign(pos[sym]):
                    reduce_qty = np.sign(delta_qty) * min(abs(delta_qty), abs(pos[sym]))
                    px = fill(k, sym, ref, reduce_qty)
                    book = books[sym]
                    book.reduce(abs(reduce_qty), px)
                    if book.flat:
                        rec = book.finalize(px, i, str(idx[i])[:10], "信号离场")
                        if rec:
                            trades.append(rec)
                        trackers[sym].s.reset()
                    delta_qty -= reduce_qty

                # --- 1b) 再处理开仓 / 加仓 ---
                if abs(delta_qty) * ref >= prev_equity * MIN_TRADE_FRACTION:
                    if delta_qty > 0:
                        # P0-1 现金下限：买单不得让现金穿负 —— 回测不能凭空加杠杆。
                        # 0.5% 缓冲覆盖佣金/滑点/港股印花税等费用。
                        est_px = ref * (1 + slip_rate)
                        affordable = max(cash, 0.0) / (est_px * 1.005)
                        if delta_qty > affordable:
                            delta_qty = affordable
                    if abs(delta_qty) * ref >= prev_equity * MIN_TRADE_FRACTION:
                        px = fill(k, sym, ref, delta_qty)
                        book = books[sym]
                        was_flat = book.flat
                        book.add_entry(sym, delta_qty, px, i, str(idx[i])[:10])
                        if was_flat:
                            trackers[sym].open(1 if pos[sym] > 0 else -1, px, i, atr_at(i, k))

        # ============ 2) 止损 / 止盈（同一 bar 内，不含本 bar 新开仓）============
        for k, sym in enumerate(symbols):
            if pos[sym] == 0 or books[sym].flat or books[sym].cur is None:
                continue
            if books[sym].cur["entry_bar"] == i:
                continue
            hp, lp, cp = h_np[i][k], l_np[i][k], c_np[i][k]
            if not np.isfinite(cp):
                continue
            hit, reason, stop_px = trackers[sym].update(
                hp if np.isfinite(hp) else cp,
                lp if np.isfinite(lp) else cp,
                cp, atr_at(i, k), i,
            )
            if not hit:
                continue
            px_ref = stop_px if np.isfinite(stop_px) and stop_px > 0 else cp
            # T-110 intra 撮合：开盘已跳空穿越止损 → 按开盘价成交（保守，不留幻想价）
            if getattr(spec, "execution", "close") == "intra" and np.isfinite(o_np[i][k]) and o_np[i][k] > 0:
                o_bar = float(o_np[i][k])
                if pos[sym] > 0:
                    px_ref = min(px_ref, o_bar)
                elif pos[sym] < 0:
                    px_ref = max(px_ref, o_bar)
            close_qty = abs(pos[sym])
            px = fill(k, sym, px_ref, -pos[sym])       # -pos 在 fill 之前求值，方向正确
            book = books[sym]
            if book.cur is not None:
                book.reduce(close_qty, px)              # FIFO 清空该笔持仓
            rec = book.finalize(px, i, str(idx[i])[:10], reason or "止损")
            if rec:
                trades.append(rec)
            trackers[sym].s.reset()

        # ============ 3) 收盘估值 ============
        mtm = 0.0
        gross = 0.0
        for k, sym in enumerate(symbols):
            cp = c_np[i][k]
            if not np.isfinite(cp):
                op = o_np[i][k]
                # P2：旧实现 NaN 兜底为 0 —— 停牌一根 bar 就把持仓估成 0，
                # 权益断崖毁掉 max_drawdown / calmar。改为沿用最近有效价。
                cp = op if np.isfinite(op) and op > 0 else last_valid_px[sym]
            if cp > 0:
                last_valid_px[sym] = cp
            mtm += pos[sym] * cp
            gross += abs(pos[sym] * cp)
        equity = cash + mtm
        equity_list.append(equity)
        exposure_list.append(gross / equity if equity > 0 else 0.0)

    equity = pd.Series(equity_list, index=idx, dtype=float)
    exposure = pd.Series(exposure_list, index=idx, dtype=float)

    bench_equity = None
    if bench_close is not None:
        b = bench_close.ffill().dropna()
        if len(b) > 2 and b.iloc[0] > 0:
            # 对齐到策略时间轴，避免基准序列短于净值序列导致取数越界
            bench_equity = (b / b.iloc[0] * spec.initial_capital).reindex(idx).ffill()

    years = max((idx[-1] - idx[0]).days / 365.25, 1e-6)
    avg_equity = float(equity.mean()) if len(equity) else spec.initial_capital
    turnover = turnover_notional / (avg_equity * years) if avg_equity > 0 else 0.0

    metrics = compute_metrics(
        equity, trades, spec.initial_capital, bench_equity, exposure, turnover,
        periods_per_year=periods_per_year(spec.interval),
    )

    dd = equity / equity.cummax() - 1.0
    step = max(1, len(idx) // 1500)
    curve = [
        {
            "date": str(idx[j])[:10],
            "equity": round(float(equity.iloc[j]), 2),
            "benchmark": round(float(bench_equity.iloc[j]), 2) if bench_equity is not None else None,
            "drawdown": round(float(dd.iloc[j]), 5),
            "exposure": round(float(exposure.iloc[j]), 4),
        }
        for j in range(0, len(idx), step)
    ]

    monthly: dict[str, float] = {}
    if len(equity) > 2:
        m = equity.resample("ME").last().pct_change().dropna()
        monthly = {str(k)[:7]: round(float(v), 5) for k, v in m.items()}

    data_warning = ""
    used_sources = set(sources.values())
    if spec.data_source not in ("", "auto") and spec.data_source not in used_sources:
        data_warning = (
            f"请求的数据源「{spec.data_source}」不可用，已自动降级为 "
            f"{'、'.join(sorted(used_sources)) or '未知'}。"
            f"请在「系统设置 → 券商连接」确认 IBKR 已连接，或改用「自动」数据源。"
        )

    return {
        "ok": True,
        "metrics": metrics,
        "curve": curve,
        "trades": list(reversed(trades))[:1500],
        "trade_count": len(trades),
        "monthly": monthly,
        "symbols": symbols,
        "data_sources": sources,
        "data_source_used": (next(iter(sources.values())) if len(set(sources.values())) == 1 else "mixed"),
        "data_source_requested": spec.data_source,
        "data_warning": data_warning,
        "strategy_notes": getattr(strategy, "notes", []),
        "bars": len(idx),
        "date_range": [str(idx[0])[:10], str(idx[-1])[:10]],
        "strategy_name": strategy.name,
    }


def grid_optimize(
    spec: BacktestSpec,
    param_grid: dict[str, list[Any]],
    objective: str = "sharpe",
    max_combos: int = 200,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_event: "threading.Event | None" = None,
) -> dict[str, Any]:
    """参数穷举网格搜索，返回按目标函数排序的排行榜。

    progress_cb(done, total)：每完成一组调用一次（供后台任务上报进度）；
    cancel_event：协作式取消 —— 每组之间检查，置位后立即停止并返回已完成部分
    （is_cancelled=True），已评估的结果不浪费。
    """
    import itertools

    keys = [k for k in param_grid if param_grid[k]]
    if not keys:
        return {"ok": False, "error": "参数网格为空"}
    combos: list[tuple] = list(itertools.product(*[param_grid[k] for k in keys]))
    if len(combos) > max_combos:
        rng = np.random.default_rng(42)
        pick = sorted(rng.choice(len(combos), size=max_combos, replace=False).tolist())
        combos = [combos[i] for i in pick]

    results: list[dict[str, Any]] = []
    cancelled = False
    total = len(combos)
    for done, combo in enumerate(combos, 1):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        params = {**spec.params, **dict(zip(keys, combo))}
        s = BacktestSpec(**{**spec.__dict__, "params": params})
        try:
            r = run_backtest(s)
        except Exception as exc:  # noqa: BLE001
            results.append({"params": params, "error": str(exc)[:160]})
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:  # noqa: BLE001
                    pass
            continue
        if not r.get("ok"):
            results.append({"params": params, "error": str(r.get("error", "失败"))[:160]})
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:  # noqa: BLE001
                    pass
            continue
        m = r["metrics"]
        results.append({
            "params": params,
            "sharpe": m["sharpe"], "sortino": m["sortino"], "calmar": m["calmar"],
            "return": m["total_return"], "cagr": m["cagr"], "max_drawdown": m["max_drawdown"],
            "profit_factor": m["profit_factor"], "win_rate": m["win_rate"], "trades": m["trades"],
        })
        if progress_cb:
            try:
                progress_cb(done, total)
            except Exception:  # noqa: BLE001
                pass
    ok = [r for r in results if r.get(objective) is not None]
    ok.sort(key=lambda r: r[objective], reverse=True)
    return {
        "ok": True,
        "is_cancelled": cancelled,
        "objective": objective,
        "evaluated": len(results),
        "failed": len(results) - len(ok),
        "best": ok[0] if ok else None,
        "results": ok[:200],
    }
