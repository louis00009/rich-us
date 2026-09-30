"""美股 Top 500（S&P 500）榜单。

数据结构：
  · 成分股清单：`app/markets/sp500.json`（Wikipedia 快照，503 只，含名称/行业）。
    提供联网刷新（7 天 TTL），失败时永远有快照兜底。
  · 行情：yfinance 批量下载（100 只/批 × 4 线程并发），内存缓存 TTL 10 分钟。
    字段：price / change_pct / volume / amount（成交额）/ name / sector。

性能设计（曾 symptom：榜单首次加载 ~74 秒、每 10 分钟又卡一次）：
  1) stale-while-revalidate —— 缓存过期也**立即返回旧数据**，后台线程去刷新；
     绝不让 HTTP 请求阻塞在网络抓取上。
  2) 磁盘持久化 —— 最近一次行情落盘 `runtime/cache/sp500_quotes.json`，
     重启后秒级可用，不再是冷启动。
  3) 并发抓取 —— 6 个分块用 4 线程同时拉，刷新耗时约为串行的 1/3~1/4。
  4) 启动预热 —— 服务一启动就在后台拉一轮（main.py lifespan）。

估值字段（PE / PB / ROE / 股息率…）来自 `fundamentals.py` 的同源腾讯批量行情，
与中文名/市值共用一次请求。**PE 由「榜单现价 ÷ 缓存 EPS」实时合成**，
保证与页面上的现价、EPS 算术自洽，也避免 PE 随价格漂移而陈旧。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .config import CACHE_DIR
from .quote_cache import QuoteCache, accept_refresh as _accept_refresh

SNAPSHOT_PATH = Path(__file__).resolve().parent / "markets" / "sp500.json"
_QUOTES_SNAPSHOT = CACHE_DIR / "sp500_quotes.json"
# 响应级快照：数据源全部新鲜时把**组装完成的完整行**（行情+估值+技术+评分+信号）
# 落盘。任何数据源未就绪时用它补缺 —— 页面打开永远是完整数据，旧值标注 stale。
_RANK_SNAPSHOT = CACHE_DIR / "rankings_snapshot.json"
_RANK_SNAPSHOT_TTL = 7 * 86400          # 超过 7 天的快照不再用于补全（太旧会误导）
_REFRESH_TTL = 7 * 86400
_QUOTE_TTL = 600
_CHUNK = 100
_WORKERS = 4

_snap_lock = threading.Lock()
_snap_cache: dict[str, Any] | None = None
_snap_loaded_at = 0.0

# 成分股清单刷新（Wikipedia 7 天 TTL）的状态；行情缓存的后台刷新状态已并入 QuoteCache
_refresh_state: dict[str, Any] = {"last": 0.0, "ok": None}

# 全池行情缓存机制（磁盘读写 / 后台单飞刷新 / 覆盖率闸门）已按铁律 9 抽到
# `quote_cache.py`，与 movers.py 共用同一实现；本模块只保留 rankings 特有的
# 解析与编排。
_qc = QuoteCache(
    snapshot_path=_QUOTES_SNAPSHOT,
    ttl=_QUOTE_TTL,
    chunk=_CHUNK,
    workers=_WORKERS,
    thread_name="rankings-refresh",
)

# 快照保存节流：全部数据源新鲜时的每个请求都会通过校验，但落盘 2200+ 只 × 全字段
# 约 5MB，没有必要每次都写 —— 5 分钟内只写一次。
_rank_snap_lock = threading.Lock()
_rank_snap_last = 0.0


# ---------------- 成分股 ----------------
def constituents() -> dict[str, Any]:
    """标的池（S&P 500 + NASDAQ 100 + S&P MidCap 400 + SmallCap 600 + 市值补充 + 精选 ≈ 2240 只）。

    委托 `universe.py` 合并（内部内存缓存）；返回结构保持
    {updated, count, constituents:[{symbol,name,sector,sub_sector}]}，
    下游（行情/估值/技术面/信号）完全无感。
    """
    from .universe import universe

    return universe()


def refresh_constituents(force: bool = False) -> dict[str, Any]:
    """尝试从 Wikipedia 刷新成分股（7 天一次）；失败静默用快照。"""
    if not force and time.time() - _refresh_state["last"] < _REFRESH_TTL:
        return {"refreshed": False, "reason": "ttl"}
    _refresh_state["last"] = time.time()
    try:
        import io

        import pandas as pd
        import requests

        r = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=20,
        )
        r.raise_for_status()
        df = pd.read_html(io.StringIO(r.text))[0]
        rows = []
        for _, x in df.iterrows():
            rows.append({
                "symbol": str(x["Symbol"]).replace(".", "-"),
                "name": str(x["Security"]),
                "sector": str(x["GICS Sector"]),
                "sub_sector": str(x.get("GICS Sub-Industry", "")),
            })
        data = {
            "updated": time.strftime("%Y-%m-%d"),
            "source": "wikipedia List of S&P 500 companies",
            "count": len(rows), "constituents": rows,
        }
        SNAPSHOT_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        global _snap_cache
        with _snap_lock:
            _snap_cache = data
        _refresh_state["ok"] = True
        return {"refreshed": True, "count": len(rows)}
    except Exception as exc:  # noqa: BLE001
        _refresh_state["ok"] = False
        return {"refreshed": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------- 批量行情 ----------------
def _load_disk() -> tuple[float, dict[str, dict[str, Any]]]:
    return _qc.load_disk()


def _save_disk(quotes_map: dict[str, dict[str, Any]]) -> None:
    _qc.save_disk(quotes_map)


def _parse_chunk(chunk: list[str], df: Any) -> dict[str, dict[str, Any]]:
    """把 yf.download 的分块结果解析成 {symbol: quote}。"""
    out: dict[str, dict[str, Any]] = {}
    if df is None or df.empty:
        return out
    for sym in chunk:
        try:
            sub = df if len(chunk) == 1 else df[sym]
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            close = float(sub["Close"].iloc[-1])
            prev = float(sub["Close"].iloc[-2]) if len(sub) > 1 else close
            vol = float(sub["Volume"].iloc[-1]) if "Volume" in sub else 0.0
            if close <= 0:
                continue
            out[sym] = {
                "price": round(close, 4),
                "prev_close": round(prev, 4),
                "change_pct": round((close - prev) / prev * 100, 2) if prev else 0.0,
                "volume": vol,
                "amount": round(close * vol, 0),
            }
        except Exception:  # noqa: BLE001
            continue
    return out


def _fetch_all_quotes() -> dict[str, dict[str, Any]]:
    """并发抓全部成分股行情（分块 yf.download + 线程池）。"""
    syms = [c["symbol"] for c in constituents()["constituents"]]
    return _qc.fetch_all(syms, _parse_chunk, period="5d")


def _bg_refresh() -> None:
    """后台刷新行情并落盘。同一时刻仅一路（由 _refreshing 旗标保证）。

    ⚠️ 必须做覆盖率闸门（quote_cache.accept_refresh，铁律 12）：yfinance
    部分超时（只抓到 228/503）时若无条件覆盖，会把好的 503 只快照直接覆盖掉。
    """
    _qc.bg_refresh(_fetch_all_quotes)


def quote_cache_meta() -> dict[str, Any]:
    return _qc.meta()


# ---------------- 响应级快照（打开即有完整数据） ----------------
def _load_rank_rows() -> dict[str, dict[str, Any]]:
    """上次完整榜单（行情+估值+技术+评分+信号 全字段）。超过 7 天不用（太旧会误导）。"""
    from .cacheio import ensure_seed, load_json_snapshot

    ensure_seed(_RANK_SNAPSHOT)
    data = load_json_snapshot(_RANK_SNAPSHOT)
    if not data or not isinstance(data.get("rows"), list):
        return {}
    try:
        if time.time() - float(data.get("ts", 0.0)) > _RANK_SNAPSHOT_TTL:
            return {}
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in data["rows"]:
        if isinstance(r, dict) and r.get("symbol"):
            out[str(r["symbol"])] = r
    return out


def _save_rank_rows(rows: list[dict[str, Any]]) -> None:
    """落盘完整行（节流：5 分钟一次）。watched/_match_rank 是请求期临时字段，剔除。"""
    global _rank_snap_last
    with _rank_snap_lock:
        if time.time() - _rank_snap_last < 300:
            return
        _rank_snap_last = time.time()
    clean = [
        {k: v for k, v in r.items() if k not in ("watched", "_match_rank")}
        for r in rows
    ]
    from .cacheio import atomic_write_json

    atomic_write_json(_RANK_SNAPSHOT, {"ts": time.time(), "rows": clean})


def _maybe_save_rank_snapshot(rows: list[dict[str, Any]],
                              fund_meta: dict[str, Any],
                              tech_meta: dict[str, Any]) -> None:
    """三个数据源**都新鲜且覆盖过半**时才落盘 —— 快照必须是完整好数据，
    否则冷启动兜底会把残缺状态固化下来。"""
    if len(rows) < 200:
        return
    meta = quote_cache_meta()
    if meta["stale"] or meta["refreshing"]:
        return
    if fund_meta.get("stale") or fund_meta.get("refreshing"):
        return
    if tech_meta.get("stale") or tech_meta.get("refreshing"):
        return
    if fund_meta.get("covered", 0) < len(rows) * 0.5:
        return
    if tech_meta.get("covered", 0) < len(rows) * 0.5:
        return
    _save_rank_rows(rows)


def _fill_missing_from_snapshot(rows: list[dict[str, Any]],
                                snap_by: dict[str, dict[str, Any]]) -> int:
    """attach 之后仍为 None 的字段用上次快照补（只补 None，绝不覆盖新数据）。"""
    from .ranking_enrich import TECH_KEYS

    fund_keys = ("eps_ttm", "pe_ttm", "pe_state", "pb", "roe", "div_yield",
                 "turnover", "amplitude", "w52_high", "w52_low",
                 "pct_from_high", "market_cap_float")
    filled = 0
    for r in rows:
        s = snap_by.get(r.get("symbol"))
        if not s:
            continue
        for k in fund_keys:
            if r.get(k) is None and s.get(k) is not None:
                r[k] = s[k]
                filled += 1
        for k in TECH_KEYS:
            if r.get(k) is None and s.get(k) is not None:
                r[k] = s[k]
                filled += 1
        if not r.get("name_cn") and s.get("name_cn"):
            r["name_cn"] = s["name_cn"]
        if r.get("market_cap") is None and s.get("market_cap") is not None:
            r["market_cap"] = s["market_cap"]
    return filled


def quotes(force: bool = False) -> dict[str, dict[str, Any]]:
    """全部成分股的最新行情。

    stale-while-revalidate：缓存新鲜直接返回；过期/force 时**立即返回现有
    数据（可能为旧值或空）**，同时在后台线程刷新 —— HTTP 请求永不等待网络。
    冷启动先读磁盘快照。
    """
    return _qc.get(_fetch_all_quotes, force=force)


# ---------------- 榜单 ----------------
# 派生字段注入层（估值 / 技术指标 / 分位 / 评分）已按铁律 9 拆到 `ranking_enrich.py`。
# 这里**保留旧的下划线名字**作为别名：测试与外部调用一直在用
# `from app.rankings import _attach_fundamentals`，改名会静默断掉它们。
from .ranking_enrich import (  # noqa: E402
    add_pe_percentile as _add_pe_percentile,
)
from .ranking_enrich import (  # noqa: E402
    attach_fundamentals as _attach_fundamentals,
)
from .ranking_enrich import (  # noqa: E402
    attach_scores as _attach_scores,
)
from .ranking_enrich import (  # noqa: E402
    attach_technicals as _attach_technicals,
)

# 可排序字段。⚠️ 新增字段必须**同步**放开 `api/rankings.py` 里 `sort` 的 pattern 白名单，
# 否则请求会被 FastAPI 判为 422（排序白名单是两处，不是一处）。
# 现已改为：白名单**只在此处定义**，API 层用 `SORT_FIELDS` 动态生成正则（见 api/rankings.py）。
_SORT_NUMERIC = (
    "change_pct", "volume", "amount", "price", "market_cap", "market_cap_float",
    "pe_ttm", "eps_ttm", "pb", "roe", "div_yield", "turnover", "amplitude",
    "pct_from_high", "w52_high", "w52_low",
    # ---- 技术指标（1 年日线派生）----
    "r1m", "r3m", "r6m", "r1y", "vol_ann", "rsi14", "atr_pct", "beta",
    "ma20_rel", "ma60_rel", "ma200_rel", "excess_1y",
    # ---- 综合评分 ----
    "score",
    # ---- 选股中心：机会信号数 ----
    "signal_count",
)
# 布尔字段不能进 _SORT_NUMERIC（排序键要求数值），单独列出以便前端列头可排序
_SORT_BOOL = ("ma_bull",)
SORT_FIELDS: tuple[str, ...] = _SORT_NUMERIC + _SORT_BOOL + ("symbol",)


# 榜单计算纯函数（搜索匹配 / 排序 / 过滤）已按铁律 9 拆到 `rankings_calc.py`。
# 这里保留旧的下划线名字作为别名：测试与外部调用一直在用
# `from app.rankings import _match_rank`，改名会静默断掉它们。
from .rankings_calc import (  # noqa: E402,F401
    _build_filter,
    _CJK_RE,
    _match_rank,
    _name_match,
    _sort_rows,
)


def rankings(
    sort: str = "change_pct",
    direction: str = "desc",
    limit: int = 50,
    q: str = "",
    sector: str = "",
    pe_min: float | None = None,
    pe_max: float | None = None,
    pb_max: float | None = None,
    cap_min: float | None = None,
    div_min: float | None = None,
    roe_min: float | None = None,
    from_high_max: float | None = None,
    exclude_loss: bool = False,
    rsi_min: float | None = None,
    rsi_max: float | None = None,
    above_ma200: bool = False,
    below_ma200: bool = False,
    vol_max: float | None = None,
    beta_max: float | None = None,
    score_min: float | None = None,
    only_bull: bool = False,
    req_1y_min: float | None = None,
    excess_min: float | None = None,
    signal: str = "",
    weights: dict[str, Any] | None = None,
    threshold: float = 70.0,
) -> dict[str, Any]:
    """榜单查询。q 匹配 symbol（精确/前缀）或 name/name_cn（词首/子串），不区分大小写。

    搜索命中按匹配质量排序（代码精确 > 代码前缀 > 名称命中），且**忽略候选池
    评分门槛** —— 详见下方 effective_score_min 处的说明。

    `cap_min` 单位是**亿美元**（UI 口径）；`from_high_max` 是距 52 周高的百分比上限。
    顺序固定为「注入 → 分位 → 评分 → 信号 → 筛选 → 排序」，不可颠倒
    （后三步都依赖注入后的字段；评分依赖 PE 分位，所以必须在分位之后；
    信号依赖评分与全部注入字段，必须在评分之后）。
    """
    if sort not in SORT_FIELDS:
        sort = "change_pct"
    cons = constituents()["constituents"]
    by_sym = {c["symbol"]: c for c in cons}
    qs = quotes()
    q_lower = (q or "").strip().lower()

    # ---- 响应级快照兜底（「打开即有完整数据」）----
    # 行情缓存空/不完整（冷启动、快照损坏、扩池初期）时，用上次完整榜单补行。
    # 用户看到的是完整旧数据（标 stale），后台刷新就绪后 5s 轮询自动替换。
    snap_by = _load_rank_rows() if len(qs) < len(by_sym) * 0.9 else {}
    snapshot_restored = bool(snap_by) and len(qs) < len(by_sym)

    rows: list[dict[str, Any]] = []
    for sym, qt in qs.items():
        meta = by_sym.get(sym, {})
        if sector and meta.get("sector") != sector:
            continue
        base = snap_by.get(sym) or {}
        rows.append({
            **base,
            "symbol": sym,
            "name": meta.get("name") or base.get("name") or "",
            "sector": meta.get("sector") or base.get("sector") or "",
            "watched": False,   # 由 API 层填充
            "_match_rank": 0,   # 搜索匹配质量（排序用，返回前剔除）
            **qt,               # 新行情永远压过快照旧值
        })
    # 快照里有、行情缓存里还没有的票（冷启动整段补 / 扩池初期新票未抓完）
    for sym, snap_row in snap_by.items():
        if sym in qs:
            continue
        meta = by_sym.get(sym, {})
        if sector and meta.get("sector") != sector:
            continue
        rows.append({
            **snap_row,
            "symbol": sym,
            "name": meta.get("name") or snap_row.get("name") or "",
            "sector": meta.get("sector") or snap_row.get("sector") or "",
            "watched": False,
            "_match_rank": 0,
        })

    # 中文名 + 总市值（腾讯批量行情，落库缓存）：必须在**排序前**注入。
    # ⚠️ 也必须在下方的搜索匹配**之前** —— 否则搜中文名（如「赛默飞」）永远搜不到，
    # 因为 name_cn 是后注入的字段，旧实现是在它注入前就把不匹配的行丢掉了。
    try:
        from .company import enrich

        info = enrich([r["symbol"] for r in rows])
        for r in rows:
            x = info.get(r["symbol"]) or {}
            r["name_cn"] = x.get("name_cn", "")
            r["market_cap"] = x.get("market_cap")
    except Exception:  # noqa: BLE001
        pass

    # 搜索匹配（拿到 name_cn 之后再做）：9 = 未命中，随后被剔除。
    if q_lower:
        for r in rows:
            m = _match_rank(r["symbol"], str(r.get("name", "")), str(r.get("name_cn") or ""), q_lower)
            r["_match_rank"] = 9 if m is None else m
        rows = [r for r in rows if r["_match_rank"] != 9]

    fund_meta = _attach_fundamentals(rows)
    tech_meta = _attach_technicals(rows)
    # 快照补缺：attach 会把数据源未就绪的字段置 None —— 用上次快照补回来
    # （只补 None，绝不覆盖新数据）。之后分位/评分/信号都在完整字段上计算。
    if snapshot_restored:
        _fill_missing_from_snapshot(rows, snap_by)
    _add_pe_percentile(rows)                 # 对全集算，筛选后分位基准才稳定
    _attach_scores(rows, weights, threshold)  # 依赖 pe_pct，故在分位之后
    # 选股中心信号（依赖 pe_pct / roe / 技术指标 / 评分之后的字段语义）：
    # 必须在**筛选前**注入 —— focus 要对全池挑，signal 筛选本身也依赖它。
    from .signals import attach_signals, pick_focus

    attach_signals(rows)
    focus = pick_focus(rows)                 # 全池 top（筛选前），直接回答「哪些值得关注」
    universe_total = len(rows)
    # 数据源全部新鲜时落盘响应级快照（节流 5 分钟），供下次冷启动秒开
    _maybe_save_rank_snapshot(rows, fund_meta, tech_meta)
    # ⚠️ 搜索时忽略「候选池评分门槛」（score_min）。
    # score_min 是「候选观察池」视图自动加的隐含门槛（= 阈值，默认 70），不是用户
    # 主动勾的筛选条件。旧实现让 q 与 score_min 做 AND —— 于是搜 "TMO" 时，
    # TMO 综合分 40.2 < 70 被门槛挡掉，接口返回 0 行，页面提示「没有匹配的标的」。
    # 用户输入一个明确的代码是在**查这只股票**，不是在浏览候选池，必须能查到。
    # 注意：PE / RSI / 均线等**用户主动设置**的筛选条件不受影响，仍然生效。
    effective_score_min = None if q_lower else score_min
    keep = _build_filter(pe_min, pe_max, pb_max, cap_min, div_min, roe_min,
                         from_high_max, exclude_loss, rsi_min, rsi_max,
                         above_ma200, below_ma200, vol_max, beta_max,
                         effective_score_min, only_bull, req_1y_min, excess_min)
    rows = [r for r in rows if keep(r)]
    # 信号筛选（选股中心）：只看触发了某个信号的标的。
    # ⚠️ 与指标筛选同语义：完全没触发才排除；signal key 不认识时静默忽略
    # （前端目录是数据驱动的，不会发出未知 key）。
    if signal:
        rows = [r for r in rows if any(s.get("key") == signal for s in (r.get("signals") or []))]
    _sort_rows(rows, sort, direction != "asc")
    for r in rows:                       # _match_rank 是内部排序键，不对外暴露
        r.pop("_match_rank", None)

    total = len(rows)
    meta = quote_cache_meta()
    # 评分分布（前端画分档统计用）—— 在**筛选后**统计，反映用户当前看到的这一批
    bands = {"buy": 0, "mid": 0, "low": 0, "na": 0}
    for r in rows:
        bands[str(r.get("score_band") or "na")] = bands.get(str(r.get("score_band") or "na"), 0) + 1
    # 信号统计：当前筛选结果里各信号触发了多少只（前端做「点击筛选」入口）
    from .signals import signal_stats

    return {
        "total": total,
        "universe_total": universe_total,
        "count": min(limit, total),
        # 搜索时是否绕过了候选池评分门槛（前端据此给出「已忽略门槛」提示，
        # 否则用户在候选池视图里看到 40 分的标的会以为门槛失效了）
        "pool_bypassed": bool(q_lower and score_min is not None),
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "universe": "S&P 500",
        "quote_age_sec": meta["age_sec"],
        "stale": meta["stale"],
        "refreshing": meta["refreshing"],
        "fundamentals": fund_meta,
        "technicals": tech_meta,
        "bands": bands,
        "threshold": threshold,
        "active_signal": signal or None,
        "signal_stats": signal_stats(rows),
        "focus": focus,
        # 打开即有完整数据：本次是否用了响应级快照兜底（前端提示「缓存秒开，后台刷新中」）
        "snapshot_restored": snapshot_restored,
        "rows": rows[: max(1, min(limit, 3000))],
        "sectors": sorted({c["sector"] for c in cons if c.get("sector")}),
    }
