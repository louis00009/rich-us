"""AI 情报中心 API · 观察标的（从 `api/intel.py` 拆出，铁律 9，2026-09-30）。

覆盖：观察标的 CRUD、一键从行情关注列表同步。全部走平台标准 JWT（CurrentUser）。

本 router **不写 prefix** —— 父 router（`api/intel.py`）已是 `/intel`。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..database import session_scope
from ..models import IntelCompany
from .deps import CurrentUser
from .intel_common import CompanyReq, CompanyUpdateReq, _SYMBOL_RE

router = APIRouter(tags=["AI 情报中心 · 观察标的"])

@router.get("/companies")
def list_companies(user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        rows = db.query(IntelCompany).order_by(IntelCompany.id).all()
        return {"items": [
            {"id": c.id, "symbol": c.symbol, "name": c.name, "theme": c.theme, "focus": c.focus,
             "enabled": c.enabled,
             "last_scrape_at": c.last_scrape_at.isoformat() if c.last_scrape_at else None}
            for c in rows
        ]}

@router.post("/companies")
def add_company(payload: CompanyReq, user: CurrentUser) -> dict:  # noqa: ARG001
    symbol = payload.symbol.strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(400, "标的代码格式不合法（示例：NVDA / ASML / BRK.B）")
    with session_scope() as db:
        row = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()
        if row:
            row.enabled = True
            if payload.name:
                row.name = payload.name.strip()[:120]
            if payload.theme:
                row.theme = payload.theme.strip()[:120]
            if payload.focus:
                row.focus = payload.focus.strip()[:500]
            cid = row.id
        else:
            row = IntelCompany(symbol=symbol, name=payload.name.strip()[:120],
                               theme=payload.theme.strip()[:120], focus=payload.focus.strip()[:500],
                               enabled=True)
            db.add(row)
            db.flush()
            cid = row.id
    return {"ok": True, "id": cid, "symbol": symbol}

@router.post("/companies/sync-watchlist")
def sync_companies_from_watchlist(user: CurrentUser) -> dict:  # noqa: ARG001
    """一键把平台关注列表（watchlist）同步进观察标的：已存在的跳过，其余全部启用。

    保持「行情收藏 ↔ AI 观察标的」同一份名单；Intel 侧新增的公司 theme/focus
    先用占位，可随时在列表里编辑。
    """
    from ..models import WatchlistItem

    added: list[str] = []
    skipped = 0
    with session_scope() as db:
        known = {c.symbol for c in db.query(IntelCompany).all()}
        for w in db.query(WatchlistItem).all():
            if w.symbol in known:
                skipped += 1
                continue
            db.add(IntelCompany(symbol=w.symbol, name=(w.note or w.symbol)[:120],
                                theme="关注列表同步", focus="", enabled=True))
            added.append(w.symbol)
    return {"ok": True, "added": added, "added_count": len(added), "skipped": skipped}

@router.put("/companies/{cid}")
def update_company(cid: int, payload: CompanyUpdateReq, user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        row = db.get(IntelCompany, cid)
        if not row:
            raise HTTPException(404, "公司不存在")
        if payload.name is not None:
            row.name = payload.name.strip()[:120]
        if payload.theme is not None:
            row.theme = payload.theme.strip()[:120]
        if payload.focus is not None:
            row.focus = payload.focus.strip()[:500]
        if payload.enabled is not None:
            row.enabled = bool(payload.enabled)
        return {"ok": True}

@router.delete("/companies/{cid}")
def delete_company(cid: int, user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        row = db.get(IntelCompany, cid)
        if not row:
            raise HTTPException(404, "公司不存在")
        db.delete(row)
    return {"ok": True}
