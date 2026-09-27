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
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .config import CACHE_DIR

SNAPSHOT_PATH = Path(__file__).resolve().parent / "markets" / "sp500.json"
_QUOTES_SNAPSHOT = CACHE_DIR / "sp500_quotes.json"
_REFRESH_TTL = 7 * 86400
_QUOTE_TTL = 600
_CHUNK = 100
_WORKERS = 4

_snap_lock = threading.Lock()
_snap_cache: dict[str, Any] | None = None
_snap_loaded_at = 0.0

_quote_lock = threading.Lock()
_quote_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_refreshing = False
_refresh_state: dict[str, Any] = {"last": 0.0, "ok": None}


# ---------------- 成分股 ----------------
def constituents() -> dict[str, Any]:
    """返回 {updated, count, constituents:[{symbol,name,sector,sub_sector}]}。

    P2：快照文件缺失/损坏时旧实现直接裸抛（API 层 500）。
    现在返回带 `error` 的空结构，并触发一次后台刷新尝试；
    调用方（rankings()）据此返回空榜单而不是崩掉。
    """
    global _snap_cache, _snap_loaded_at
    with _snap_lock:
        if _snap_cache is not None:
            return _snap_cache
        try:
            data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data.get("constituents"):
                raise ValueError("快照内容为空")
        except Exception as exc:  # noqa: BLE001
            return {
                "updated": "", "source": "missing", "count": 0, "constituents": [],
                "error": f"成分股快照不可用（{type(exc).__name__}: {exc}）——可在榜单页点刷新重建",
            }
        _snap_cache = data
        _snap_loaded_at = time.time()
        return data


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
    try:
        if _QUOTES_SNAPSHOT.exists():
            data = json.loads(_QUOTES_SNAPSHOT.read_text(encoding="utf-8"))
            return float(data.get("ts", 0.0)), dict(data.get("quotes", {}))
    except Exception:  # noqa: BLE001
        pass
    return 0.0, {}


def _save_disk(quotes_map: dict[str, dict[str, Any]]) -> None:
    try:
        _QUOTES_SNAPSHOT.write_text(
            json.dumps({"ts": time.time(), "quotes": quotes_map}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


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
    chunks = [syms[i: i + _CHUNK] for i in range(0, len(syms), _CHUNK)]

    def work(chunk: list[str]) -> dict[str, dict[str, Any]]:
        try:
            import yfinance as yf

            df = yf.download(
                tickers=" ".join(chunk), period="5d", interval="1d",
                group_by="ticker", threads=False, progress=False, auto_adjust=False,
            )
            return _parse_chunk(chunk, df)
        except Exception:  # noqa: BLE001
            return {}

    out: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        futs = [ex.submit(work, c) for c in chunks]
        for f in as_completed(futs):
            out.update(f.result() or {})
    return out


def _bg_refresh() -> None:
    """后台刷新行情并落盘。同一时刻仅一路（由 _refreshing 旗标保证）。"""
    global _quote_cache, _refreshing
    try:
        fresh = _fetch_all_quotes()
        if fresh:
            with _quote_lock:
                _quote_cache = (time.time(), fresh)
            _save_disk(fresh)
            _refresh_state["ok"] = True
        else:
            _refresh_state["ok"] = False
    except Exception as exc:  # noqa: BLE001
        _refresh_state["ok"] = False
        _refresh_state["error"] = f"{type(exc).__name__}: {exc}"[:160]
    finally:
        with _quote_lock:
            _refreshing = False
        _refresh_state["last"] = time.time()


def quote_cache_meta() -> dict[str, Any]:
    ts, data = _quote_cache
    return {
        "count": len(data),
        "age_sec": int(time.time() - ts) if ts else None,
        "stale": (not data) or (time.time() - ts >= _QUOTE_TTL),
        "refreshing": _refreshing,
        "last_refresh_ok": _refresh_state.get("ok"),
    }


def quotes(force: bool = False) -> dict[str, dict[str, Any]]:
    """全部成分股的最新行情。

    stale-while-revalidate：缓存新鲜直接返回；过期/force 时**立即返回现有
    数据（可能为旧值或空）**，同时在后台线程刷新 —— HTTP 请求永不等待网络。
    冷启动先读磁盘快照。
    """
    global _quote_cache, _refreshing
    ts, data = _quote_cache
    if not data:                       # 冷启动：尝试磁盘快照
        ts, data = _load_disk()
        if data:
            with _quote_lock:
                if not _quote_cache[1]:
                    _quote_cache = (ts, data)

    fresh_enough = bool(data) and not force and time.time() - ts < _QUOTE_TTL
    if fresh_enough:
        return data

    with _quote_lock:
        busy = _refreshing
        if not busy:
            _refreshing = True
    if not busy:
        threading.Thread(target=_bg_refresh, daemon=True, name="rankings-refresh").start()
    return dict(data)


# ---------------- 榜单 ----------------
_SORTERS = {
    "change_pct": lambda x: x["change_pct"],
    "volume": lambda x: x["volume"],
    "amount": lambda x: x["amount"],
    "price": lambda x: x["price"],
    "symbol": lambda x: x["symbol"],
    "market_cap": lambda x: x.get("market_cap") or 0.0,   # 总市值（腾讯行情，亿美元→美元）
}


def rankings(
    sort: str = "change_pct",
    direction: str = "desc",
    limit: int = 50,
    q: str = "",
    sector: str = "",
) -> dict[str, Any]:
    """榜单查询。q 匹配 symbol/name（不区分大小写），sector 过滤行业。"""
    cons = constituents()["constituents"]
    by_sym = {c["symbol"]: c for c in cons}
    qs = quotes()
    q_lower = (q or "").strip().lower()

    rows: list[dict[str, Any]] = []
    for sym, qt in qs.items():
        meta = by_sym.get(sym, {})
        if q_lower and q_lower not in sym.lower() and q_lower not in str(meta.get("name", "")).lower():
            continue
        if sector and meta.get("sector") != sector:
            continue
        rows.append({
            "symbol": sym,
            "name": meta.get("name", ""),
            "sector": meta.get("sector", ""),
            "watched": False,   # 由 API 层填充
            **qt,
        })

    # 中文名 + 总市值（腾讯批量行情，落库缓存）：必须在**排序前**注入
    try:
        from .company import enrich

        info = enrich([r["symbol"] for r in rows])
        for r in rows:
            x = info.get(r["symbol"]) or {}
            r["name_cn"] = x.get("name_cn", "")
            r["market_cap"] = x.get("market_cap")
    except Exception:  # noqa: BLE001
        pass

    fn = _SORTERS.get(sort, _SORTERS["change_pct"])
    rows.sort(key=fn, reverse=(direction != "asc"))
    total = len(rows)
    meta = quote_cache_meta()
    return {
        "total": total,
        "count": min(limit, total),
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "universe": "S&P 500",
        "quote_age_sec": meta["age_sec"],
        "stale": meta["stale"],
        "refreshing": meta["refreshing"],
        "rows": rows[: max(1, min(limit, 503))],
        "sectors": sorted({c["sector"] for c in cons if c.get("sector")}),
    }
