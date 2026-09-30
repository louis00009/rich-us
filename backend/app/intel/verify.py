"""intel 建议验证闭环（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

到期对账（三段式：只读查清单 → 无锁取报价 → 短事务写回）、SPY 超额收益判定、
Brier + 置信度分桶校准。window_days_for 放本文件（文档配方在 report.py，
但 verify 与 report 互用会成环）。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from ..database import session_scope
from .common import IntelAnalysis, IntelRun, log


def _run_row(r: IntelRun) -> dict[str, Any]:
    return {
        "id": r.id, "status": r.status, "interval_minutes": r.interval_minutes,
        "auto_analyze": bool(r.auto_analyze), "started_at": r.started_at.isoformat(),
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "tick_count": r.tick_count, "last_tick_at": r.last_tick_at.isoformat() if r.last_tick_at else None,
        "events_found": r.events_found, "analyses_done": r.analyses_done,
        "agents_seen": r.agents_seen, "note": r.note, "report_path": r.report_path,
    }



_VERIFY_TOLERANCE = 1.0   # ±1% 死区：区间收益落在死区视为"平"，不计命中
_VERIFY_BENCHMARK = "SPY"  # 超额收益基准（买方口径：跑赢大盘才算看对）
_HOLD_TOLERANCE = 3.0     # hold 验证：窗口内标的相对基准横在 ±3% 内 → 观望正确

# 验证窗口按建议的 horizon 分档：intraday 建议用 7 天对账毫无意义
VERIFY_WINDOW_DAYS = {"intraday": 2, "swing": 7, "position": 30}


def window_days_for(horizon: str | None) -> int:
    """horizon → 对账窗口（自然日）。未知值回落 swing/7 天。"""
    return VERIFY_WINDOW_DAYS.get((horizon or "swing").strip().lower(), 7)



def _hold_hit(ret: float) -> bool:
    """hold 判定（纯函数）：窗口收益相对基准横在 ±3% 内 → 「观望」正确。"""
    return abs(ret) <= _HOLD_TOLERANCE


def _hit_for(recommendation: str, ret: float) -> bool | None:
    """方向对错判定：看多类涨才算对，看空类跌才算对；死区内为平(None)。

    v2：传入的是**超额收益**（标的收益 − SPY 同期收益）——牛市里涨 2% 而大盘
    涨 3% 不算看对。标的本身是基准（SPY 对 SPY）时超额恒为 0，调用方回退用
    绝对收益判定。
    """
    if abs(ret) <= _VERIFY_TOLERANCE:
        return None
    bullish = recommendation in ("strong_buy", "buy")
    return (ret > 0) if bullish else (ret < 0)


def _close_on_or_before(df: "pd.DataFrame", day: dt.date) -> tuple[dt.date, float] | None:
    """序列里 ≤ day 的最后一根 bar 的 (日期, 收盘)。空/越界返回 None。"""
    import pandas as pd

    if df is None or df.empty:
        return None
    try:
        idx = df.index[df.index.normalize() <= pd.Timestamp(day)]
        if len(idx) == 0:
            return None
        d = idx[-1].normalize()
        px = float(df["close"].loc[d])
        if not px > 0:
            return None
        return d.date(), px
    except Exception:  # noqa: BLE001
        return None


def verify_due_analyses(limit: int = 8) -> int:
    """验证所有「满各自 horizon 窗口未对账」的建议，返回本次验证条数。

    v2（对账口径升级）：
      · 窗口按 horizon 分档：intraday→2 天 / swing→7 天 / position→30 天；
      · 定价精确化：不再用「调度线程跑到时的现价」，而是取历史日线里
        **基线日收盘**（≤分析日）与**目标日收盘**（≤分析日+窗口）——
        无论对账晚跑几天，结果都可复现、可审计；
      · 命中判定改用**相对 SPY 的超额收益**：牛市里跑输大盘的「看多」不算对。
        SPY 自身的建议回退用绝对收益（对自身求超额恒为 0，无意义）。
    三段式不变：① 事务内只读查出到期清单 → ② 事务外取历史序列（网络）→
    ③ 新事务写回。绝不在 SQLite 写事务内做网络调用。
    """
    from ..data_provider import fetch_history

    now = dt.datetime.now(dt.timezone.utc)

    def _aware(x: dt.datetime) -> dt.datetime:
        # SQLite 存 naive UTC——统一补 tz 再比较（naive/aware 混比会 TypeError）
        return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)

    # ① 只读：到期清单（按各自 horizon 窗口判定），立刻关事务
    # hold 也参与验证：窗口内相对基准横在 ±3% 内 = 观望正确（不再是永远不算错的逃逸口）
    with session_scope() as db:
        cand = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.outcome_checked_at.is_(None))
            .filter(IntelAnalysis.created_at <= now - dt.timedelta(days=min(VERIFY_WINDOW_DAYS.values())))
            .order_by(IntelAnalysis.created_at.asc())
            .limit(limit * 4)
            .all()
        )
        tasks = [
            {"id": a.id, "symbol": a.symbol,
             "price_at_analysis": a.price_at_analysis, "recommendation": a.recommendation,
             "created": _aware(a.created_at), "window": window_days_for(a.horizon)}
            for a in cand
            if _aware(a.created_at) <= now - dt.timedelta(days=window_days_for(a.horizon))
        ][:limit]
    if not tasks:
        return 0

    # ② 无锁区：历史日线精确对账（单条失败跳过，不拖垮整批）
    bench_symbol = _VERIFY_BENCHMARK
    bench_cache: dict[str, "pd.DataFrame | None"] = {}

    def _hist(sym: str, start: str, end: str):
        key = f"{sym}|{start}|{end}"
        if key not in bench_cache:
            try:
                df, _src = fetch_history(sym, start=start, end=end, interval="1d")
            except Exception:  # noqa: BLE001
                df = None
            bench_cache[key] = df if (df is not None and not df.empty) else None
        return bench_cache[key]

    results: list[tuple[int, float, float, float | None, bool | None, int]] = []
    for t in tasks:
        created: dt.datetime = t["created"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        win = t["window"]
        base_day = created.date()
        target_day = base_day + dt.timedelta(days=win)
        start = (base_day - dt.timedelta(days=10)).isoformat()
        end = (min(target_day, now.date()) + dt.timedelta(days=3)).isoformat()

        sym_df = _hist(t["symbol"], start, end)
        base_bar = _close_on_or_before(sym_df, base_day)
        # 基线价优先用历史收盘（可复现）；历史不可用退回分析时现价
        if base_bar is not None:
            baseline_px = base_bar[1]
            baseline_date = base_bar[0]
        elif t["price_at_analysis"] and t["price_at_analysis"] > 0:
            baseline_px = float(t["price_at_analysis"])
            baseline_date = base_day
        else:
            continue
        tgt_bar = _close_on_or_before(sym_df, target_day)
        if tgt_bar is None or tgt_bar[0] < baseline_date:
            continue  # 目标日尚无收盘（数据缺口），留待下轮
        outcome_px = tgt_bar[1]

        ret = round((outcome_px / baseline_px - 1) * 100, 2)
        # 基准（SPY）：同一基线日 → 同一目标日
        bench_ret: float | None = None
        if t["symbol"].upper() != bench_symbol:
            bdf = _hist(bench_symbol, start, end)
            b_base = _close_on_or_before(bdf, base_day)
            b_tgt = _close_on_or_before(bdf, tgt_bar[0])
            if b_base and b_tgt and b_base[1] > 0:
                bench_ret = round((b_tgt[1] / b_base[1] - 1) * 100, 2)
        judge = ret if (bench_ret is None or t["symbol"].upper() == bench_symbol) \
            else round(ret - bench_ret, 2)
        if t["recommendation"] == "hold":
            hit: bool | None = _hold_hit(judge)
        else:
            hit = _hit_for(t["recommendation"], judge)
        results.append((t["id"], outcome_px, ret, bench_ret, hit, win))

    # ③ 短事务写回（已被并发验证过的条目跳过）
    pairs = []
    with session_scope() as db:
        for aid, px, ret, bench_ret, hit, win in results:
            a = db.get(IntelAnalysis, aid)
            if not a or a.outcome_checked_at is not None:
                continue
            a.outcome_checked_at = now
            a.outcome_price = round(px, 4)
            a.outcome_return = ret
            a.outcome_benchmark = bench_ret
            a.outcome_hit = hit
            a.outcome_window_days = win
            pairs.append((a.symbol, a.recommendation, ret, bench_ret, hit))
    if pairs:
        log.info("Intel 建议验证 %s 条: %s", len(pairs), pairs)
    return len(pairs)



# 置信度校准分桶（下闭上开，最后桶闭区间）
_CAL_BUCKETS: list[tuple[str, float, float]] = [
    ("0-50", 0, 50), ("50-65", 50, 65), ("65-80", 65, 80), ("80+", 80, 100.01),
]


def _calibrate(pairs: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    """置信度分桶校准（纯函数）：每桶 n / 命中数 / 实际胜率 / 平均置信度。

    校准良好的引擎应满足：桶内「平均置信度 ≈ 实际胜率」。
    """
    out: list[dict[str, Any]] = []
    for label, lo, hi in _CAL_BUCKETS:
        seg = [(c, h) for c, h in pairs if lo <= c < hi]
        if not seg:
            continue
        n = len(seg)
        hits = sum(1 for _, h in seg if h)
        out.append({
            "bucket": label,
            "n": n,
            "hits": hits,
            "hit_rate": round(hits / n * 100, 1),
            "avg_confidence": round(sum(c for c, _ in seg) / n, 1),
        })
    return out


def _brier(pairs: list[tuple[float, bool]]) -> float | None:
    """Brier 分数（纯函数）：mean((conf/100 − hit)²)，0 完美 / 0.25 瞎猜，越小越好。"""
    if not pairs:
        return None
    return round(sum(((c / 100.0) - (1.0 if h else 0.0)) ** 2 for c, h in pairs) / len(pairs), 4)


def verify_stats() -> dict[str, Any]:
    """按 Agent 聚合验证结果：胜率、平均收益/超额收益、平均置信度、Brier、校准分桶。"""
    with session_scope() as db:
        rows = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.outcome_checked_at.is_(None) == False)  # noqa: E712
            .all()
        )
        pending = (
            db.query(IntelAnalysis).filter(IntelAnalysis.outcome_checked_at.is_(None))
            .filter(
                IntelAnalysis.created_at
                <= dt.datetime.now(dt.timezone.utc)
                - dt.timedelta(days=min(VERIFY_WINDOW_DAYS.values()))
            )
            .count()
        )
        total = db.query(IntelAnalysis).count()
    by_agent: dict[str, dict[str, Any]] = {}
    for a in rows:
        if a.outcome_hit is None:
            continue  # 平局不计入胜负（hold 现在也验证：横在 ±3% 内算对，False 算错）
        d = by_agent.setdefault(a.agent or "unknown", {
            "n": 0, "hits": 0, "rets": [], "excess": [], "confs": [], "pairs": []})
        d["n"] += 1
        d["hits"] += 1 if a.outcome_hit else 0
        d["rets"].append(a.outcome_return or 0.0)
        if a.outcome_benchmark is not None:
            d["excess"].append(round((a.outcome_return or 0.0) - a.outcome_benchmark, 2))
        d["confs"].append(a.confidence)
        d["pairs"].append((a.confidence, bool(a.outcome_hit)))
    agents = []
    for agent, d in sorted(by_agent.items(), key=lambda kv: -kv[1]["n"]):
        agents.append({
            "agent": agent,
            "n": d["n"],
            "hits": d["hits"],
            "hit_rate": round(d["hits"] / d["n"] * 100, 1) if d["n"] else None,
            "avg_return": round(sum(d["rets"]) / len(d["rets"]), 2) if d["rets"] else None,
            "avg_excess_return": round(sum(d["excess"]) / len(d["excess"]), 2) if d["excess"] else None,
            "avg_confidence": round(sum(d["confs"]) / len(d["confs"]), 1) if d["confs"] else None,
            "brier": _brier(d["pairs"]),
            "calibration": _calibrate(d["pairs"]),
        })
    all_rets = [(a.outcome_return or 0.0) for a in rows if a.outcome_hit is not None]
    all_pairs = [(a.confidence, bool(a.outcome_hit)) for a in rows if a.outcome_hit is not None]
    all_excess = [
        round((a.outcome_return or 0.0) - a.outcome_benchmark, 2)
        for a in rows if a.outcome_hit is not None and a.outcome_benchmark is not None
    ]
    return {
        "verified_total": len(rows),
        "pending": pending,
        "analyses_total": total,
        "agents": agents,
        "global_hit_rate": (
            round(sum(1 for a in rows if a.outcome_hit) / len(all_rets) * 100, 1) if all_rets else None
        ),
        "global_avg_excess_return": round(sum(all_excess) / len(all_excess), 2) if all_excess else None,
        "global_brier": _brier(all_pairs),
        "global_calibration": _calibrate(all_pairs),
        "tolerance_pct": _VERIFY_TOLERANCE,
        "window_days": 7,  # 兼容旧字段；实际窗口按 horizon 分档见 window_days_by_horizon
        "window_days_by_horizon": VERIFY_WINDOW_DAYS,
        "benchmark": _VERIFY_BENCHMARK,
    }

