"""新闻 API。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import news as newsmodule
from ..config import settings
from .deps import CurrentUser

router = APIRouter(prefix="/news", tags=["新闻"])


@router.get("")
def get_news(
    user: CurrentUser,
    symbol: str = Query(..., min_length=1, max_length=32),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    return newsmodule.fetch_news(symbol, limit=limit)


@router.post("/refresh")
def refresh_news(
    user: CurrentUser,
    symbol: str = Query(..., min_length=1, max_length=32),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """强制绕过缓存抓取。"""
    return newsmodule.fetch_news(symbol, limit=limit, force=True)


@router.get("/market")
def get_market_news(user: CurrentUser, limit: int = Query(20, ge=1, le=50)) -> dict:
    return newsmodule.market_news(limit=limit)


@router.get("/status")
def news_status(user: CurrentUser) -> dict:
    st = newsmodule.status()
    st["ttl_sec"] = settings.news_ttl_sec
    return st
