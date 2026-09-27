"""关注列表 API（含持仓一键关注）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .. import rankings as rankmod
from ..data_provider import get_quotes
from ..database import session_scope
from ..models import PositionSnapshot, WatchlistItem
from ..state import log as audit_log
from .deps import CurrentUser

router = APIRouter(prefix="/watchlist", tags=["关注列表"])


class WatchAdd(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    note: str = ""
    held: bool = False


def _normalize(symbol: str) -> str:
    try:
        from ..markets import symbols as mksym
        return mksym.parse(symbol).symbol
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"无法识别的标的：{symbol!r}（{exc}）")


@router.get("")
def list_watchlist(user: CurrentUser) -> dict:
    with session_scope() as s:
        rows = s.query(WatchlistItem).order_by(WatchlistItem.created_at.desc()).all()
        syms = [r.symbol for r in rows]
    quotes = {q.get("symbol"): q for q in get_quotes(syms)} if syms else {}
    # 中文名（腾讯批量行情，落库缓存；失败不影响主流程）
    try:
        from ..company import names_cn

        cn = names_cn(syms)
    except Exception:  # noqa: BLE001
        cn = {}
    items = []
    for r in rows:
        q = quotes.get(r.symbol, {})
        items.append({
            "symbol": r.symbol, "market": r.market, "note": r.note, "held": r.held,
            "name_cn": cn.get(r.symbol, ""),
            "price": q.get("price", 0.0), "change_pct": q.get("change_pct", 0.0),
            "quote_source": q.get("source", ""),
        })
    return {"items": items, "count": len(items)}


@router.post("")
def add_watch(payload: WatchAdd, user: CurrentUser) -> dict:
    sym = _normalize(payload.symbol)
    market = "HK" if sym.endswith(".HK") else "US"
    with session_scope() as s:
        exists = s.query(WatchlistItem).filter(WatchlistItem.symbol == sym).first()
        if exists:
            exists.note = payload.note or exists.note
            exists.held = exists.held or payload.held
            return {"ok": True, "symbol": sym, "already": True}
        s.add(WatchlistItem(symbol=sym, market=market, note=payload.note, held=payload.held))
    audit_log("watch_add", "INFO", f"关注 {sym}", actor=user.username)
    return {"ok": True, "symbol": sym, "already": False}


@router.delete("/{symbol}")
def remove_watch(symbol: str, user: CurrentUser) -> dict:
    with session_scope() as s:
        n = s.query(WatchlistItem).filter(WatchlistItem.symbol == symbol.upper()).delete()
    if not n:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该标的不在关注列表")
    return {"ok": True, "removed": symbol.upper()}


@router.post("/sync-positions")
def sync_positions(user: CurrentUser) -> dict:
    """把当前全部持仓一键加入关注（held=True）。"""
    with session_scope() as s:
        held = (
            s.query(PositionSnapshot.symbol, PositionSnapshot.quantity)
            .filter(PositionSnapshot.quantity > 0)
            .all()
        )
        added, kept = [], []
        for sym, _qty in held:
            sym = sym.upper()
            row = s.query(WatchlistItem).filter(WatchlistItem.symbol == sym).first()
            if row:
                row.held = True
                kept.append(sym)
                continue
            market = "HK" if sym.endswith(".HK") else "US"
            s.add(WatchlistItem(symbol=sym, market=market, held=True, note="来自持仓"))
            added.append(sym)
    return {"ok": True, "added": added, "kept": kept, "positions": len(kept) + len(added)}


# ---------------- 榜单联动：标记关注状态 ----------------
def annotate_watched(rows: list[dict]) -> list[dict]:
    with session_scope() as s:
        watched = {w.symbol for w in s.query(WatchlistItem).all()}
    for r in rows:
        r["watched"] = r.get("symbol") in watched
    return rows


@router.get("/snapshot-status")
def snapshot_status(user: CurrentUser) -> dict:
    """给榜单页显示数据新鲜度。"""
    data = rankmod.constituents()
    return {"updated": data.get("updated"), "count": data.get("count"), "source": data.get("source")}
