"""情报中心「总控」统计
======================
页面顶部的监控总控需要回答四个问题，而旧实现一个都答不上来：

  1. **上次什么时候跑的？** —— 旧逻辑只在「监控运行中」时渲染，监控一停整块消失。
     这里提供 `last_run`：最近一次批次（不论 running/finished/stopped）的完整摘要。
  2. **这批到底抓了多少条？** —— `IntelRun.events_found / analyses_done` 只在写入时
     带 run_id 才累加，实测运行中的批次长期显示 `事件 0 / 建议 0`（而库里明明有产出）。
     这里提供**三个口径**（见 `run_summary` 注释），前端展示按**运行窗口实查**的
     `events_in_window / analyses_in_window` —— 那才是「这批期间抓了多少条」的真实答案。
  3. **今天新增了多少？** —— 提供今日 / 近 24h 事件数、近 7 日每日分布。
  4. **抓取覆盖到哪了？** —— 上次抓取时间（所有标的的最大值）、近 24h 内被抓过的标的数。

放在独立模块而不是塞进 `intel.py`（已 1462 行、超硬上限）：新代码不再加重该文件。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from .models import IntelAnalysis, IntelCompany, IntelEvent, IntelRun

_AGENTS_MAX = 12


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite 存 naive UTC —— 与 aware 直接比较会 TypeError，统一补 tz。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def run_summary(run: IntelRun | None, db: Session) -> dict[str, Any] | None:
    """批次摘要：run 自报值 + 按 run_id 实查 + 按运行窗口实查。

    三个计数口径不同，别混：
      · `events_found / analyses_done` —— run 自报，只在写入带 run_id 时累加，
        **长期为 0**（实测运行中批次 events_found=0 而库里同期有产出），仅作对照；
      · `events_in_db / analyses_in_db` —— 按 run_id 实查，反映「归属本批次的产出」；
      · `events_in_window / analyses_in_window` —— 按 [started_at, ended_at/now] 实查，
        这才是「这批期间到底抓了多少条」的**权威答案**（外部 Agent 提交时可能
        没有 run_id，只按 run_id 查会严重低估）。
    """
    if run is None:
        return None
    started = _aware(run.started_at)
    ended = _aware(run.ended_at)
    now = dt.datetime.now(dt.timezone.utc)
    end = ended or now
    events_in_db = db.query(IntelEvent).filter(IntelEvent.run_id == run.id).count()
    analyses_in_db = db.query(IntelAnalysis).filter(IntelAnalysis.run_id == run.id).count()
    events_in_window = analyses_in_window = 0
    if started:
        events_in_window = db.query(IntelEvent).filter(
            IntelEvent.created_at >= started, IntelEvent.created_at <= end
        ).count()
        analyses_in_window = db.query(IntelAnalysis).filter(
            IntelAnalysis.created_at >= started, IntelAnalysis.created_at <= end
        ).count()
    try:
        import json

        agents = json.loads(run.agents_seen or "[]")
        agents = [str(a) for a in agents if a][:_AGENTS_MAX]
    except (ValueError, TypeError):
        agents = []
    return {
        "id": run.id,
        "status": run.status,
        "interval_minutes": run.interval_minutes,
        "auto_analyze": bool(run.auto_analyze),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        # 运行中为「至今」，已截止为「总时长」——单位秒，前端自行格式化
        "duration_seconds": max(0, int((end - started).total_seconds())) if started else None,
        "running": run.status == "running",
        "tick_count": run.tick_count or 0,
        "last_tick_at": run.last_tick_at.isoformat() if run.last_tick_at else None,
        # 权威口径：本批次运行窗口内实际入库的条数
        "events_in_window": events_in_window,
        "analyses_in_window": analyses_in_window,
        # 归属本批次（带 run_id）的产出
        "events_in_db": events_in_db,
        "analyses_in_db": analyses_in_db,
        # run 自报值（可能长期为 0，仅供对照，不作为展示口径）
        "events_found": run.events_found or 0,
        "analyses_done": run.analyses_done or 0,
        "agents_seen": agents,
        "note": run.note or "",
        "report_path": run.report_path or "",
    }


def activity_stats(db: Session, days: int = 7) -> dict[str, Any]:
    """今日 / 近 24h 事件量、近 N 日分布、抓取覆盖情况。"""
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    day_start = dt.datetime(today.year, today.month, today.day, tzinfo=dt.timezone.utc)
    day_ago = now - dt.timedelta(hours=24)

    today_events = (
        db.query(IntelEvent)
        .filter((IntelEvent.occurred_on == today.isoformat())
                | (IntelEvent.created_at >= day_start))
        .count()
    )
    h24_events = db.query(IntelEvent).filter(IntelEvent.created_at >= day_ago).count()
    h24_analyses = db.query(IntelAnalysis).filter(IntelAnalysis.created_at >= day_ago).count()
    events_total = db.query(IntelEvent).count()
    analyses_total = db.query(IntelAnalysis).count()

    # 近 N 日每日事件数（按事件发生日；缺失日补 0，前端可直接画柱）
    daily: list[dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        n = db.query(IntelEvent).filter(IntelEvent.occurred_on == d).count()
        daily.append({"date": d, "count": n})

    # 抓取覆盖：上次抓取时间 + 近 24h 被抓过的标的数
    last_scrape: dt.datetime | None = None
    for (ts,) in db.query(IntelCompany.last_scrape_at).filter(
        IntelCompany.last_scrape_at.is_not(None)
    ).all():
        t = _aware(ts)
        if t and (last_scrape is None or t > last_scrape):
            last_scrape = t
    scraped_24h = db.query(IntelCompany).filter(
        IntelCompany.last_scrape_at.is_not(None), IntelCompany.last_scrape_at >= day_ago
    ).count()
    enabled = db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).count()

    # 高影响事件（近 24h）：用户最该看的少数几条
    high_24h = db.query(IntelEvent).filter(
        IntelEvent.created_at >= day_ago, IntelEvent.impact >= 4
    ).count()

    return {
        "today_events": today_events,
        "h24_events": h24_events,
        "h24_analyses": h24_analyses,
        "h24_high_impact": high_24h,
        "events_total": events_total,
        "analyses_total": analyses_total,
        "daily": daily,
        "last_scrape_at": last_scrape.isoformat() if last_scrape else None,
        "scraped_24h": scraped_24h,
        "companies_enabled": enabled,
    }


def last_run(db: Session) -> IntelRun | None:
    """最近一次批次（含已截止的）—— 监控停止后也要能回答「上次什么时候跑的」。"""
    return db.query(IntelRun).order_by(IntelRun.id.desc()).first()
