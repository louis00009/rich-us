"""新闻聚合：统一 NewsItem 模型 + provider 注册制 + SQLite 缓存。

设计（与 data_provider 同一思路）：
  · 每个 provider 只做一件事：给 symbol / 市场类别，返回 list[NewsItem]。
  · 服务层负责 去重 → 落库 → TTL 内存缓存 → 网络失败回读缓存。
  · provider 任何异常都不能把接口打挂 —— 失败的记进 status，成功的照常返回。
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import settings


# ======================================================================
# 数据模型
# ======================================================================
@dataclass
class NewsItem:
    source: str                       # finnhub | yahoo-rss | ibkr | hkex
    headline: str
    url: str = ""
    summary: str = ""
    symbol: str = ""                  # 关联标的（空 = 市场级快讯）
    market: str = "US"
    category: str = "company"         # company | market | announcement
    published_at: str = ""            # ISO 8601 UTC；解析失败留空（不猜）
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        raw = f"{self.source}|{self.url or self.headline.strip()}"
        return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:40]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "headline": self.headline,
            "url": self.url,
            "summary": self.summary,
            "symbol": self.symbol,
            "market": self.market,
            "category": self.category,
            "published_at": self.published_at,
            "extra": self.extra,
        }


class NewsProvider(Protocol):
    name: str
    def fetch(self, symbol: str | None, limit: int = 20) -> list[NewsItem]: ...


# ======================================================================
# 注册制
# ======================================================================
_providers: dict[str, NewsProvider] = {}
_reg_lock = threading.Lock()


def register_news_provider(provider: NewsProvider) -> None:
    with _reg_lock:
        _providers[provider.name] = provider


def get_news_provider(name: str) -> NewsProvider | None:
    return _providers.get(name)


def available_news_providers() -> list[str]:
    return list(_providers)


# 各市场的抓取优先级（先本地公告，后国际聚合）
_PRIORITY: dict[str, list[str]] = {
    "HK": ["hkex", "finnhub", "yahoo-rss", "ibkr"],
    "US": ["finnhub", "yahoo-rss", "ibkr", "hkex"],
}


# ======================================================================
# 服务层
# ======================================================================
_sym_cache: dict[str, tuple[float, list[NewsItem]]] = {}
_cache_lock = threading.Lock()
_last_status: dict[str, Any] = {"providers": {}, "ts": 0.0}


def _market_of(symbol: str) -> str:
    try:
        from ..markets import symbols as mksym
        return mksym.parse(symbol).market
    except Exception:  # noqa: BLE001
        return "HK" if symbol.upper().endswith(".HK") else "US"


def fetch_news(symbol: str, limit: int = 20, force: bool = False) -> dict[str, Any]:
    """按标的聚合多源新闻。返回 {items, sources, cached, errors}。"""
    sym = symbol.strip().upper()
    market = _market_of(sym)
    ttl = max(30, settings.news_ttl_sec)

    with _cache_lock:
        hit = _sym_cache.get(sym)
        if hit and not force and time.time() - hit[0] < ttl:
            items = hit[1]
            return {
                "symbol": sym, "market": market, "items": [i.as_dict() for i in items[:limit]],
                "cached": True, "errors": {},
            }

    errors: dict[str, str] = {}
    collected: list[NewsItem] = []
    seen: set[str] = set()

    for name in _PRIORITY.get(market, _PRIORITY["US"]):
        p = _providers.get(name)
        if p is None:
            continue
        try:
            items = p.fetch(sym, limit=limit)
            for it in items:
                if it.dedup_key in seen:
                    continue
                seen.add(it.dedup_key)
                it.symbol = it.symbol or sym
                it.market = market
                collected.append(it)
            _last_status["providers"][name] = {"ok": True, "items": len(items), "ts": time.time()}
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {exc}"
            _last_status["providers"][name] = {"ok": False, "error": errors[name], "ts": time.time()}

    # 网络全挂 → 回读数据库缓存（最近 72h），并如实标注 cached=True
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc)
    if collected:
        _upsert(collected)
        with _cache_lock:
            _sym_cache[sym] = (time.time(), collected)
        cached = False
    else:
        collected = _read_cache_db(sym, limit, since_hours=72)
        cached = bool(collected)

    _last_status["ts"] = time.time()
    collected.sort(key=lambda i: i.published_at or "", reverse=True)
    return {
        "symbol": sym, "market": market,
        "items": [i.as_dict() for i in collected[:limit]],
        "cached": cached, "errors": errors,
    }


def market_news(category: str = "general", limit: int = 20) -> dict[str, Any]:
    """市场级快讯（不绑定标的）。"""
    errors: dict[str, str] = {}
    out: list[NewsItem] = []
    seen: set[str] = set()
    for name in ("finnhub", "ibkr"):
        p = _providers.get(name)
        if p is None:
            continue
        try:
            for it in p.fetch(None, limit=limit):
                if it.dedup_key in seen:
                    continue
                seen.add(it.dedup_key)
                out.append(it)
            _last_status["providers"][name] = {"ok": True, "market_items": len(out), "ts": time.time()}
        except Exception as exc:  # noqa: BLE001
            errors[name] = f"{type(exc).__name__}: {exc}"
    out.sort(key=lambda i: i.published_at or "", reverse=True)
    return {
        "category": category,
        "items": [i.as_dict() for i in out[:limit]],
        "errors": errors,
    }


def headlines_for_symbols(symbols: list[str], limit_each: int = 3) -> dict[str, list[dict[str, Any]]]:
    """给 AI 分析师 / 提示引擎用：一批标的各取最近几条标题。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for s in symbols[: max(1, settings.news_scan_symbols)]:
        try:
            res = fetch_news(s, limit=limit_each)
            out[s.upper()] = res["items"]
        except Exception:  # noqa: BLE001
            out[s.upper()] = []
    return out


