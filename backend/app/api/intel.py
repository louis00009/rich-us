"""AI 情报中心 API（管理端）· 总览 / 设置 / 监控 / 令牌。

`/intel/*` 走平台标准 JWT（CurrentUser），供页面使用。

拆分（铁律 9，2026-09-30 第二次拆）：原 687 行超 600 软上限，按业务域拆出
  · `api/intel_scrape.py`    —— 抓取任务（ai-scrape / job / 台账 / 重试 / 熔断）
  · `api/intel_companies.py` —— 观察标的 CRUD / 关注列表同步
  · `api/intel_events.py`    —— 事件 / 建议 / 批次报告 / 验证 / 时间线 / 行情
  · `api/intel_bridge.py`    —— Bridge 端（X-Intel-Token，外部 Agent 领任务）
全部在本文件末尾 `include_router`，对外 URL 与拆分前**完全一致**。

⚠️ 子 router 的 `prefix` 只能写相对部分（本文件父 prefix 是 `/intel`）：
   子 router 不写 prefix、路径写 `/companies` → 最终 `/api/intel/companies`。
   写成 `prefix="/intel"` 会叠加成 `/api/intel/intel/...`（实测踩过）。

共享件（鉴权 / 请求体 / 归一化工具）在 `api/intel_common.py`。
真正的业务逻辑在 `app/intel/`、`app/intel_activity.py`、`app/intel_digest.py`。
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from .. import intel, intel_activity, intel_digest
from ..database import session_scope
from ..models import IntelAnalysis, IntelBridgeLog, IntelCompany, IntelEvent, IntelRun
from . import intel_bridge, intel_companies, intel_events, intel_scrape
from .deps import CurrentUser
from .intel_common import IntelSettingsReq, MonitorStartReq, _llm_configured

router = APIRouter(prefix="/intel", tags=["AI 情报中心"])

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
            "pinned_symbols": intel.pinned_list(st),
            "surge_pct": float(st.surge_pct or 3.0),
            "bridge_token": st.bridge_token,
            # 模型 fallback 链（09-30 加）：页面上能改顺序
            "llm_fallback_chain": intel.chain_list(st),
        },
        "llm": {"configured": _llm_configured()},
        # 09-30：熔断器状态（连续失败保护）—— 前端 MonitorBar 顶栏用
        "breaker": intel.breaker_status() if hasattr(intel, "breaker_status") else {},
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
    """预配置抓取周期 / 自动分析 / AI 抓取 / 重点标的 / 异动阈值（不开监控也能改）。"""
    intel.save_settings(interval_minutes=payload.interval_minutes,
                        auto_analyze=payload.auto_analyze, ai_scrape=payload.ai_scrape,
                        pinned_symbols=payload.pinned_symbols, surge_pct=payload.surge_pct,
                        llm_fallback_chain=payload.llm_fallback_chain)
    st = intel.ensure_settings()
    return {"ok": True, "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze), "ai_scrape": bool(st.ai_scrape),
            "pinned_symbols": intel.pinned_list(st),
            "surge_pct": float(st.surge_pct or 3.0),
            # 模型 fallback 链（09-30 加）：页面上能看到当前顺序 + 拖拽改顺序
            "llm_fallback_chain": intel.chain_list(st)}

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

@router.get("/live")
def live_status(user: CurrentUser) -> dict:  # noqa: ARG001
    """实时运行状态（前端 2~3 秒轮询）。

    只读内存 + 两条本地小查询，不碰任何网络 —— 高频轮询安全：
      · live.phase: idle | scrape | scrape_done | analyze | skipped
      · live.note:  人类可读的当前动作（含正在抓取/分析的公司名）
      · live.progress/total: 本轮进度（家）
    """
    cur = intel.SCHEDULER.current_run()
    from ..ai_analyst import ai_configured

    return {
        "ok": True,
        "scheduler_alive": intel.SCHEDULER.alive,
        "monitor_enabled": bool(intel.ensure_settings().monitor_enabled),
        "interval_minutes": intel.ensure_settings().interval_minutes,
        "current_run": (
            {"id": cur.id, "started_at": cur.started_at.isoformat(),
             "tick_count": cur.tick_count or 0,
             "last_tick_at": cur.last_tick_at.isoformat() if cur.last_tick_at else None}
            if cur else None
        ),
        "live": dict(intel.SCHEDULER._live),  # noqa: SLF001 —— 同模块管理端接口，读内存状态
        "llm_configured": ai_configured(),
    }

@router.post("/bridge-token/reset")
def reset_token(user: CurrentUser) -> dict:  # noqa: ARG001
    token = intel.reset_bridge_token()
    return {"ok": True, "bridge_token": token}

@router.get("/bridge/guide")
def bridge_guide(user: CurrentUser) -> dict:  # noqa: ARG001
    return intel.bridge_guide()

# 子 router 挂在最后，保持与拆分前一致的注册顺序（URL 完全不变）。
router.include_router(intel_scrape.router)
router.include_router(intel_companies.router)
router.include_router(intel_events.router)
router.include_router(intel_bridge.router)
