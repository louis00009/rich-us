"""盘前监控（美东 04:00–09:30）+ 新闻增强 + AI 盘前综述。

需求背景（2026-09-28 用户）：
    「盘前监控，开盘前应该是盘前监控，抓新闻进来，然后帮助选股」；
    「可以尝试通过 AI 去抓取一些信息，帮助每日开盘实时监控」。

数据源与口径
------------
· 盘前价：yfinance 批量 5m K 线（prepost=True）。免费源里唯一可用的盘前价，
  美东 04:00 起大中型票陆续有 bar；小票可能整段无盘前交易（无 bar → 不参与排行，合理）。
· 盘前涨跌幅 = 盘前最新价 ÷ 昨收 − 1。昨收取榜单行情缓存的 prev_close（同源自洽）。
· 盘前量 = 09:30 ET 之前所有 5m bar 的成交量累计 —— 衡量盘前关注度。
· 新闻：`news.fetch_news`（yahoo-rss，内部带缓存），对涨/跌 top 并发抓取，
  每只附最多 2 条标题 —— 「为什么动」往往比「动了多少」更值钱。

缓存策略（与 movers 同款三层）
------------------------------
内存 TTL 300s + stale-while-revalidate + 磁盘快照 + 覆盖率闸门。
池子 2241 只后全池抓取 ~1-2 分钟，5 分钟 TTL 仍能覆盖（盘前价格变化远慢于盘中）。

时段判定
--------
America/New_York：04:00–09:30 = premarket；09:30–16:00 = regular；
16:00–20:00 = afterhours；其余 = closed。非盘前时段返回最后一次盘前快照并带 note，
前端据此显示「盘前时段：北京时间 16:00–21:30（夏令时）」。
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from zoneinfo import ZoneInfo

from .cacheio import atomic_write_json, load_json_snapshot
from .config import CACHE_DIR

_ET = ZoneInfo("America/New_York")
_PREMARKET_TTL = 300          # 盘前数据 5 分钟（盘前价格节奏慢，且全池抓取 ~30s）
_SNAPSHOT = CACHE_DIR / "premarket.json"
_CHUNK = 100
_WORKERS = 5
_MIN_REFRESH_RATIO = 0.6      # 盘前覆盖率天然偏低（小票无盘前交易），闸门放宽
_NEWS_TTL = 600               # 新闻缓存 10 分钟（标题短时间不会变）
_NEWS_WORKERS = 6

_lock = threading.Lock()
_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_refreshing = False
_state: dict[str, Any] = {"last": 0.0, "ok": None}
_news_lock = threading.Lock()
_news_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_universe: list[str] = []


# ---------------- 时段 ----------------
def et_now() -> Any:
    from datetime import datetime as _dt

    return _dt.now(_ET)


def session_state() -> str:
    """premarket / regular / afterhours / closed（按美东时间）。"""
    t = et_now()
    wd = t.weekday()                     # 5=周六 6=周日
    hm = t.hour * 60 + t.minute
    if wd >= 5:
        return "closed"
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "regular"
    if 16 * 60 <= hm < 20 * 60:
        return "afterhours"
    return "closed"


# ---------------- 盘前行情 ----------------
def _load_disk() -> tuple[float, dict[str, dict[str, Any]]]:
    from .cacheio import ensure_seed

    ensure_seed(_SNAPSHOT)
    data = load_json_snapshot(_SNAPSHOT)
    if data and data.get("quotes"):
        try:
            return float(data.get("ts", 0.0)), dict(data["quotes"])
        except Exception:  # noqa: BLE001
            return 0.0, {}
    return 0.0, {}


def _save_disk(quotes_map: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(_SNAPSHOT, {"ts": time.time(), "quotes": quotes_map})


def _parse_chunk(chunk: list[str], df: Any) -> dict[str, dict[str, Any]]:
    """把 prepost 5m K 线解析成 {sym: 盘前字段}。

    盘前价 = 09:30 ET 之前最后一根 bar 的 close；盘前量 = 09:30 前 bars 的量累计。
    无盘前 bar（小票/无盘前交易）→ 不输出该标的。
    """
    out: dict[str, dict[str, Any]] = {}
    if df is None or df.empty:
        return out
    cutoff = et_now().replace(hour=9, minute=30, second=0, microsecond=0)
    for sym in chunk:
        try:
            # ⚠️ 列形态有两种：多标的 yf.download → MultiIndex（group_by="ticker"）；
            # 单标的 → 扁平列。`df[sym]` 只对 MultiIndex 成立 —— chunk 恰好 1 只时
            # （标的总数 % 100 == 1）df 仍是 MultiIndex，直接 `sub = df` 会让
            # dropna/取列在 MultiIndex 上跑出空结果（自检抓过）。
            if len(chunk) == 1:
                sub = df[sym] if (hasattr(df.columns, "nlevels") and df.columns.nlevels > 1) else df
            else:
                sub = df[sym]
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            idx = sub.index
            if getattr(idx, "tz", None) is None:
                idx = idx.tz_localize("UTC")
            idx_et = idx.tz_convert(_ET)
            mask = idx_et < cutoff
            if not bool(mask.any()):
                continue                      # 无盘前 bar（全是盘中或无数据）
            pre = sub[mask]
            close = float(pre["Close"].iloc[-1])
            vol = float(pre["Volume"].sum()) if "Volume" in pre else 0.0
            if close <= 0:
                continue
            out[sym] = {
                "pre_price": round(close, 4),
                "pre_vol": int(vol),
                "pre_time": str(idx_et[mask][-1])[:16],
            }
        except Exception:  # noqa: BLE001 —— 单只失败不影响整批
            continue
    return out


def _fetch_all_premarket() -> dict[str, dict[str, Any]]:
    """并发抓全池盘前 5m K 线。"""
    syms = list(_universe)
    chunks = [syms[i: i + _CHUNK] for i in range(0, len(syms), _CHUNK)]

    def work(chunk: list[str]) -> dict[str, dict[str, Any]]:
        try:
            import yfinance as yf

            df = yf.download(
                tickers=" ".join(chunk), period="1d", interval="5m",
                group_by="ticker", threads=False, progress=False,
                auto_adjust=False, prepost=True,
            )
            return _parse_chunk(chunk, df)
        except Exception:  # noqa: BLE001
            return {}

    out: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for res in ex.map(work, chunks):
            out.update(res)
    return out


def _bg_refresh() -> None:
    global _cache, _refreshing
    try:
        fresh = _fetch_all_premarket()
        _, old = _cache
        if fresh and (len(fresh) >= len(old) * _MIN_REFRESH_RATIO or not old):
            with _lock:
                _cache = (time.time(), fresh)
            _save_disk(fresh)
            _state["ok"] = True
        else:
            _state["ok"] = False
            _state["error"] = (
                f"本次只抓到 {len(fresh)} 只（旧快照 {len(old)} 只），保留旧快照"
            )[:160]
    except Exception as exc:  # noqa: BLE001
        _state["ok"] = False
        _state["error"] = f"{type(exc).__name__}: {exc}"[:160]
    finally:
        with _lock:
            _refreshing = False
        _state["last"] = time.time()


def _refresh_async(syms: list[str]) -> None:
    global _refreshing
    with _lock:
        if len(syms) > len(_universe):
            _universe[:] = syms
        if _refreshing or not _universe:
            return
        _refreshing = True
    threading.Thread(target=_bg_refresh, daemon=True, name="premarket-refresh").start()


def quotes(force: bool = False) -> dict[str, dict[str, Any]]:
    """全池盘前行情 {sym: {pre_price, pre_vol, pre_time}}。stale-while-revalidate。"""
    global _cache
    ts, data = _cache
    if not data:
        ts, data = _load_disk()
        if data:
            with _lock:
                if not _cache[1]:
                    _cache = (ts, data)

    fresh_enough = bool(data) and not force and time.time() - ts < _PREMARKET_TTL
    if fresh_enough:
        return data
    from .rankings import constituents

    _refresh_async([c["symbol"] for c in constituents()["constituents"]])
    return dict(data)


def meta() -> dict[str, Any]:
    ts, data = _cache
    return {
        "count": len(data),
        # 盘前数据真正抓取完成的时刻（≠ 响应生成时间）—— 前端「上次更新」显示用它
        "updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else None,
        "age_sec": int(time.time() - ts) if ts else None,
        "stale": (not data) or (time.time() - ts >= _PREMARKET_TTL),
        "refreshing": _refreshing,
        "last_refresh_ok": _state.get("ok"),
        "error": _state.get("error"),
        "session": session_state(),
    }


# ---------------- 新闻增强 ----------------
def _news_for(symbol: str, limit: int = 2) -> list[dict[str, str]]:
    """单只新闻（带 10 分钟缓存）。失败返回空 —— 新闻是增强，绝不阻塞主流程。"""
    now = time.time()
    with _news_lock:
        hit = _news_cache.get(symbol)
        if hit and now - hit[0] < _NEWS_TTL:
            return hit[1]
    try:
        from .news import fetch_news

        res = fetch_news(symbol, limit=limit)
        items = [
            {"headline": str(it.get("headline") or "")[:120],
             "source": str(it.get("source") or ""),
             "published": str(it.get("published_at") or "")[:16]}
            for it in (res.get("items") or [])[:limit]
            if it.get("headline")
        ]
    except Exception:  # noqa: BLE001
        items = []
    with _news_lock:
        _news_cache[symbol] = (now, items)
    return items


def _attach_news(rows: list[dict[str, Any]], per_symbol: int = 2) -> None:
    """并发给 rows 挂新闻（rows 会被原地更新）。"""
    if not rows:
        return
    with ThreadPoolExecutor(max_workers=_NEWS_WORKERS) as ex:
        futs = {ex.submit(_news_for, r["symbol"], per_symbol): r for r in rows}
        for fut, r in futs.items():
            try:
                r["news"] = fut.result()
            except Exception:  # noqa: BLE001
                r["news"] = []


# ---------------- 盘前异动 ----------------
def movers(threshold: float = 2.0, limit: int = 12, with_news: bool = True,
           force: bool = False) -> dict[str, Any]:
    """盘前异动榜：涨/跌各 limit 只，附新闻。

    阈值默认 2% —— 盘前流动性薄，1% 级别的跳动多为噪音；
    盘前量也一并返回（< 1 万股的异动可信度低，前端可提示）。
    force=True：手动刷新 —— 数据即使还新鲜也强制起一轮后台抓取。
    """
    from .rankings import constituents, quotes as r_quotes

    pre = quotes(force=force)
    prev = r_quotes()                       # 昨收与现价同源（榜单行情缓存）
    cons = {c["symbol"]: c for c in constituents()["constituents"]}

    rows: list[dict[str, Any]] = []
    for sym, p in pre.items():
        q = prev.get(sym) or {}
        prev_close = q.get("prev_close")
        if not isinstance(prev_close, (int, float)) or prev_close <= 0:
            continue
        pct = round((p["pre_price"] - prev_close) / prev_close * 100, 2)
        if abs(pct) < threshold:
            continue
        cmeta = cons.get(sym) or {}
        rows.append({
            "symbol": sym,
            "name": cmeta.get("name") or q.get("name") or "",
            "name_cn": q.get("name_cn") or "",
            "sector": cmeta.get("sector") or "",
            "pre_price": p["pre_price"],
            "prev_close": round(prev_close, 2),
            "pre_pct": pct,
            "pre_vol": p.get("pre_vol", 0),
            "pre_time": p.get("pre_time"),
            "reg_price": q.get("price"),     # 盘前快照时的常规价（参考）
        })
    rows.sort(key=lambda r: r["pre_pct"], reverse=True)
    gainers = [r for r in rows if r["pre_pct"] > 0][:limit]
    losers = [r for r in rows if r["pre_pct"] < 0][:limit]
    if with_news:
        _attach_news((gainers + losers)[:24])
    m = meta()
    return {
        "session": m["session"],
        "is_premarket": m["session"] == "premarket",
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "quotes_updated": m["updated"],      # 盘前数据真正抓取完成的时刻（前端「上次更新」）
        "age_sec": m["age_sec"],
        "stale": m["stale"],
        "refreshing": m["refreshing"],
        "covered": m["count"],
        "note": (
            "盘前监控中（美东 04:00–09:30）" if m["session"] == "premarket"
            else f"当前美东时段：{m['session']} —— 显示的是最近一次盘前快照"
        ),
        "gainers": gainers,
        "losers": losers,
        "threshold": threshold,
    }


# ---------------- AI 盘前综述 ----------------
def analyze(model: str = "", threshold: float = 2.0) -> dict[str, Any]:
    """AI 盘前综述：top movers + 新闻标题 → 一段可执行的盘前要点。

    LLM 失败降级本地统计（engine="local"）—— 与 movers.analyze 同款契约。
    """
    from .ai_analyst import _llm_call

    mv = movers(threshold=threshold, limit=12)
    top = (mv["gainers"][:8] + mv["losers"][:8])

    def _line(r: dict[str, Any]) -> str:
        head = "；".join(n["headline"] for n in (r.get("news") or [])[:2]) or "（无新闻）"
        return (
            f"{r['symbol']}（{r.get('name_cn') or r.get('name')}，{r.get('sector')}）"
            f"盘前 {r['pre_pct']:+.1f}%（{r['prev_close']}→{r['pre_price']}），"
            f"盘前量 {r['pre_vol']:,}。新闻：{head}"
        )

    if not top:
        return {
            "engine": "local", "model": "",
            "summary": "盘前暂无触发阈值的异动（阈值 ±{:.0f}%）。可降低阈值再试。".format(threshold),
            "updated": mv["updated"], "session": mv["session"],
        }

    context = "\n".join(_line(r) for r in top)
    prompt = f"""以下是美股盘前（美东 04:00–09:30）异动最大的标的与相关新闻：

