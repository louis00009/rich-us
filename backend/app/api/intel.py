"""AI 情报中心 API（管理端）。

`/intel/*` 走平台标准 JWT（CurrentUser），供页面使用。

Bridge 端（`/intel/bridge/*`，走独立 `X-Intel-Token`，供外部 AI Agent 领任务）
已拆到 `api/intel_bridge.py`，在本文件末尾挂载 —— 对外 URL 与拆分前完全一致。

共享件（鉴权 / 请求体 / 归一化工具）在 `api/intel_common.py`。
本文件只做**参数校验与编排**：真正的业务逻辑在 `app/intel.py`、
`app/intel_activity.py`、`app/intel_digest.py`（铁律 9）。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from sqlalchemy import case

from .. import intel, intel_activity, intel_digest
from ..database import session_scope
from ..models import IntelAnalysis, IntelBridgeLog, IntelCompany, IntelEvent, IntelRun
from . import intel_bridge
from .deps import CurrentUser
from .intel_common import (
    AiScrapeReq,
    CompanyReq,
    CompanyUpdateReq,
    IntelSettingsReq,
    MonitorStartReq,
    _llm_configured,
    _norm_scrape_limit,
    _norm_scrape_symbols,
    _scored_rows,
    _SYMBOL_RE,
)

router = APIRouter(prefix="/intel", tags=["AI 情报中心"])


# ==================================================================
# 总览 / 设置 / 监控
# ==================================================================
@router.get("/overview")
def overview(user: CurrentUser) -> dict:  # noqa: ARG001
    intel.ensure_default_companies()
    st = intel.ensure_settings()
    with session_scope() as db:
        n_events = db.query(IntelEvent).count()
        n_analyses = db.query(IntelAnalysis).count()
        n_companies = db.query(IntelCompany).count()
        n_enabled = db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).count()
        companies = db.query(IntelCompany).order_by(IntelCompany.id).all()
        recent_events = db.query(IntelEvent).order_by(IntelEvent.created_at.desc()).limit(15).all()
        recent_analyses = db.query(IntelAnalysis).order_by(IntelAnalysis.created_at.desc()).limit(8).all()
        runs = db.query(IntelRun).order_by(IntelRun.id.desc()).limit(10).all()
        pending_list = intel.pending_tasks(db, st.interval_minutes)
        tasks_pending = len(pending_list)
        day_ago = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        logs = db.query(IntelBridgeLog).filter(IntelBridgeLog.ts >= day_ago).all()
        agents: dict[str, str] = {}
        for lg in logs:
            agents.setdefault(lg.agent, lg.ts.isoformat())
        # 每个 agent 保留最近一次活动
        for lg in logs:
            if agents.get(lg.agent, "") < lg.ts.isoformat():
                agents[lg.agent] = lg.ts.isoformat()
        # 总控需要的关键信息：上次批次摘要（含实查计数）+ 今日/近 24h 活动
        # 旧实现只暴露 running 批次且用 run 自报计数，实测运行中批次长期显示「事件 0」
        # —— 数字既缺又假。改为实查 + 补全已截止批次。
        last_run_row = intel_activity.last_run(db)
        last_run = intel_activity.run_summary(last_run_row, db)
        activity = intel_activity.activity_stats(db)
        digest_row = intel_digest.load_digest()
    return {
        "settings": {
            "monitor_enabled": bool(st.monitor_enabled),
            "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze),
            "ai_scrape": bool(st.ai_scrape),
            "bridge_token": st.bridge_token,
        },
        "llm": {"configured": _llm_configured()},
        "scheduler": intel.SCHEDULER.status(),
        "stats": {
            "events_total": n_events,
            "analyses_total": n_analyses,
            "companies_total": n_companies,
            "companies_enabled": n_enabled,
            "tasks_pending": tasks_pending,
            # 「指定标的」需要按标的显示「待抓取」并支持「全选待抓取」——
            # 待抓取的判定逻辑只在后端（interval*1.2），前端不得自行推算，故直接给出清单。
            "pending_symbols": [t["symbol"] for t in pending_list],
            "agents_24h": agents,
        },
        "last_run": last_run,
        "activity": activity,
        "digest": {
            "available": digest_row is not None,
            "digest_date": digest_row["digest_date"] if digest_row else None,
            "top_count": digest_row["top_count"] if digest_row else 0,
            "event_count": digest_row["event_count"] if digest_row else 0,
            "updated_at": digest_row["updated_at"] if digest_row else None,
            "has_llm_text": bool(digest_row and digest_row.get("llm_text")),
        },
        "companies": [
            {
                "id": c.id, "symbol": c.symbol, "name": c.name, "theme": c.theme,
                "focus": c.focus, "enabled": c.enabled,
                "last_scrape_at": c.last_scrape_at.isoformat() if c.last_scrape_at else None,
            }
            for c in companies
        ],
        "recent_events": [intel._event_row(e) for e in recent_events],
        "recent_analyses": [intel._analysis_row(a) for a in recent_analyses],
        "runs": [intel._run_row(r) for r in runs],
    }


@router.put("/settings")
def update_settings(payload: IntelSettingsReq, user: CurrentUser) -> dict:  # noqa: ARG001
    """预配置抓取周期 / 自动分析 / AI 抓取（不开监控也能改）。"""
    intel.save_settings(interval_minutes=payload.interval_minutes,
                        auto_analyze=payload.auto_analyze, ai_scrape=payload.ai_scrape)
    st = intel.ensure_settings()
    return {"ok": True, "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze), "ai_scrape": bool(st.ai_scrape)}


@router.post("/ai-scrape")
def ai_scrape_now(payload: AiScrapeReq, user: CurrentUser) -> dict:  # noqa: ARG001
    """内置 AI 立即抓取（后台任务版）：立即返回 job_id，前端轮询 GET /intel/job/{id}。

    旧实现是同步 HTTP：4 家公司要 2~6 分钟，前端 30s 超时报错、后端还在傻跑，
    占死工作线程且用户看不到任何进度 —— 违反「长任务走 jobs」铁律，故改造。
    symbols 为空时自动取「到期待抓取」的公司；**非空时该清单就是本轮批次**（不再按 limit
    截断）—— 前端「指定标的」用它实现「只跑我挑的这几家 / 只跑一家」。
    """
    from ..ai_analyst import ai_configured
    from ..engine import jobs

    if not ai_configured():
        raise HTTPException(400, "尚未配置 AI：请到「设置 → AI 分析」填写 base_url / api_key / model 后重试")

    picked = _norm_scrape_symbols(payload.symbols)

    def _fn(progress, cancel_event):  # noqa: ANN001
        results = intel.ai_scrape_companies(
            symbols=picked,
            limit=_norm_scrape_limit(payload.limit),
            with_analysis=bool(payload.with_analysis),
            model=str(payload.model or ""),
            progress_cb=progress, cancel_event=cancel_event,
        )
        total_events = sum(r.get("inserted", 0) for r in results)
        intel.bridge_log("builtin-ai", "ai_scrape",
                         f"symbols={len(results)} picked={len(picked)} "
                         f"events=+{total_events} model={payload.model or 'default'}")
        # 逐家失败明细单独汇总 —— 前端据此给出明确的失败提示，而不是笼统「完成」
        errors = [{"symbol": r.get("symbol"), "error": r["error"]}
                  for r in results if r.get("error")]
        return {"count": len(results), "events_inserted": total_events,
                "cancelled": cancel_event.is_set(), "errors": errors, "results": results}

    job_id = jobs.start("intel_scrape", _fn)
    return {"ok": True, "job_id": job_id, "model": payload.model or ""}


@router.get("/job/{job_id}")
def get_job(job_id: str, user: CurrentUser) -> dict:  # noqa: ARG001
    """查询后台抓取任务：running / done / error / cancelled + progress/total/note。"""
    from ..engine import jobs

    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"任务 {job_id} 不存在或已过期")
    return {"ok": True, **job}


@router.post("/job/{job_id}/cancel")
def cancel_job(job_id: str, user: CurrentUser) -> dict:  # noqa: ARG001
    """协作式取消：当前公司跑完即停，已完成的公司结果保留。"""
    from ..engine import jobs

    if not jobs.cancel(job_id):
        raise HTTPException(404, f"任务 {job_id} 不存在或已结束")
    return {"ok": True, "job_id": job_id, "message": "已请求取消，当前公司处理完后停止"}


@router.post("/monitor/start")
def monitor_start(payload: MonitorStartReq, user: CurrentUser) -> dict:  # noqa: ARG001
    intel.ensure_default_companies()
    if payload.ai_scrape is not None:
        intel.save_settings(ai_scrape=payload.ai_scrape)
    run_id = intel.SCHEDULER.start(payload.interval_minutes, payload.auto_analyze)
    return {"ok": True, "run_id": run_id, "status": intel.SCHEDULER.status()}


@router.post("/monitor/stop")
def monitor_stop(user: CurrentUser) -> dict:  # noqa: ARG001
    result = intel.SCHEDULER.stop()
    return {"ok": True, **result, "status": intel.SCHEDULER.status()}


# ==================================================================
# 观察标的
# ==================================================================
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


# ==================================================================
# 事件 / 建议
# ==================================================================
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


# ==================================================================
# 批次 / 报告
# ==================================================================
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


# ==================================================================
# Bridge 令牌 / 指南（管理端；Bridge 端点本身在 intel_bridge.py）
# ==================================================================
@router.post("/bridge-token/reset")
def reset_token(user: CurrentUser) -> dict:  # noqa: ARG001
    token = intel.reset_bridge_token()
    return {"ok": True, "bridge_token": token}


@router.get("/bridge/guide")
def bridge_guide(user: CurrentUser) -> dict:  # noqa: ARG001
    return intel.bridge_guide()


# ==================================================================
# 建议验证 / 时间线 / 行情
# ==================================================================
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


# Bridge 端（/intel/bridge/*）：挂在最后，保持与拆分前一致的注册顺序。
router.include_router(intel_bridge.router)
