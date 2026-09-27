"""决策日志：所有交易决策的统一落库与查询。

AI 可接管的根基 —— 任何模型接手时都能回答：
  「上一个决策者当时看到了什么（context_json）→ 决定做什么（action）
    → 为什么（reasoning）→ 结果下了什么单（order_id）」
"""
from __future__ import annotations

import json
import time
from typing import Any

from .database import SessionLocal, session_scope
from .models import DecisionLog


def log_decision(
    actor: str,
    action: str,
    decision: str = "",
    reasoning: str = "",
    symbol: str = "",
    market: str = "US",
    context: dict[str, Any] | None = None,
    order_id: int | None = None,
    engine_run_id: int | None = None,
) -> None:
    """落一条决策日志。**任何异常都不允许影响交易路径** —— 失败只打警告。"""
    try:
        with session_scope() as s:
            s.add(DecisionLog(
                actor=actor[:48],
                action=action[:24],
                decision=(decision or "")[:2000],
                reasoning=(reasoning or "")[:6000],
                symbol=(symbol or "")[:32],
                market=market or "US",
                context_json=json.dumps(context or {}, ensure_ascii=False, default=str)[:30000],
                order_id=order_id,
                engine_run_id=engine_run_id,
            ))
    except Exception as exc:  # noqa: BLE001
        print(f"[decisions] 决策日志落库失败（不影响交易）：{type(exc).__name__}: {exc}")


def list_decisions(
    limit: int = 50,
    actor: str = "",
    symbol: str = "",
    action_contains: str = "",
) -> list[dict[str, Any]]:
    with SessionLocal() as s:
        q = s.query(DecisionLog)
        if actor:
            q = q.filter(DecisionLog.actor.contains(actor))
        if symbol:
            q = q.filter(DecisionLog.symbol == symbol.upper())
        if action_contains:
            q = q.filter(DecisionLog.action.contains(action_contains))
        rows = q.order_by(DecisionLog.ts.desc(), DecisionLog.id.desc()).limit(min(limit, 200)).all()
        return [{
            "id": r.id, "ts": r.ts.isoformat(), "actor": r.actor,
            "symbol": r.symbol, "market": r.market, "action": r.action,
            "decision": r.decision, "reasoning": r.reasoning,
            "context": json.loads(r.context_json or "{}"),
            "order_id": r.order_id, "engine_run_id": r.engine_run_id,
        } for r in rows]


def stats(hours: int = 24) -> dict[str, Any]:
    """按 actor/action 汇总（供接管中心显示）。"""
    import datetime as dt

    from sqlalchemy import func

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    with SessionLocal() as s:
        by_actor = (
            s.query(DecisionLog.actor, func.count(DecisionLog.id))
            .filter(DecisionLog.ts >= cutoff)
            .group_by(DecisionLog.actor)
            .all()
        )
        by_action = (
            s.query(DecisionLog.action, func.count(DecisionLog.id))
            .filter(DecisionLog.ts >= cutoff)
            .group_by(DecisionLog.action)
            .all()
        )
    return {
        "hours": hours,
        "by_actor": {a: int(n) for a, n in by_actor},
        "by_action": {a: int(n) for a, n in by_action},
    }
