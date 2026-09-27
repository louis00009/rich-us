"""智能提示 API。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .. import alerts as alertmod
from .deps import CurrentUser

router = APIRouter(prefix="/alerts", tags=["智能提示"])


class MarkRead(BaseModel):
    ids: list[int] = []


@router.get("")
def list_alerts(
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
) -> dict:
    return {"items": alertmod.list_events(limit=limit, unread_only=unread_only),
            "unread": alertmod.unread_count()}


@router.get("/unread-count")
def alerts_unread(user: CurrentUser) -> dict:
    return {"unread": alertmod.unread_count()}


@router.post("/scan")
def alerts_scan(user: CurrentUser, force: bool = False) -> dict:
    """扫描关注 + 持仓标的（技术信号 + 新闻关键词），有冷却。"""
    return alertmod.scan(force=force)


@router.post("/read")
def alerts_read(payload: MarkRead, user: CurrentUser) -> dict:
    n = alertmod.mark_read(payload.ids or None)
    return {"ok": True, "marked": n, "unread": alertmod.unread_count()}
