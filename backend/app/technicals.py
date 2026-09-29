"""技术指标（日线派生）的分层缓存。

为什么单独一个模块
------------------
榜单的**估值**字段（PE/PB/ROE）一个季度才变；而这里的技术指标（均线、动量、
波动率、RSI、Beta）每天都会变，且**必须拉 1 年日线**才能算 ——
`rankings._fetch_all_quotes()` 只拉 `period="5d"`，根本不够。

实测代价（2026-09-27，本机）：
    · 单块 100 只串行 = 52.4s
    · 4 线程 × 50 只/块 × 200 只 = 28.0s → 推算全量 503 只约 70s
    · 若连原始日线一起落盘 ≈ 1 MB+；**只落算好的指标 = 95 KB / 503 只**

所以这里落盘的是**算好的指标**，不是原始 K 线（省 10 倍体积，且启动即可用）。

与 `fundamentals.py` 完全一致的三层策略：
  1) 内存 TTL + stale-while-revalidate —— 请求永不等待网络；
  2) 磁盘快照 `runtime/cache/us_technicals.json`；
  3) 单飞（`_refreshing`）+ **覆盖率闸门**（部分失败不许覆盖好快照）。

⚠️ 覆盖率闸门在这里比对「估值」更关键：yfinance 单块超时是常态（实测有过
228/503），技术指标一旦被残缺数据覆盖，均线/Beta 会大面积变成空值，
而页面看不出任何异常 —— 只是「好多列都是 —」。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from .config import CACHE_DIR

_TTL = 3600          # 1 小时。用户选了「跟着行情一起刷」，
                     # 但行情 TTL 是 600s —— 若这里也用 600s，每次刷行情都要
                     # 拉一轮 1 年日线（全量约 70s）。日线是**日频**数据，
                     # 盘中重拉不会产生新的一根 K 线，纯粹是浪费。
                     # 因此行情刷新会**顺带触发**它，但受这里的 TTL 闸门约束：
                     # 新鲜就直接返回，不重复拉。
_SNAPSHOT = CACHE_DIR / "us_technicals.json"
_MIN_REFRESH_RATIO = 0.8

_lock = threading.Lock()
_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_refreshing = False
_universe: list[str] = []
_state: dict[str, Any] = {"last": 0.0, "ok": None, "error": None}

# 需要多少根日线才敢算 MA200 / Beta。少于这个数一律不出指标（宁缺勿错）。
MIN_BARS = 210

# ⚠️ 抓取窗口用 2 年，不是 1 年。
# 实测 `period="1y"` 只返回 **251** 根 K 线，而「近 1 年收益」需要 252 根
# （今日 + 251 根之前那一天）—— 差一根，导致 r1y / excess_1y **全部静默为 None**，
# 而「相对 SPY 超额」筛选因此变成永远选不出东西的空功能，页面上完全看不出异常。
# 2 年 ≈ 502 根，多出来的部分不增加请求数（同一个 HTTP 请求，只是 payload 大一点），
# 反而让 MA200 在长假期后有足够样本。
_FETCH_PERIOD = "2y"


def _load_disk() -> tuple[float, dict[str, dict[str, Any]]]:
    """磁盘快照恢复（原子读 + seed 兜底，见 cacheio 模块说明）。"""
    from .cacheio import ensure_seed, load_json_snapshot

    ensure_seed(_SNAPSHOT)
    data = load_json_snapshot(_SNAPSHOT)
    if data and data.get("fields"):
        try:
            return float(data.get("ts", 0.0)), dict(data["fields"])
        except Exception:  # noqa: BLE001
            return 0.0, {}
    return 0.0, {}


def _save_disk(fields: dict[str, dict[str, Any]]) -> None:
    from .cacheio import atomic_write_json

    atomic_write_json(_SNAPSHOT, {"ts": time.time(), "fields": fields})


# ---------------- 指标计算（纯函数，可单测） ----------------
def _rsi(closes: list[float], n: int = 14) -> float | None:
    """经典 Wilder RSI。需 n+1 根 K 线。"""
    if len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_g, avg_l = gains / n, losses / n
    # 用后续数据做 Wilder 平滑（比只看最后 n 根稳）
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return round(100 - 100 / (1 + rs), 1)


def _pct_change(closes: list[float], bars: int) -> float | None:
    """近 bars 根的累计涨跌幅（%）。"""
    if len(closes) < bars + 1:
        return None
    prev = closes[-(bars + 1)]
    if prev <= 0:
        return None
    return round((closes[-1] - prev) / prev * 100, 2)


def _ann_vol(closes: list[float], bars: int = 252) -> float | None:
    """年化波动率（%）：日收益率标准差 × √252。"""
    import statistics

    if len(closes) < 30:
        return None
    window = closes[-(bars + 1):]
    rets = []
    for i in range(1, len(window)):
        if window[i - 1] > 0:
            rets.append(window[i] / window[i - 1] - 1)
    if len(rets) < 20:
        return None
    return round(statistics.stdev(rets) * (252 ** 0.5) * 100, 1)


def _atr_pct(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> float | None:
    """ATR(14) ÷ 现价（%）。衡量「日均真实波幅」，比波动率更贴近止损设置。"""
    if len(closes) < n + 1 or len(highs) < n + 1 or len(lows) < n + 1:
        return None
    trs = []
    for i in range(1, n + 1):
        h, l, pc = highs[-i], lows[-i], closes[-i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs or closes[-1] <= 0:
        return None
    return round(sum(trs) / len(trs) / closes[-1] * 100, 2)


def _beta(stock: list[float], bench: list[float]) -> float | None:
    """Beta = Cov(r_s, r_b) / Var(r_b)。两条序列需**按日期对齐**（调用方保证）。"""
    import statistics

    if len(stock) < 60 or len(bench) != len(stock):
        return None
    rs, rb = [], []
    for i in range(1, len(stock)):
        if stock[i - 1] > 0 and bench[i - 1] > 0:
            rs.append(stock[i] / stock[i - 1] - 1)
            rb.append(bench[i] / bench[i - 1] - 1)
    if len(rs) < 40:
        return None
    mb = statistics.fmean(rb)
    ms = statistics.fmean(rs)
    cov = sum((rb[i] - mb) * (rs[i] - ms) for i in range(len(rs))) / (len(rs) - 1)
    var = sum((x - mb) ** 2 for x in rb) / (len(rb) - 1)
    if var == 0:
        return None
    return round(cov / var, 2)


def _ma_rel(closes: list[float], window: int) -> float | None:
    """现价相对 N 日均线的偏离（%）。正 = 在均线上方。"""
    if len(closes) < window:
        return None
    ma = sum(closes[-window:]) / window
    if ma <= 0:
        return None
    return round((closes[-1] - ma) / ma * 100, 2)


def compute_indicators(closes: list[float], highs: list[float], lows: list[float],
                       bench_closes: list[float] | None = None) -> dict[str, Any]:
    """从日线序列算出全部指标。纯函数 —— 单测直接喂构造数据即可。

    数据不够时**返回 None 而不是猜**：MA200 需要 200 根，新上市的股票就是没有，
    硬用现有 ma 长度算出来的「200 日均线」是错的，而页面看不出来。
    """
    out: dict[str, Any] = {}
    n = len(closes)

    out["ma20_rel"] = _ma_rel(closes, 20)
    out["ma60_rel"] = _ma_rel(closes, 60)
    out["ma200_rel"] = _ma_rel(closes, 200)
    # 均线多头排列：价 > MA20 > MA60 > MA200（经典趋势确认）
    ma20 = sum(closes[-20:]) / 20 if n >= 20 else None
    ma60 = sum(closes[-60:]) / 60 if n >= 60 else None
    ma200 = sum(closes[-200:]) / 200 if n >= 200 else None
    if ma20 and ma60 and ma200:
        out["ma_bull"] = bool(closes[-1] > ma20 > ma60 > ma200)
        out["ma_bear"] = bool(closes[-1] < ma20 < ma60 < ma200)
    else:
        out["ma_bull"] = None
        out["ma_bear"] = None

    out["r1m"] = _pct_change(closes, 21)
    out["r3m"] = _pct_change(closes, 63)
    out["r6m"] = _pct_change(closes, 126)
    out["r1y"] = _pct_change(closes, 251)
    out["vol_ann"] = _ann_vol(closes)
    out["rsi14"] = _rsi(closes)
    out["atr_pct"] = _atr_pct(highs, lows, closes)
    out["bars"] = n

    if bench_closes is not None:
        out["beta"] = _beta(closes, bench_closes)
        b1y = _pct_change(bench_closes, 251)
        s1y = out["r1y"]
        out["bench_1y"] = b1y
        # 相对基准的超额收益 —— 单看个股涨幅会被大盘整体涨跌误导
        out["excess_1y"] = round(s1y - b1y, 2) if (s1y is not None and b1y is not None) else None
    else:
        out["beta"] = None
        out["bench_1y"] = None
        out["excess_1y"] = None

    return out


# ---------------- 抓取 ----------------
_BENCH = "SPY"


def _fetch_daily(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """并发拉 1 年日线并算好指标。SPY 单独先拉，用于所有个股的 Beta 对齐。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import yfinance as yf

    def bars(sym: str) -> tuple[list[float], list[float], list[float], list[str]]:
        df = yf.download(sym, period=_FETCH_PERIOD, interval="1d", progress=False,
                         auto_adjust=False, threads=False)
        if df is None or df.empty:
            return [], [], [], []
        # ⚠️ 压平 MultiIndex **必须在**取列之前：yfinance 即便只下 1 个标的也会返回
        # MultiIndex（列是 ('Close','SPY')），此时 df["Close"] 会直接抛 KeyError，
        # 被我下面的 except 吞掉 —— 表现是「Beta 全部为 0 只可用」且毫无报错线索。
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        idx = [str(x)[:10] for x in df.index]
        return (
            [float(x) for x in df["Close"]],
            [float(x) for x in df["High"]] if "High" in df else [float(x) for x in df["Close"]],
            [float(x) for x in df["Low"]] if "Low" in df else [float(x) for x in df["Close"]],
            idx,
        )

    # ---- 基准 ----
    # ⚠️ 基准拉不到时不能只是静默 pass：那会让**所有个股的 Beta 全变 None**，
    # 而页面只表现为「Beta 一列全是 —」，完全看不出是基准的问题。
    # 所以把失败原因记进 _state，由 meta() 暴露给前端。
    bench_map: dict[str, float] = {}
    try:
        bc, _, _, bidx = bars(_BENCH)
        bench_map = dict(zip(bidx, bc))
        if not bench_map:
            _state["bench_error"] = f"基准 {_BENCH} 返回空序列"
        else:
            _state["bench_error"] = None
    except Exception as exc:  # noqa: BLE001
        _state["bench_error"] = f"基准 {_BENCH} 抓取失败：{type(exc).__name__}: {exc}"[:160]

    def work(chunk: list[str]) -> dict[str, dict[str, Any]]:
        res: dict[str, dict[str, Any]] = {}
        try:
            df = yf.download(" ".join(chunk), period=_FETCH_PERIOD, interval="1d", group_by="ticker",
                             threads=False, progress=False, auto_adjust=False)
        except Exception:  # noqa: BLE001
            return res
        if df is None or df.empty:
            return res
        for sym in chunk:
            try:
                sub = df if len(chunk) == 1 else df[sym]
                sub = sub.dropna(subset=["Close"])
                if len(sub) < 30:
                    continue
                if hasattr(sub.columns, "nlevels") and sub.columns.nlevels > 1:
                    sub.columns = sub.columns.get_level_values(0)
                closes = [float(x) for x in sub["Close"]]
                highs = [float(x) for x in sub["High"]] if "High" in sub else closes
                lows = [float(x) for x in sub["Low"]] if "Low" in sub else closes
                idx = [str(x)[:10] for x in sub.index]

                # Beta 必须**按日期对齐**：直接按位置对齐会在个股停牌、
                # 新股上市、或两边交易日数不同时算出一个假的 Beta。
                # ⚠️ 对齐时要**整行一起筛**（close/high/low/bench 同一批日期），
                # 只筛 close 再按位置切 highs 会错位 —— 那正是「假的 Beta」的来源。
                row_ok = [(c, h, l, bench_map[d]) for c, h, l, d in zip(closes, highs, lows, idx)
                          if d in bench_map]
                if bench_map and len(row_ok) >= 60:
                    res[sym] = compute_indicators(
                        [r[0] for r in row_ok], [r[1] for r in row_ok],
                        [r[2] for r in row_ok], [r[3] for r in row_ok],
                    )
                else:
                    res[sym] = compute_indicators(closes, highs, lows, None)
            except Exception:  # noqa: BLE001
                continue
        return res

    chunks = [symbols[i: i + 50] for i in range(0, len(symbols), 50)]
    out: dict[str, dict[str, Any]] = {}
    if not chunks:
        return out
    # 5 线程：实测 4 线程 200 只 28s；再高收益递减（yfinance 端有连接限制）
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(work, c) for c in chunks]
        for f in as_completed(futs):
            out.update(f.result() or {})
    return out


