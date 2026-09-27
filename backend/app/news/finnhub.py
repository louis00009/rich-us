"""Finnhub 新闻 provider（公司新闻 + 市场快讯）。

免费档：60 次/分钟。我们做了 TTL 内存缓存，正常使用远低于限流。
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import requests

from ..config import settings
from .base import NewsItem, register_news_provider

BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 10.0


def _get(path: str, params: dict[str, Any]) -> Any:
    params = dict(params)
    params["token"] = settings.finnhub_api_key
    r = requests.get(f"{BASE}{path}", params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


class FinnhubNews:
    name = "finnhub"

    def fetch(self, symbol: str | None, limit: int = 20) -> list[NewsItem]:
        if not settings.finnhub_api_key:
            return []
        if symbol:
            sym = symbol.upper()
            if sym.endswith(".HK"):
                return []       # 免费档不含港股公司新闻（403），交给 hkex provider
            return self._company(sym, limit)
        return self._market(limit)

    def _company(self, symbol: str, limit: int) -> list[NewsItem]:
        to = _dt.date.today()
        frm = to - _dt.timedelta(days=14)
        data = _get("/company-news", {"symbol": symbol, "from": frm.isoformat(), "to": to.isoformat()})
        if not isinstance(data, list):
            return []
        out: list[NewsItem] = []
        for d in data[: limit * 2]:
            out.append(NewsItem(
                source="finnhub",
                headline=str(d.get("headline") or "")[:500],
                url=str(d.get("url") or ""),
                summary=str(d.get("summary") or "")[:1000],
                symbol=symbol,
                market="US",
                category="company",
                published_at=_epoch_iso(d.get("datetime")),
                extra={"source_site": d.get("source") or ""},
            ))
        return out

    def _market(self, limit: int) -> list[NewsItem]:
        data = _get("/news", {"category": "general"})
        if not isinstance(data, list):
            return []
        out: list[NewsItem] = []
        for d in data[: limit * 2]:
            out.append(NewsItem(
                source="finnhub",
                headline=str(d.get("headline") or "")[:500],
                url=str(d.get("url") or ""),
                summary=str(d.get("summary") or "")[:1000],
                symbol="",
                market="US",
                category="market",
                published_at=_epoch_iso(d.get("datetime")),
            ))
        return out


def _epoch_iso(v: Any) -> str:
    try:
        return _dt.datetime.fromtimestamp(int(v), tz=_dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def register() -> None:
    register_news_provider(FinnhubNews())
