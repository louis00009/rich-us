"""intel Bridge 接入（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

token 重置、台账日志（bridge_log）、待抓取任务、接入指南（bridge_guide）。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..database import session_scope
from .common import (
    EVENT_CATEGORIES,
    RECOMMENDATIONS,
    IntelBridgeLog,
    IntelCompany,
    IntelSetting,
    log,
)
from .settings import _gen_token, ensure_settings


def reset_bridge_token() -> str:
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        row.bridge_token = _gen_token()
        token = row.bridge_token
    log.info("Intel bridge token 已重置")
    return token



def bridge_log(agent: str, action: str, detail: str = "", ok: bool = True) -> None:
    try:
        with session_scope() as db:
            db.add(IntelBridgeLog(agent=agent[:48] or "unknown", action=action,
                                  detail=str(detail)[:800], ok=ok))
    except Exception:  # noqa: BLE001
        pass



def pending_tasks(db: Session, interval_minutes: int) -> list[dict[str, Any]]:
    """到期待抓取的公司：从未抓取，或上次抓取已超过 1.2 个周期。"""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=interval_minutes * 1.2)
    out: list[dict[str, Any]] = []
    for c in db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).all():
        # 历史缺陷：DB 里的 naive UTC 与 aware cutoff 直接比较会 TypeError——统一补 UTC 后再比
        last = c.last_scrape_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        if last is None or last < cutoff:
            out.append({
                "symbol": c.symbol, "name": c.name, "theme": c.theme, "focus": c.focus,
                "last_scrape_at": c.last_scrape_at.isoformat() if c.last_scrape_at else None,
                "due_reason": "never" if c.last_scrape_at is None else "stale",
            })
    return out



def bridge_base_url() -> str:
    host = "127.0.0.1" if settings.host in ("0.0.0.0", "127.0.0.1") else settings.host
    return f"http://{host}:{settings.port}"



def bridge_guide() -> dict[str, Any]:
    st = ensure_settings()
    base = bridge_base_url()
    token = st.bridge_token
    common = (
        f"接口约定：\n"
        f"  · 所有请求带 header：X-Intel-Token: {token}\n"
        f"  · 领任务：GET {base}/api/intel/bridge/poll?agent=<你的名字>\n"
        f"  · 公司简报：GET {base}/api/intel/bridge/brief/<SYMBOL>\n"
        f"  · 提交事件：POST {base}/api/intel/bridge/events\n"
        f"  · 提供建议：POST {base}/api/intel/bridge/analysis\n"
        f"  · 收工确认：POST {base}/api/intel/bridge/done\n"
    )
    prompts = {
        "workbuddy": (
            f"请作为 QuantDesk 的外部情报 Agent（在所有提交中把 agent 参数填为：workbuddy）执行一轮情报抓取。\n{common}\n"
            "【执行步骤】\n"
            "1. GET /api/intel/bridge/poll?agent=workbuddy 获取待抓取公司列表；\n"
            "2. 对每家公司联网检索最近 90 天的关键节点（产品发布/重大合同签约/财报/监管/人事）；\n"
            "3. 每条节点 POST /api/intel/bridge/events 提交，字段要求：\n"
            "   · symbol、occurred_on（YYYY-MM-DD，事件发生日，必填）、category、title、summary\n"
            "   · source_name + source_url（必须真实可访问，禁止编造）\n"
            "   · stage（前瞻管道阶段）：confirmed=已公告签约/落地，negotiating=官方口径在谈/磋商，rumor=媒体传闻未证实，普通事件留空\n"
            "   · sentiment（positive/neutral/negative）与 impact（1-5 星）\n"
            "4. GET /api/intel/bridge/brief/<SYMBOL> 取简报，结合事件面与量化快照，POST /api/intel/bridge/analysis 提交建议：\n"
            "   recommendation（strong_buy/buy/hold/reduce/avoid）、confidence 0-100、thesis、catalysts、risks、position_pct 0-20、invalidation\n"
            "5. 全部完成后 POST /api/intel/bridge/done。\n"
            "【质量红线】只提交有真实来源的信息；区分『已敲定事实』与『在谈/传闻』，不要把传闻标成 confirmed。"
        ),
        "claude_code": (
            f"用 curl 与 QuantDesk 情报桥接完成一轮抓取（提交时 agent 参数填：claude-code）。\n{common}\n"
            f"示例：curl -s -H \"X-Intel-Token: {token}\" \"{base}/api/intel/bridge/poll?agent=claude-code\"\n"
            "【执行步骤】\n"
            "1. poll 获取 tasks（每家含 symbol 与抓取原因）；\n"
            "2. 逐家联网检索最近 90 天关键节点；\n"
            "3. POST /events 提交事件——字段：symbol、occurred_on（YYYY-MM-DD 必填）、category、title、summary、"
            "source_name/source_url（真实链接）、stage（confirmed=已敲定/negotiating=在谈/rumor=传闻，普通事件留空）、sentiment、impact 1-5；\n"
            "4. GET /bridge/brief/<SYMBOL> 后 POST /analysis 提交建议（recommendation/confidence/thesis/catalysts/risks/position_pct/invalidation）；\n"
            "5. POST /done 收工。"
        ),
        "codex": (
            f"执行 QuantDesk 情报抓取任务（提交时 agent 参数填：codex）。\n{common}\n"
            f"curl -s -H \"X-Intel-Token: {token}\" \"{base}/api/intel/bridge/poll?agent=codex\"\n"
            "【流程】poll → 逐家联网调研（近 90 天：产品/合同签约/财报/监管/人事）→ POST /events → "
            "GET /bridge/brief/<SYMBOL> → POST /analysis → POST /done。\n"
            "【事件字段】symbol、occurred_on（YYYY-MM-DD 必填）、category、title、summary、source_name/source_url（真实链接）、"
            "stage（confirmed=已敲定/negotiating=在谈/rumor=传闻/空=普通事件）、sentiment、impact 1-5。\n"
            "【红线】信息必须带真实来源；区分事实与传闻；禁止编造。"
        ),
    }
    return {
        "base_url": base,
        "token": token,
        "token_header": "X-Intel-Token",
        "endpoints": {
            "poll": f"{base}/api/intel/bridge/poll",
            "brief": f"{base}/api/intel/bridge/brief/{{symbol}}",
            "events": f"{base}/api/intel/bridge/events",
            "analysis": f"{base}/api/intel/bridge/analysis",
            "done": f"{base}/api/intel/bridge/done",
        },
        "prompts": prompts,
        "event_categories": EVENT_CATEGORIES,
        "recommendation_options": sorted(RECOMMENDATIONS),
        "security_note": "Bridge 与交易账户完全隔离：只能读写情报数据，无法下单、无法访问持仓与密钥。token 可随时在页面重置。",
    }

