"""AI 每日必读 API（/intel/digest）
=================================
与 `api/intel.py` 同前缀但独立成文件 —— `api/intel.py` 已近 600 行软上限，
再塞进来会直接超限（项目铁律：后端文件软上限 600）。

端点：
  · GET  /intel/digest          取当日必读清单（不存在则现算并落库）
  · POST /intel/digest/rebuild  强制重算并落库
  · POST /intel/digest/record   把前端拿到的 AI 解读**记录**到当日清单行
  · GET  /intel/digest/history  最近 N 天的清单留痕（「AI 主动分析并记录」的凭证）

设计边界（重要）
----------------
· 清单本身（重要度、入选理由、买入时机）全部由**确定性规则**产生，不调 LLM，
  因此调度器每轮都能自动生成 —— 这是「AI 主动分析并记录」的确定性部分。
· AI 解读由**前端通过统一入口 `aiAssist('intel_digest', …)` 调用**
  （项目铁律：全平台 AI 一律走 AI Task Hub，不另开 AI 端点），
  拿到结果后再调本文件的 `record` 落库。这样既满足「统一入口」，
  也满足用户要求的「AI 主动分析并且记录」。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import intel, intel_digest
from ..database import session_scope
from ..models import IntelDigest
from .deps import CurrentUser

router = APIRouter(prefix="/intel", tags=["AI 情报中心"])

_MAX_DAYS = 14


class RebuildReq(BaseModel):
    days: int = intel_digest.DIGEST_DAYS
    scope: str = ""          # 空 = 全市场；填标的代码则只算该公司


class RecordReq(BaseModel):
    """前端 aiAssist('intel_digest', …) 的结果回传落库。"""
    text: str
    engine: str = "llm"
    llm_error: str = ""


def _norm_scope(scope: str | None) -> str:
    s = (scope or "").strip().upper()
    if not s:
        return "all"
    if not s.replace(".", "").replace("-", "").isalnum() or len(s) > 16:
        raise HTTPException(400, "scope 需为标的代码或留空")
    return s


def _shape(row: dict[str, Any] | None, *, days: int) -> dict[str, Any]:
    """把落库行整形为前端结构；没有落库行时返回空壳（不静默编造内容）。"""
    if row is None:
        return {
            "available": False, "digest_date": None, "scope": "all", "days": days,
            "totals": {}, "top": [], "by_symbol": [], "watch": [], "notes": [],
            "llm_text": "", "llm_engine": "", "generated_by": "", "updated_at": None,
        }
    payload = row.get("payload") or {}
    return {
        "available": True,
        "digest_date": row.get("digest_date"),
        "scope": row.get("scope") or "all",
        "days": payload.get("days", days),
        "totals": payload.get("totals") or {},
        "top": payload.get("top") or [],
        "by_symbol": payload.get("by_symbol") or [],
        "watch": payload.get("watch") or [],
        "notes": payload.get("notes") or [],
        "llm_text": row.get("llm_text") or "",
        "llm_engine": row.get("llm_engine") or "",
        "generated_by": row.get("generated_by") or "",
        "updated_at": row.get("updated_at"),
    }


@router.get("/digest")
def get_digest(user: CurrentUser, scope: str = "", days: int = 0) -> dict:  # noqa: ARG001
    """取当日必读清单。没有落库记录时**现算并落库**（首次约 5~8 秒：要给候选标的读量化快照）。

    实时性：落库行落后于最新入库事件时同步重算（30s 节流，节流期内转后台刷新）——
    保证「抓取/监控的数据一到，打开每日必读就能看到」，而不是等监控下一轮。
    """
    sc = _norm_scope(scope)
    d = max(1, min(_MAX_DAYS, int(days or intel_digest.DIGEST_DAYS)))
    row = intel_digest.load_digest(scope=sc) if sc == "all" else None
    if row is None:
        payload = intel_digest.build_digest(days=d, symbol=None if sc == "all" else sc)
        intel_digest.save_digest(payload, generated_by="api")
        row = intel_digest.load_digest(scope=payload["scope"])
    else:
        row = intel_digest.refresh_if_stale(row)
    out = _shape(row, days=d)
    # 心跳：最新一条事件的入库时刻 —— 让「数据到了、必读同步了」可见可查，
    # 否则清单内容因去重稳定时用户会误以为「没在更新」。
    try:
        _ne = intel_digest.newest_event_at()
        out["last_event_at"] = _ne.isoformat() if _ne else None
    except Exception:  # noqa: BLE001
        out["last_event_at"] = None
    # 附带当前是否已配置 AI —— 前端据此决定「AI 深度解读」按钮是否可点
    from ..ai_analyst import ai_configured

    out["llm_configured"] = bool(ai_configured())
    return out


@router.post("/digest/rebuild")
def rebuild_digest(payload: RebuildReq, user: CurrentUser) -> dict:  # noqa: ARG001
    """强制重算清单（纯规则，不调 LLM），并覆盖当日留痕。"""
    sc = _norm_scope(payload.scope)
    d = max(1, min(_MAX_DAYS, int(payload.days or intel_digest.DIGEST_DAYS)))
    built = intel_digest.build_digest(days=d, symbol=None if sc == "all" else sc)
    intel_digest.save_digest(built, generated_by="manual")
    row = intel_digest.load_digest(scope=built["scope"])
    return {"ok": True, **_shape(row, days=d)}


@router.post("/digest/record")
def record_digest(payload: RecordReq, user: CurrentUser) -> dict:  # noqa: ARG001
    """把前端 `aiAssist('intel_digest', …)` 拿到的解读**记录**到当日清单行。

    为什么不在后端直接调 LLM：项目铁律「全平台 AI 一律走 AI Task Hub 统一入口」，
    前端必须通过 `aiAssist()` 调用（守卫 `render-check.mjs` 会扫源码校验任务名）。
    本端点只负责落库，不发起任何 LLM 请求。
    """
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, "解读内容为空，不写入记录")
    row = intel_digest.load_digest()
    if row is None:
        built = intel_digest.build_digest()
        intel_digest.save_digest(built, generated_by="api")
        row = intel_digest.load_digest()
    digest = row.get("payload") or {}
    intel_digest.save_digest(digest, llm_text=text, llm_engine=payload.engine or "llm",
                             generated_by="manual")
    intel.bridge_log("builtin-ai", "digest_record",
                     f"engine={payload.engine} len={len(text)} err={payload.llm_error[:120]}")
    fresh = intel_digest.load_digest()
    return {"ok": True, **_shape(fresh, days=digest.get("days") or intel_digest.DIGEST_DAYS)}


@router.get("/digest/history")
def digest_history(user: CurrentUser, limit: int = 10) -> dict:  # noqa: ARG001
    """最近 N 天的必读清单留痕（证明「AI 主动分析并记录」确实落盘了）。"""
    limit = max(1, min(60, int(limit or 10)))
    with session_scope() as db:
        rows = (
            db.query(IntelDigest)
            .order_by(IntelDigest.digest_date.desc(), IntelDigest.id.desc())
            .limit(limit).all()
        )
        return {
            "items": [
                {
                    "id": r.id, "digest_date": r.digest_date, "scope": r.scope,
                    "event_count": r.event_count, "top_count": r.top_count,
                    "generated_by": r.generated_by,
                    "has_llm_text": bool(r.llm_text), "llm_engine": r.llm_engine or "",
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        }
