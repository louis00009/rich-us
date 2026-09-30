"""intel 事件面评分与时间线（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

_event_face_weights（纯函数，correct 节单测）、_event_face、_rec_from_score、
_vol_position_scale（纯函数）、timeline。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import case

from ..database import session_scope
from .common import EVENT_CATEGORIES, EVENT_STAGES, REC_CN, IntelAnalysis, IntelCompany, IntelEvent


_LOCAL_REC_MAP = [(50, "strong_buy"), (20, "buy"), (-20, "hold"), (-50, "reduce"), (-999, "avoid")]

_EVENT_FACE_WEIGHT = 0.20   # 事件面在综合评分中的权重（本地引擎）
_EVENT_FACE_DAYS = 90       # 事件面回看窗口


# 前瞻管道阶段权重（与 intel_digest.STAGE_WEIGHT 同口径）：已敲定 > 在谈 > 传闻
_STAGE_WEIGHT: dict[str, float] = {"confirmed": 1.25, "negotiating": 1.0, "rumor": 0.65}
# 同一 (发生日, 方向) 最多计入权重的事件条数：同一条消息被路透/Bloomberg/官网
# 各发一遍（标题不同绕过 dedupe）时不再线性刷分
_EVENT_FACE_DAILY_CAP = 3


def _event_face_weights(events: list[dict[str, Any]], days: int, today: dt.date) -> list[dict[str, Any]]:
    """事件面权重计算（纯函数，无 I/O，供 correct 节单测）。

    每条事件 weight = (impact/5) × 时间衰减 max(0.05, 1 - age/days) × 阶段权重，
    再按 (发生日, 方向) 分组取权重最高的前 _EVENT_FACE_DAILY_CAP 条计入（kept）。
    返回 [{weight, age_days, kept}]，与输入事件按下标一一对应。
    """
    out: list[dict[str, Any]] = []
    for it in events:
        ref = it.get("occurred_on") or (it.get("created_at") or "")
        try:
            d0 = dt.date.fromisoformat(str(ref)[:10])
            age = (today - d0).days
        except (ValueError, TypeError):
            age = days  # 日期未知：按最远窗口计（最保守）
        out.append({"weight": 0.0, "age_days": age, "kept": True, "day": str(ref)[:10]})

    for i, it in enumerate(events):
        age = out[i]["age_days"]
        stage = str(it.get("stage") or "")
        out[i]["weight"] = (
            (it.get("impact") or 0) / 5.0
            * max(0.05, 1.0 - max(0, age) / days)
            * _STAGE_WEIGHT.get(stage, 1.0)
        )

    # 同 (发生日, 方向) 封顶：按权重降序保留前 N 条
    groups: dict[tuple[str, str], list[int]] = {}
    for i, it in enumerate(events):
        sent = str(it.get("sentiment") or "neutral")
        groups.setdefault((out[i]["day"], sent), []).append(i)
    for idxs in groups.values():
        for i in sorted(idxs, key=lambda j: -out[j]["weight"])[_EVENT_FACE_DAILY_CAP:]:
            out[i]["kept"] = False
    return out


def _event_face(symbol: str, days: int = _EVENT_FACE_DAYS) -> dict[str, Any]:
    """事件面评分：近期信息按「影响度 × 时间衰减 × 阶段」加权。

    每条事件权重 = (impact/5) × max(0.05, 1 - 距今天数/days) × stage 权重
      · stage：confirmed 1.25 / negotiating 1.0 / rumor 0.65（与 digest 同口径）；
      · 同 (发生日, 方向) 最多计 3 条 —— 多源转发不再线性刷分。
    score = 100 × (利好权重和 − 利空权重和) / max(利好+利空, 0.5)   ∈ [-100, +100]
    中性事件只计数不参与分子；无利好/利空 → score=None。
    返回 {score, n, pos, neg, neu, top: [按权重排序的事件摘要], ids}
    """
    now = dt.datetime.now(dt.timezone.utc)
    with session_scope() as db:
        rows = (
            db.query(IntelEvent).filter(IntelEvent.symbol == symbol.upper())
            .order_by(IntelEvent.created_at.desc()).limit(40).all()
        )
        events = [
            {
                "id": e.id, "title": e.title, "category": e.category, "impact": e.impact,
                "sentiment": e.sentiment, "occurred_on": e.occurred_on, "stage": e.stage or "",
                "created_at": e.created_at.isoformat() if e.created_at else "",
                "age_days": None,
            }
            for e in rows
        ]
    wts = _event_face_weights(events, days, now.date())
    pos_w = neg_w = 0.0
    pos_n = neg_n = neu_n = 0
    for it, w in zip(events, wts):
        it["age_days"] = w["age_days"]
        it["weight"] = round(w["weight"], 4)
        if not w["kept"]:
            continue
        if it["sentiment"] == "positive":
            pos_w += w["weight"]
            pos_n += 1
        elif it["sentiment"] == "negative":
            neg_w += w["weight"]
            neg_n += 1
        else:
            neu_n += 1
    score = round(100.0 * (pos_w - neg_w) / max(pos_w + neg_w, 0.5), 1) if (pos_w + neg_w) > 0 else None
    top = sorted((it for it, w in zip(events, wts) if w["kept"]),
                 key=lambda x: -x.get("weight", 0.0))[:4]
    return {"score": score, "n": len(events), "pos": pos_n, "neg": neg_n, "neu": neu_n,
            "top": top, "ids": [t["id"] for t in top]}


def _rec_from_score(score: float) -> str:
    return next(r for th, r in _LOCAL_REC_MAP if score >= th)



def _vol_position_scale(position_pct: float, rv20: float | None) -> float:
    """建议仓位随已实现波动率缩放（纯函数，供 correct 节单测）。

    rv20 为年化小数（0.18 = 18%）。高波动压缩仓位、低波动适度放大，
    硬上限 20% 与护栏 max_position_pct 对齐：
      rv20 ≥ 40% → ×0.5（TSLA 级波动不给满仓）
      rv20 ≥ 25% → ×0.75
      rv20 ≤ 10% → ×1.25（低波标的仓位效率更高）
    position_pct 无效（≤0）返回 0；rv20 未知原样放行（只做上限钳制）。
    """
    try:
        pos = float(position_pct or 0)
    except (TypeError, ValueError):
        return 0.0
    if pos <= 0:
        return 0.0
    scale = 1.0
    if rv20 is not None:
        if rv20 >= 0.40:
            scale = 0.5
        elif rv20 >= 0.25:
            scale = 0.75
        elif rv20 <= 0.10:
            scale = 1.25
    return round(min(pos * scale, 20.0), 1)



def timeline(symbol: str, days: int = 180) -> dict[str, Any]:
    """公司时间线：过去 N 天事件（含前瞻管道）+ 最新 AI 建议 + 行情摘要。

    「财报是滞后指标」——用已敲定合同/在谈订单管道前瞻未来 3-6 个月经营。
    """
    symbol = symbol.strip().upper()
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with session_scope() as db:
        evs = (
            db.query(IntelEvent)
            .filter(IntelEvent.symbol == symbol, IntelEvent.occurred_on >= cutoff)
            # 已知日期优先：occurred_on 为空（日期未知）排最后，同日再按时刻倒序
            .order_by(
                case((IntelEvent.occurred_on != "", 0), else_=1),
                IntelEvent.occurred_on.desc(),
                IntelEvent.occurred_at.desc(),
                IntelEvent.id.desc(),
            )
            .limit(120)
            .all()
        )
        ana = (
            db.query(IntelAnalysis)
            .filter(IntelAnalysis.symbol == symbol)
            .order_by(IntelAnalysis.id.desc())
            .first()
        )
        comp = db.query(IntelCompany).filter(IntelCompany.symbol == symbol).first()

    def _ev(e: IntelEvent) -> dict[str, Any]:
        return {
            "id": e.id, "occurred_on": e.occurred_on, "occurred_at": e.occurred_at or "",
            "category": e.category,
            "category_cn": EVENT_CATEGORIES.get(e.category, e.category),
            "title": e.title, "summary": e.summary, "impact": e.impact,
            "sentiment": e.sentiment, "stage": e.stage,
            "stage_cn": EVENT_STAGES.get(e.stage, "") if e.stage else "",
            "source_name": e.source_name, "source_url": e.source_url,
            "agent": e.agent,
        }

    events = [_ev(e) for e in evs]
    pipeline = {
        st: sum(1 for x in events if x["stage"] == st) for st in EVENT_STAGES
    }
    pos = sum(1 for x in events if x["sentiment"] == "positive")
    neg = sum(1 for x in events if x["sentiment"] == "negative")
    # 前瞻可见性评分：已敲定=+2/条（封顶 20），在谈=+1/条（封顶 10），负面事件 -2（封顶 -12）
    visibility = min(20, pipeline.get("confirmed", 0) * 2) + min(10, pipeline.get("negotiating", 0)) \
        - min(12, neg * 2)

    quote = {}
    try:
        from ..data_provider import get_quote

        quote = get_quote(symbol) or {}
    except Exception:  # noqa: BLE001
        pass

    return {
        "symbol": symbol,
        "name": (comp.name if comp else "") or "",
        "enabled": bool(comp.enabled) if comp else False,
        "days": days,
        "events": events,
        "counts": {
            "total": len(events),
            "positive": pos,
            "negative": neg,
            "neutral": len(events) - pos - neg,
            **pipeline,
        },
        "pipeline": pipeline,                       # confirmed/negotiating/rumor 计数
        "visibility_score": visibility,             # 经营可见性评分（前瞻）
        "latest_analysis": {
            "recommendation": ana.recommendation,
            "recommendation_cn": REC_CN.get(ana.recommendation, ana.recommendation),
            "confidence": ana.confidence,
            "thesis": ana.thesis,
            "catalysts": ana.catalysts,
            "risks": ana.risks,
            "position_pct": ana.position_pct,
            "horizon": ana.horizon,
            "event_score": ana.event_score,
            "agent": ana.agent,
            "created_at": ana.created_at.isoformat() if ana.created_at else "",
        } if ana else None,
        "quote": quote,
    }

