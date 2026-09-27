"""新闻聚合包：provider 注册 + 统一服务层。"""
from __future__ import annotations

from .base import (
    NewsItem,
    available_news_providers,
    clear_memory_cache,
    fetch_news,
    get_news_provider,
    headlines_for_symbols,
    market_news,
    register_news_provider,
    status,
)
from . import finnhub, hkex, ibkr_news, yahoo_rss


def register_all() -> None:
    """按可用性注册全部 provider（幂等）。"""
    finnhub.register()
    yahoo_rss.register()
    hkex.register()
    ibkr_news.register()


register_all()

__all__ = [
    "NewsItem", "register_news_provider", "get_news_provider", "available_news_providers",
    "fetch_news", "market_news", "headlines_for_symbols", "status", "clear_memory_cache",
    "register_all",
]
