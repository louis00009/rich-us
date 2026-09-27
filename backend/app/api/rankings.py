"""美股 Top 500 榜单 API。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import rankings as rankmod
from .deps import CurrentUser
from .watchlist import annotate_watched

router = APIRouter(prefix="/market/rankings", tags=["榜单"])


@router.get("")
def get_rankings(
    user: CurrentUser,
    sort: str = Query("change_pct", pattern="^(change_pct|volume|amount|price|symbol|market_cap)$"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=503),
    q: str = "",
    sector: str = "",
) -> dict:
    res = rankmod.rankings(sort=sort, direction=direction, limit=limit, q=q, sector=sector)
    res["rows"] = annotate_watched(res["rows"])   # name_cn / market_cap 已在 rankmod.rankings 注入
    return res


@router.post("/refresh-quotes")
def refresh_rankings(user: CurrentUser) -> dict:
    """触发后台强制刷新（立即返回，不阻塞 —— 由 stale-while-revalidate 接管）。"""
    rankmod.quotes(force=True)
    return {"ok": True, "refreshing": True}


@router.get("/profile")
def company_profile(
    user: CurrentUser,
    symbol: str = Query(..., min_length=1, max_length=32),
    force: bool = False,
) -> dict:
    """公司档案：英文名 / 行业 / 英文介绍（longBusinessSummary）/ 市值 / 官网。缓存 30 天。"""
    from ..company import get_profile

    return get_profile(symbol, force=force)
