"""Yahoo Finance RSS 新闻 provider（免 key 兜底）。

美股与港股符号都支持（0700.HK 同样可用）。
"""
from __future__ import annotations

import datetime as _dt
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from .base import NewsItem, register_news_provider

_TIMEOUT = 8.0
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return _TAG_RE.sub("", s or "").strip()


class YahooRssNews:
    name = "yahoo-rss"

    def fetch(self, symbol: str | None, limit: int = 20) -> list[NewsItem]:
        if not symbol:
            symbol = "SPY"          # 无标的时用大盘代理
        sym = symbol.upper()
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items: list[NewsItem] = []
        for item in root.iter("item"):
            title = _clean(item.findtext("title") or "")
            if not title:
                continue
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc = _clean(item.findtext("description") or "")
            items.append(NewsItem(
                source="yahoo-rss",
                headline=title[:500],
                url=link,
                summary=desc[:800],
                symbol=sym,
                category="company",
                published_at=_rfc822_iso(pub),
            ))
            if len(items) >= limit:
                break
        return items


def _rfc822_iso(s: str) -> str:
    if not s:
        return ""
    try:
        return parsedate_to_datetime(s).astimezone(_dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def register() -> None:
    register_news_provider(YahooRssNews())