def status() -> dict[str, Any]:
    with _cache_lock:
        sym_cache_n = len(_sym_cache)
    from ..database import SessionLocal
    from ..models import NewsCache

    by_source: dict[str, int] = {}
    with SessionLocal() as s:
        rows = s.query(NewsCache.source, NewsCache.id).all()
        for src, _ in rows:
            by_source[src] = by_source.get(src, 0) + 1
    return {
        "providers": sorted(_providers),
        "configured": {
            "finnhub": bool(settings.finnhub_api_key),
            "yahoo-rss": True,
            "hkex": True,
            "ibkr": "ibkr" in _providers,
        },
        "providers_detail": _last_status.get("providers", {}),
        "memory_cache_symbols": sym_cache_n,
        "db_items_by_source": by_source,
    }


# ---------------- 落库与回读 ----------------
def _upsert(items: list[NewsItem]) -> int:
    """按 dedup_key 去重落库。

    教训：`merge()` 只按**主键**判断合并，不看唯一索引 —— 已存在同 dedup_key
    的行时它仍会走 INSERT，撞 UNIQUE 后 IntegrityError 还会把 session 污染
    （后续每条都抛 PendingRollbackError），最终整批回滚。所以必须：
      1. 先查 dedup_key，命中则只刷新 fetched_at；
      2. 任何异常立即 `s.rollback()` 给会话"解毒"，保证后面的条目不受牵连。
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from ..database import session_scope
    from ..models import NewsCache

    n = 0
    now = _dt.now(_tz.utc)
    with session_scope() as s:
        for it in items:
            try:
                existing = (
                    s.query(NewsCache)
                    .filter(NewsCache.dedup_key == it.dedup_key)
                    .first()
                )
                if existing is not None:
                    existing.fetched_at = now
                    continue
                s.add(NewsCache(
                    dedup_key=it.dedup_key,
                    source=it.source,
                    category=it.category,
                    symbol=it.symbol or "",
                    market=it.market,
                    headline=(it.headline or "")[:2000],
                    summary=(it.summary or "")[:4000],
                    url=(it.url or "")[:2000],
                    published_at=_parse_dt(it.published_at),
                    fetched_at=now,
                ))
                n += 1
            except Exception:  # noqa: BLE001
                s.rollback()
                continue
    return n


def _read_cache_db(symbol: str, limit: int, since_hours: int = 72) -> list[NewsItem]:
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    from ..database import SessionLocal
    from ..models import NewsCache

    cutoff = _dt.now(_tz.utc) - _td(hours=since_hours)
    out: list[NewsItem] = []
    with SessionLocal() as s:
        rows = (
            s.query(NewsCache)
            .filter(NewsCache.symbol == symbol.upper(), NewsCache.fetched_at >= cutoff)
            .order_by(NewsCache.published_at.desc().nullslast(), NewsCache.id.desc())
            .limit(limit)
            .all()
        )
        for r in rows:
            out.append(NewsItem(
                source=r.source, headline=r.headline, url=r.url, summary=r.summary,
                symbol=r.symbol, market=r.market, category=r.category,
                published_at=r.published_at.isoformat() if r.published_at else "",
            ))
    return out


def _parse_dt(s: str):
    from datetime import datetime as _dt

    if not s:
        return None
    try:
        return _dt.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def clear_memory_cache() -> None:
    with _cache_lock:
        _sym_cache.clear()
