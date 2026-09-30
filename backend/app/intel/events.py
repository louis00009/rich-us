"""intel 事件入库（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

归一化、dedupe_key、add_events（含 _seen_add）、_event_row。
⚠️ add_events 的 category/stage 归一化必须在算 dedupe_key **之前**（key 含 category）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from typing import Any

from .. import intel_classify as classify
from ..database import session_scope
from .common import EVENT_CATEGORIES, EVENT_STAGES, SENTIMENTS, IntelCompany, IntelEvent, IntelRun


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (title or "").lower())[:60]


def _norm_event_time(raw: str) -> str:
    """归一化事件发生时刻为 'YYYY-MM-DD HH:MM'（原样保留来源时区，通常是 UTC）。

    只接受带日期 + 时分的可解析串（ISO / 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD HH:MM:SS'）；
    解析失败返回空串——宁可不显示，也不臆造一个时间。
    """
    s = (raw or "").strip().replace("T", " ")
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ ](\d{2}:\d{2})", s)
    if not m:
        return ""
    return f"{m.group(1)} {m.group(2)}"


def make_dedupe_key(symbol: str, category: str, title: str) -> str:
    return hashlib.sha1(f"{symbol}|{category}|{_norm_title(title)}".encode()).hexdigest()[:40]


def add_events(items: list[dict[str, Any]], agent: str, run_id: int | None) -> dict[str, int]:
    """批量入库事件节点。返回 {inserted, duplicates, rejected}。"""
    inserted = duplicates = rejected = 0
    touched: set[str] = set()
    with session_scope() as db:
        for raw in items:
            try:
                symbol = str(raw.get("symbol", "")).strip().upper()[:32]
                title = str(raw.get("title", "")).strip()[:300]
                if not symbol or not title:
                    rejected += 1
                    continue
                category = str(raw.get("category", "other")).strip()
                if category not in EVENT_CATEGORIES:
                    category = "other"
                stage = str(raw.get("stage", "")).strip().lower()
                if stage not in EVENT_STAGES:
                    stage = ""
                # 归一化：提交方留空 / 给了 other 时用确定性规则补 category 与 stage。
                # ⚠️ 必须在算 dedupe_key **之前** —— key 含 category，顺序错了会让
                # 「同一事件重复提交」漏判成两条。详见 intel_classify 模块 docstring。
                normalized = classify.normalize_event(
                    {"title": title, "summary": raw.get("summary"), "category": category, "stage": stage}
                )
                category = normalized["category"]
                stage = normalized["stage"]
                sentiment = str(raw.get("sentiment", "neutral")).strip()
                if sentiment not in SENTIMENTS:
                    sentiment = "neutral"
                try:
                    impact = max(1, min(5, int(raw.get("impact") or 3)))
                except (TypeError, ValueError):
                    impact = 3
                raw_at = str(raw.get("occurred_at") or raw.get("published_at") or "").strip()
                occurred_on = str(raw.get("occurred_on") or "").strip()[:10] or raw_at[:10]
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", occurred_on):
                    occurred_on = ""
                occurred_at = _norm_event_time(raw_at)
                # 时刻缺失但日期已知：不臆造时间，留空由前端只显示日期
                if occurred_at and occurred_on and occurred_at[:10] != occurred_on:
                    occurred_at = ""
                key = make_dedupe_key(symbol, category, title)
                if db.query(IntelEvent.id).filter(IntelEvent.dedupe_key == key).first():
                    duplicates += 1
                    continue
                # 未知标的：自动建档为未启用（不进入自动任务），由用户决定是否关注
                if not db.query(IntelCompany.id).filter(IntelCompany.symbol == symbol).first():
                    db.add(IntelCompany(symbol=symbol, name=str(raw.get("company_name", ""))[:120],
                                        enabled=False, note="由 AI Agent 提交事件时自动创建"))
                db.add(IntelEvent(
                    symbol=symbol, occurred_on=occurred_on, occurred_at=occurred_at, category=category,
                    title=title, summary=str(raw.get("summary", "")).strip()[:2000],
                    impact=impact, sentiment=sentiment, stage=stage,
                    source_name=str(raw.get("source_name", "")).strip()[:200],
                    source_url=str(raw.get("source_url", "")).strip()[:600],
                    dedupe_key=key, agent=agent, run_id=run_id,
                ))
                db.flush()  # 立即可见：同批重复项与后续唯一键检查都能命中
                touched.add(symbol)
                inserted += 1
            except Exception as exc:  # noqa: BLE001 —— 单条失败不拖垮整批
                # 记录原因：静默吞异常会让「提交成功但 0 入库」无法定位
                logging.getLogger("quantdesk.intel").warning(
                    "事件入库失败 symbol=%s title=%s: %s: %s",
                    raw.get("symbol"), str(raw.get("title"))[:40], type(exc).__name__, exc)
                rejected += 1
        if run_id:
            run = db.get(IntelRun, run_id)
            if run:
                run.events_found = (run.events_found or 0) + inserted
                _seen_add(run, agent)
        for sym in touched:
            comp = db.query(IntelCompany).filter(IntelCompany.symbol == sym).first()
            if comp:
                comp.last_scrape_at = dt.datetime.now(dt.timezone.utc)
    # 数据一到就更新每日必读：提交已结束（session_scope 出栈 = 已 commit），
    # 后台重算拿得到刚入库的事件。手动抓取 / 监控内置 AI / Bridge Agent 三条
    # 入库路径全走这里，一个挂钩全覆盖。失败不影响入库。
    # 09-30 修复：触发条件从 `if inserted` 改为 `if inserted or touched` —— Bridge Agent
    # 重复提交（同条新闻多 Agent 复述，dedupe 全命中 inserted=0）的情况不能跳过刷新；
    # 用户期望「提交了就能在 UI 看到最新状态」（即使全是 dup，确认数据库已 commit 是基本预期）。
    if inserted or touched:
        try:
            from .. import intel_digest

            intel_digest.refresh_async("events")
        except Exception:  # noqa: BLE001
            pass
    return {"inserted": inserted, "duplicates": duplicates, "rejected": rejected}


def _seen_add(run: IntelRun, agent: str) -> None:
    try:
        seen = json.loads(run.agents_seen or "[]")
    except json.JSONDecodeError:
        seen = []
    if agent and agent not in seen:
        seen.append(agent)
        run.agents_seen = json.dumps(seen[:12], ensure_ascii=False)



def _event_row(e: IntelEvent) -> dict[str, Any]:
    return {
        "id": e.id, "symbol": e.symbol, "occurred_on": e.occurred_on, "occurred_at": e.occurred_at or "",
        "category": e.category,
        "category_cn": EVENT_CATEGORIES.get(e.category, e.category),
        "title": e.title, "summary": e.summary, "impact": e.impact, "sentiment": e.sentiment,
        "source_name": e.source_name, "source_url": e.source_url, "agent": e.agent,
        # 媒体评论/行情播报/分析师动作（规则判定，非公司自身事件）——
        # 前端据此把这类条目降级展示，避免把噪音和真实催化剂混在一起。
        "commentary": classify.is_commentary(e.title or ""),
        "created_at": e.created_at.isoformat(),
    }

