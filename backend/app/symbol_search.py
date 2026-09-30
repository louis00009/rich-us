"""全市场标的搜索（从 `data_provider.py` 拆出，铁律 9，2026-09-30）。

本地 `universe.UNIVERSE` 是精选集，覆盖不了全市场 —— 搜 SPCX（SpaceX）之类
新上市标的必须联网。这里用 Yahoo search API 兜底，带 TTL 缓存 + 失败静默降级。

⚠️ 失败（空结果）走**短 TTL 负缓存**：旧实现按正常 TTL 缓存空结果，一次网络抖动
   会让该关键词在 10 分钟内始终搜不到，恢复被掩盖。
"""
from __future__ import annotations

import time

import httpx

from .ds_state import _bounded_set, _last_errors
from .universe import UNIVERSE, SymbolInfo


# ------------------------------------------------------------------
# 全市场搜索（Yahoo search API 兜底）：本地 UNIVERSE 是精选集（S&P 500 + 常用
# ETF/港股/指数），覆盖不了全市场——搜 SPCX（SpaceX）之类的新上市标的必须联网搜。
# 带 10 分钟 TTL 缓存 + 失败静默降级（本地结果兜底）。
# ------------------------------------------------------------------
_yahoo_search_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_YAHOO_SEARCH_TTL = 600.0
# P3：失败（空结果）只做短 TTL 负缓存 —— 旧实现按正常 TTL 缓存空结果，
# 一次网络抖动会让该关键词在 10 分钟内始终搜不到，恢复被掩盖。
_YAHOO_SEARCH_FAIL_TTL = 60.0
_KIND_MAP = {
    "EQUITY": "STK", "ETF": "ETF", "INDEX": "IDX", "CRYPTOCURRENCY": "CRYPTO",
    "FUTURE": "FUT", "OPTION": "OPT", "CURRENCY": "FX", "MUTUALFUND": "FUND",
}


def _yahoo_search(q: str, limit: int) -> list[dict[str, str]]:
    """Yahoo Finance 全市场搜索（股票/ETF/指数/加密，无需 key）。失败返回空。"""
    key = f"{q.upper()}|{limit}"
    now = time.time()
    hit = _yahoo_search_cache.get(key)
    if hit:
        # 空结果走短 TTL（见 _YAHOO_SEARCH_FAIL_TTL 注释）
        ttl = _YAHOO_SEARCH_TTL if hit[1] else _YAHOO_SEARCH_FAIL_TTL
        if now - hit[0] < ttl:
            return hit[1]
    out: list[dict[str, str]] = []
    try:
        r = httpx.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": limit, "newsCount": 0, "listsCount": 0},
            headers={"User-Agent": "Mozilla/5.0 QuantDesk"},
            timeout=8,
        )
        r.raise_for_status()
        for qt in (r.json().get("quotes") or [])[:limit]:
            sym = str(qt.get("symbol") or "").strip()
            if not sym:
                continue
            kind = _KIND_MAP.get(str(qt.get("quoteType") or ""), "STK")
            name = str(qt.get("longname") or qt.get("shortname") or "")
            exch = str(qt.get("exchDisp") or qt.get("exchange") or "")
            out.append({"symbol": sym, "name": f"{name} [{exch}]" if exch else name, "kind": kind})
        _bounded_set(_yahoo_search_cache, key, (now, out))
    except Exception as exc:  # noqa: BLE001 —— 搜索失败静默，本地结果兜底
        _last_errors["yahoo-search"] = f"{type(exc).__name__}: {exc}"[:160]
        _bounded_set(_yahoo_search_cache, key, (now, []))
    return _yahoo_search_cache.get(key, (now, []))[1]


def search_symbols(q: str, limit: int = 20) -> list[dict[str, str]]:
    """标的搜索：本地 UNIVERSE 命中排前，Yahoo 全市场结果补充（去重）。"""
    q_raw = (q or "").strip()
    q = q_raw.upper()
    if not q:
        return [{"symbol": s.symbol, "name": s.name, "kind": s.kind} for s in UNIVERSE[:limit]]
    scored: list[tuple[int, SymbolInfo]] = []
    for s in UNIVERSE:
        sym, nm = s.symbol.upper(), s.name.upper()
        if sym == q:
            scored.append((0, s))
        elif sym.startswith(q):
            scored.append((1, s))
        elif q in sym:
            scored.append((2, s))
        elif q_raw.upper() in nm:
            scored.append((3, s))
    scored.sort(key=lambda x: (x[0], len(x[1].symbol)))
    local = [{"symbol": s.symbol, "name": s.name, "kind": s.kind} for _, s in scored[:limit]]
    # 全市场兜底（q 长度 ≥ 2 才联网，单字符结果太多没意义）
    remote: list[dict[str, str]] = []
    if len(q_raw) >= 2:
        seen = {x["symbol"] for x in local}
        for r in _yahoo_search(q_raw, limit):
            if r["symbol"] not in seen:
                remote.append(r)
    return (local + remote)[:limit]
