"""AI 情报中心 API · 事件 / 建议 / 批次报告 / 验证 / 时间线 / 行情。

从 `api/intel.py` 拆出（铁律 9，2026-09-30）。全部走平台标准 JWT（CurrentUser）。

本 router **不写 prefix** —— 父 router（`api/intel.py`）已是 `/intel`。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from sqlalchemy import case

from .. import intel
from ..database import session_scope
from ..models import IntelAnalysis, IntelCompany, IntelEvent, IntelRun
from .deps import CurrentUser
from .intel_common import _scored_rows

router = APIRouter(tags=["AI 情报中心 · 事件与建议"])

@router.get("/events")
def list_events(  # noqa: ARG001
    user: CurrentUser,
    symbol: str = "",
    limit: int = 100,
    min_impact: int = 0,
    since_days: int = 0,
    sentiment: str = "",
    category: str = "",
    stage: str = "",
    media: str = "",
    sort: str = "created",
) -> dict:
    """事件列表。

    `sort`：
      · created（默认，兼容旧行为）—— 按入库时间倒序
      · importance —— 按确定性重要度倒序（页面「重点优先」用这个）
      · occurred —— 按事件发生日倒序（日期未知排最后）
    `since_days` > 0 时只取近 N 天（按 occurred_on，日期未知的按入库时间兜底）。
    `media`：`""` 全部 / `"exclude"` 仅公司自身事件 / `"only"` 仅媒体评论。
    返回体额外带 `importance` / `tier` / `stage` / `stage_cn` / `commentary` —— 旧版不返回
    stage，导致「已敲定 / 在谈 / 传闻」的前瞻管道能力在页面上完全看不见。
    """
    limit = max(1, min(500, limit))
    today = dt.date.today()
    # `commentary` 不是 DB 列（由 intel_classify 现算），只能在 Python 侧过滤 ——
    # 因此启用该筛选时必须**多取一批**，否则过滤后凑不满 limit 条。
    media_on = media in ("exclude", "only")
    with session_scope() as db:
        q = db.query(IntelEvent)
        if symbol:
            q = q.filter(IntelEvent.symbol == symbol.strip().upper())
        if min_impact > 0:
            q = q.filter(IntelEvent.impact >= max(1, min(5, min_impact)))
        if sentiment in ("positive", "negative", "neutral"):
            q = q.filter(IntelEvent.sentiment == sentiment)
        if category:
            q = q.filter(IntelEvent.category == category.strip())
        if stage in ("confirmed", "negotiating", "rumor"):
            q = q.filter(IntelEvent.stage == stage)
        if since_days > 0:
            cutoff = (today - dt.timedelta(days=max(1, min(400, since_days)))).isoformat()
            q = q.filter((IntelEvent.occurred_on >= cutoff) | (IntelEvent.occurred_on == ""))
        if sort == "occurred":
            q = q.order_by(
                case((IntelEvent.occurred_on != "", 0), else_=1),
                IntelEvent.occurred_on.desc(),
                IntelEvent.impact.desc(),
                IntelEvent.id.desc(),
            )
        elif sort == "importance":
            # 重要度是 Python 侧纯函数，无法在 SQL 排序 —— 多取一批再截断，
            # 保证「重点优先」拿到的是全局最重要的，而不是先按时间截断后的局部最优。
            q = q.order_by(
                case((IntelEvent.occurred_on != "", 0), else_=1),
                IntelEvent.occurred_on.desc(),
                IntelEvent.impact.desc(),
                IntelEvent.id.desc(),
            )
            rows = q.limit(min(1500, limit * (12 if media_on else 6))).all()
            return {"items": _scored_rows(rows, limit, today, media=media, by_importance=True)}
        else:
            q = q.order_by(IntelEvent.created_at.desc(), IntelEvent.id.desc())
        rows = q.limit(min(1500, limit * (4 if media_on else 1))).all()
    return {"items": _scored_rows(rows, limit, today, media=media)}

@router.delete("/events/{eid}")
def delete_event(eid: int, user: CurrentUser) -> dict:  # noqa: ARG001
    with session_scope() as db:
        row = db.get(IntelEvent, eid)
        if not row:
            raise HTTPException(404, "事件不存在")
        db.delete(row)
    return {"ok": True}

@router.get("/analyses")
def list_analyses(user: CurrentUser, symbol: str = "", limit: int = 50) -> dict:  # noqa: ARG001
    limit = max(1, min(200, limit))
    with session_scope() as db:
        q = db.query(IntelAnalysis).order_by(IntelAnalysis.created_at.desc())
        if symbol:
            q = q.filter(IntelAnalysis.symbol == symbol.strip().upper())
        rows = q.limit(limit).all()
    return {"items": [intel._analysis_row(a) for a in rows]}

@router.post("/analyze/{symbol}")
def analyze_now(symbol: str, user: CurrentUser) -> dict:  # noqa: ARG001
    """手动触发一次分析（LLM 优先 / 本地兜底），不依赖监控是否开启。"""
    symbol = symbol.strip().upper()
    with session_scope() as db:
        if not db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first():
            raise HTTPException(404, "该公司不在观察列表中，请先添加")
        run = db.query(IntelRun).filter(IntelRun.status == "running").order_by(IntelRun.id.desc()).first()
        run_id = run.id if run else None
    row = intel.auto_analyze_symbol(symbol, run_id)
    if row is None:
        raise HTTPException(502, "分析失败：行情数据不可用或 LLM 异常，请稍后重试")
    return {"ok": True, "analysis": intel._analysis_row(row)}

@router.get("/runs")
def list_runs(user: CurrentUser, limit: int = 30) -> dict:  # noqa: ARG001
    limit = max(1, min(100, limit))
    with session_scope() as db:
        rows = db.query(IntelRun).order_by(IntelRun.id.desc()).limit(limit).all()
    return {"items": [intel._run_row(r) for r in rows]}

@router.get("/runs/{rid}/report")
def run_report(rid: int, user: CurrentUser) -> dict:  # noqa: ARG001
    from pathlib import Path

    with session_scope() as db:
        run = db.get(IntelRun, rid)
        if not run:
            raise HTTPException(404, "批次不存在")
        path = run.report_path
    if not path or not Path(path).exists():
        path = intel.write_report(rid)
        if not path:
            raise HTTPException(404, "批次不存在")
    text = Path(path).read_text(encoding="utf-8")
    return {"path": path, "markdown": text}

@router.get("/verify/stats")
def verify_stats(user: CurrentUser) -> dict:  # noqa: ARG001
    """按 Agent 聚合的建议验证统计（胜率 / 平均实际收益 / 置信度校准）。"""
    return intel.verify_stats()

@router.post("/verify/run")
def verify_run(user: CurrentUser) -> dict:  # noqa: ARG001
    """手动触发一次到期建议对账（满 7 天未验证的立即结算）。"""
    n = intel.verify_due_analyses(limit=50)
    return {"ok": True, "verified": n, "stats": intel.verify_stats()}

@router.get("/timeline/{symbol}")
def intel_timeline(symbol: str, user: CurrentUser, days: int = 180) -> dict:  # noqa: ARG001
    """公司时间线：过去 N 天事件（含已敲定/在谈/传闻管道）+ 最新 AI 建议 + 行情摘要。

    「财报是滞后指标」——用合同管道前瞻未来 3-6 个月经营状况。
    """
    return intel.timeline(symbol, days=max(30, min(400, int(days or 180))))

@router.get("/history/{symbol}")
def price_history(symbol: str, user: CurrentUser, days: int = 120) -> dict:  # noqa: ARG001
    """日线收盘序列（供事件时间线叠加价格曲线）。"""
    import datetime as _dt

    from ..data_provider import fetch_history

    symbol = symbol.strip().upper()
    days = max(7, min(400, int(days or 120)))
    start = (_dt.datetime.now() - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df, source = fetch_history(symbol, start=start, interval="1d")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"行情获取失败：{exc}") from exc
    if df is None or df.empty:
        return {"symbol": symbol, "source": source, "dates": [], "close": []}
    # 严格按请求区间裁剪（fetch_history 缓存/增量可能返回更早的数据）
    import pandas as _pd

    df = df[df.index >= _pd.to_datetime(start)]
    return {
        "symbol": symbol,
        "source": source,
        "count": len(df),
        "dates": [str(d)[:10] for d in df.index],
        "close": [round(float(x), 4) for x in df["close"]],
    }