{context}

请输出盘前综述（简体中文，≤400 字）：
1. 今日盘前主线（哪些板块/主题在动，依据新闻归纳，不要编造）
2. 值得开盘重点关注的 3~5 只（说明理由：盘前量能 + 新闻催化 + 幅度）
3. 风险提示（盘前流动性薄、新闻真伪待确认等）
只基于给定信息，不得编造。"""

    model_name = model
    try:
        text = _llm_call(
            [{"role": "system", "content": "你是严谨的美股盘前分析师，只基于给定数据与新闻归纳，不编造。输出简体中文。"},
             {"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=900, timeout=120,
            model_name=model_name, reasoning_effort="low",
        )
        engine, model_used = "llm", model_name
    except Exception as exc:  # noqa: BLE001 —— LLM 失败降级本地统计
        g = mv["gainers"]
        l = mv["losers"]
        text = (
            f"（AI 暂不可用：{type(exc).__name__}，以下为本地统计）\n"
            f"盘前上涨 {len(g)} 只触发阈值，最强 {g[0]['symbol']} {g[0]['pre_pct']:+.1f}%；"
            f"下跌 {len(l)} 只触发，最深 {l[0]['symbol']} {l[0]['pre_pct']:+.1f}%。"
            f"盘前量最大：{max(top, key=lambda r: r['pre_vol'])['symbol']}。"
            f"盘前流动性薄，幅度与新闻需开盘后确认。"
        )
        engine, model_used = "local", ""

    return {
        "engine": engine, "model": model_used,
        "summary": text.strip(),
        "updated": mv["updated"], "session": mv["session"],
        "gainers": mv["gainers"], "losers": mv["losers"],
    }
