"""AI 情报中心 API · 抓取任务（从 `api/intel.py` 拆出，铁律 9，2026-09-30）。

覆盖：内置 AI 立即抓取（后台 job）、job 查询/取消、入库台账、近 N 分钟聚合、
失败重试、熔断器状态。全部走平台标准 JWT（CurrentUser）。

本 router **不写 prefix** —— 父 router（`api/intel.py`）已是 `/intel`。
"""
from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, HTTPException

from .. import intel
from ..database import session_scope
from ..models import IntelBridgeLog
from .deps import CurrentUser
from .intel_common import (
    AiScrapeReq,
    RetryRequest,
    _norm_scrape_limit,
    _norm_scrape_symbols,
)

router = APIRouter(tags=["AI 情报中心 · 抓取"])

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

@router.get("/scrape-log")
def scrape_log(user: CurrentUser, limit: int = 40) -> dict:  # noqa: ARG001
    """入库台账：每一条「数据进了库」的记录，可审计。

    覆盖三条入库路径：内置 AI 抓取（scrape / ai_scrape）、外部 Agent 提交事件
    （submit_events）与提交建议（submit_analysis）。失败/空抓也如实记录。
    """
    limit = max(1, min(100, int(limit or 40)))
    with session_scope() as db:
        rows = (
            db.query(IntelBridgeLog)
            .filter(IntelBridgeLog.action.in_(("scrape", "ai_scrape", "submit_events", "submit_analysis")))
            .order_by(IntelBridgeLog.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "items": [
                {"ts": r.ts.isoformat(), "agent": r.agent, "action": r.action,
                 "detail": r.detail, "ok": bool(r.ok)}
                for r in rows
            ]
        }

@router.get("/ingest-stats")
def ingest_stats(user: CurrentUser, since_minutes: int = 60) -> dict:  # noqa: ARG001
    """近 N 分钟的入库台账聚合（09-30 加）—— 给前端「失败 X 家 · 一键重试」按钮用。

    返回：
      · total / succeeded / failed（按业务结果计数）
      · failed_symbols：失败的去重 symbol 列表（用于一键重试）
      · last_error_by_symbol：每家最近的错误摘要（截断 80 字符）
    """
    from datetime import timedelta as _td
    from ..models import IntelBridgeLog
    since_minutes = max(1, min(720, int(since_minutes or 60)))
    cutoff = dt.datetime.utcnow() - _td(minutes=since_minutes)
    with session_scope() as db:
        rows = (
            db.query(IntelBridgeLog)
            .filter(IntelBridgeLog.action == "scrape", IntelBridgeLog.ts >= cutoff)
            .order_by(IntelBridgeLog.id.desc())
            .all()
        )
    total = len(rows)
    succeeded = sum(1 for r in rows if r.ok)
    failed = total - succeeded
    fail_syms: dict[str, str] = {}
    for r in rows:
        if r.ok:
            continue
        # detail 形如 "TSM · ... · 失败：LLM ... 503 Service Unavailable"
        m = re.match(r"^([A-Z][A-Z0-9.]{0,15})", r.detail or "")
        if not m:
            continue
        sym = m.group(1)
        # 取最近一条错误（即同一 symbol 多次失败只取最后一次）
        if sym not in fail_syms:
            err_m = re.search(r"失败：(.+)$", r.detail or "")
            fail_syms[sym] = (err_m.group(1)[:80] if err_m else "unknown")
    return {
        "since_minutes": since_minutes,
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "failed_symbols": sorted(fail_syms.keys()),
        "last_error_by_symbol": fail_syms,
    }

@router.post("/scrape/retry")
def scrape_retry(payload: RetryRequest, user: CurrentUser) -> dict:  # noqa: ARG001
    """重试近 N 分钟内失败的家（09-30 加）—— 复用 raw_news 缓存直接打标。

    body:
      · symbols: 指定重试的清单；空 = 自动取「近 since_minutes 内失败的 symbol」
      · since_minutes: 默认 60（与 ingest-stats 对齐）
      · force: true 强制重新抓新闻（覆盖 raw_news 缓存）

    设计动机：之前失败 = 新闻真丢；现在 raw_news 已暂存，重试时不重新 fetch_news，
    直接拿缓存调 LLM（按 fallback 链）打标入库，省一次抓取 + 一次网关注入。
    """
    from ..engine import jobs
    from ..intel.scrape import ai_harvest_events

    since = max(1, min(720, int(payload.since_minutes or 60)))
    # 1. 决定本轮要重试的 symbol
    if payload.symbols:
        picked = _norm_scrape_symbols(payload.symbols)
    else:
        # 自动取失败的 symbol
        from datetime import timedelta as _td
        from ..models import IntelBridgeLog
        cutoff = dt.datetime.utcnow() - _td(minutes=since)
        with session_scope() as db:
            rows = (
                db.query(IntelBridgeLog)
                .filter(IntelBridgeLog.action == "scrape",
                        IntelBridgeLog.ok == False, IntelBridgeLog.ts >= cutoff)
                .order_by(IntelBridgeLog.id.desc())
                .all()
            )
        syms = []
        seen = set()
        for r in rows:
            m = re.match(r"^([A-Z][A-Z0-9.]{0,15})", r.detail or "")
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                syms.append(m.group(1))
        picked = syms
    if not picked:
        return {"ok": True, "job_id": None, "symbols": [], "message": "无失败家可重试"}

    # 2. 后台跑（沿用 ai-scrape 同样的 jobs 模式），模型链仍走 fallback。
    # 09-30：熔断器开启时**不接任务**，直接返 503 —— 用户应看到熔断状态而非空跑。
    from ..intel.scrape import _breaker_open, breaker_status as _bs
    if _breaker_open():
        st = _bs()
        raise HTTPException(503, f"熔断冷却中，剩余 {st['cooldown_remaining_s']}s；前端顶栏「熔断」按钮可手动恢复")

    def _fn(progress, cancel_event):  # noqa: ANN001
        results = []
        for i, sym in enumerate(picked):
            if cancel_event.is_set():
                break
            progress(i, len(picked), f"重试 {sym}（复用 raw_news → fallback 打标）…")
            r = ai_harvest_events(sym, run_id=None, model_name=payload.model or "")
            results.append(r)
        # 整批兜底刷新（即便 0 inserted 也算本批结束）
        from .. import intel_digest
        intel_digest.refresh_async("retry")
        progress(len(picked), len(picked), "重试完成")
        return results

    job = jobs.submit("intel_scrape_retry", _fn)
    return {"ok": True, "job_id": job.id, "symbols": picked}

@router.get("/breaker")
def breaker_status(user: CurrentUser) -> dict:  # noqa: ARG001
    """熔断器状态（09-30 加）—— 给 MonitorBar 顶部条显示「熔断中：剩余 12 分」用。"""
    from ..intel.scrape import breaker_status as _bs
    return _bs()