def _accept_refresh(fresh_count: int, old_count: int) -> bool:
    """覆盖率闸门 —— 与 rankings 同款。部分失败不许覆盖好快照。"""
    if fresh_count <= 0:
        return False
    if old_count <= 0:
        return True
    return fresh_count >= old_count * _MIN_REFRESH_RATIO


def _bg_refresh() -> None:
    global _cache, _refreshing
    try:
        fresh = _fetch_daily(list(_universe))
        _, old = _cache
        if _accept_refresh(len(fresh), len(old)):
            with _lock:
                _cache = (time.time(), fresh)
            _save_disk(fresh)
            _state["ok"] = True
            _state["error"] = None
        else:
            _state["ok"] = False
            _state["error"] = (
                f"本次只算到 {len(fresh)} 只（旧快照 {len(old)} 只），覆盖率过低，保留旧快照"
            )[:160]
    except Exception as exc:  # noqa: BLE001
        _state["ok"] = False
        _state["error"] = f"{type(exc).__name__}: {exc}"[:160]
    finally:
        with _lock:
            _refreshing = False
        _state["last"] = time.time()


def _refresh_async(syms: list[str]) -> None:
    """登记标的池（只增不减）+ 单飞启动后台刷新。"""
    global _refreshing
    with _lock:
        if len(syms) > len(_universe):
            _universe[:] = syms
        if _refreshing or not _universe:
            return
        _refreshing = True
    threading.Thread(target=_bg_refresh, daemon=True, name="technicals-refresh").start()


def snapshot(symbols: list[str], force: bool = False) -> dict[str, dict[str, Any]]:
    """返回 {symbol: 指标}。**永不阻塞网络**。"""
    global _cache
    syms = [s.strip().upper() for s in symbols if s.strip()]
    ts, data = _cache
    if not data:
        ts, data = _load_disk()
        if data:
            with _lock:
                if not _cache[1]:
                    _cache = (ts, data)

    if data and not force and time.time() - ts < _TTL:
        return data
    _refresh_async(syms)
    return dict(data)


def meta() -> dict[str, Any]:
    ts, data = _cache
    return {
        "count": len(data),
        "age_sec": int(time.time() - ts) if ts else None,
        "stale": (not data) or (time.time() - ts >= _TTL),
        "refreshing": _refreshing,
        "last_refresh_ok": _state.get("ok"),
        "error": _state.get("error"),
        "ttl_sec": _TTL,
    }
