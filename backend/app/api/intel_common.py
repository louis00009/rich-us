"""AI 情报中心 API · 共享件（Bridge 鉴权 / 请求体 / 归一化工具）。

从 `api/intel.py` 抽出（铁律 9 拆分，2026-09-29）。原文件 706 行、超 600 软上限。

被 `api/intel.py`（管理端）与 `api/intel_bridge.py`（Bridge 端）**共用**，
因此不能放进任一方 —— 否则会形成循环导入（两边都要 import 对方）。

内容分三类：
  · Bridge 鉴权        —— `bridge_auth`（X-Intel-Token）
  · 请求体模型         —— 各 `*Req`
  · 纯归一化/加工函数  —— `_norm_agent` / `_norm_scrape_*` / `_scored_rows`
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any

from fastapi import Header, HTTPException, Query
from pydantic import BaseModel

from .. import intel, intel_digest
from ..models import IntelEvent

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^]{1,16}$")


def _norm_agent(agent: str | None) -> str:
    """解析式处理任意 Agent 名：不设白名单——非法字符替换为 '-' 而非整体拒绝。

    例：'WorkBuddy AI'→'WorkBuddy-AI'，'workbuddy.ai'→'workbuddy-ai'，
    名字完整保留（截 48 与 DB 列宽一致），空值才回退 unknown。
    """
    a = re.sub(r"[^A-Za-z0-9_\-. ]", "-", (agent or "").strip())
    a = re.sub(r"[ .]+", "-", a).strip("-_")[:48]
    return a or "unknown"


def _llm_configured() -> bool:
    from ..ai_analyst import ai_configured

    return ai_configured()


# ==================================================================
# Bridge 鉴权
# ==================================================================
def bridge_auth(
    x_intel_token: Annotated[str, Header()] = "",
    token: Annotated[str, Query(include_in_schema=False)] = "",
) -> str:
    """校验 Bridge Token，返回规范化前的 token（仅用于比对）。"""
    st = intel.ensure_settings()
    supplied = x_intel_token or token
    if not supplied or supplied != st.bridge_token:
        raise HTTPException(401, "X-Intel-Token 无效或缺失（可在情报中心页面查看/重置）")
    return supplied


# ==================================================================
# 请求体
# ==================================================================
class MonitorStartReq(BaseModel):
    interval_minutes: int | None = None
    auto_analyze: bool | None = None
    ai_scrape: bool | None = None


class IntelSettingsReq(BaseModel):
    interval_minutes: int | None = None
    auto_analyze: bool | None = None
    ai_scrape: bool | None = None
    # 重点标的（监控每轮优先抓取；2026-09-30 起「指定标的」同步到这里 = 重点盯）
    pinned_symbols: list[str] | None = None
    # 价格异动联动阈值 %（观察标的盘中 |涨跌幅| 达到即记事件 + 触发归因分析）
    surge_pct: float | None = None
    # 模型 fallback 链（09-30 加）：逗号分隔，每家抓取按顺序尝试。
    # 例：`"监hy4-perview,cn:glm-5.3-flash,deepseek4.1-flash"`。空串 = 用 settings.ai_model 单档。
    llm_fallback_chain: str | None = None


class AiScrapeReq(BaseModel):
    # 显式指定标的（前端「指定标的」）：**非空即精确批次**，limit 不生效。空 = 自动轮转。
    symbols: list[str] = []
    # 本轮家数：<= 0 = 全部待抓取（前端「全部」选项）；正数夹在 [1, 60]。
    # 仅在上面的 symbols 为空时生效。
    limit: int = 3
    with_analysis: bool = True
    model: str = ""   # 空 = 设置页默认模型；非空 = 别名/网关模型 id（_llm_config_for 解析）


class RetryRequest(BaseModel):
    """POST /intel/scrape/retry 的请求体（09-30 加）。"""
    symbols: list[str] = []        # 空 = 自动取近 since_minutes 内失败家
    since_minutes: int = 60        # 自动模式下的时间窗
    model: str = ""                # 空 = 用 llm_fallback_chain；非空 = 单档模型


# 手动抓取的硬上限：单家要 1 次新闻聚合 + 最多 2 次 LLM 调用，推理型模型每次先烧
# 上千 token 思维链。放开到 60 是「够用且不至于失控」——超过这个量应该靠调度器轮转，
# 而不是一次点完（后台任务虽可取消，但会长时间占住 LLM 配额）。
_SCRAPE_MAX = 60


def _norm_scrape_limit(value: object) -> int:
    """归一化手动抓取家数：<= 0 表示「全部」，正数夹到 [1, _SCRAPE_MAX]。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 3
    if n <= 0:
        return 0
    return max(1, min(_SCRAPE_MAX, n))


def _norm_scrape_symbols(raw: object) -> list[str]:
    """归一化**显式指定**的抓取标的：大写、去空格、去重（保序）、上限 _SCRAPE_MAX。

    非序列输入（老前端/手写 curl 传字符串或 null）一律按空处理 —— 空 = 走「自动」路径，
    与前端 `symbolsToList` 同一套规则，避免「传了 'NVDA,MSFT' 被当成一个标的代码」。

    超过上限时保留前 N 个：截断发生在用户勾选之后，属于配额保护，不是静默改需求。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for it in raw:
        s = str(it or "").strip().upper()
        if s and s not in out:
            out.append(s)
    return out[:_SCRAPE_MAX]


class CompanyReq(BaseModel):
    symbol: str
    name: str = ""
    theme: str = ""
    focus: str = ""


class CompanyUpdateReq(BaseModel):
    name: str | None = None
    theme: str | None = None
    focus: str | None = None
    enabled: bool | None = None


class BridgeEventsReq(BaseModel):
    agent: str = "unknown"
    events: list[dict[str, Any]] = []


class BridgeAnalysisReq(BaseModel):
    agent: str = "unknown"
    analyses: list[dict[str, Any]] = []


class BridgeDoneReq(BaseModel):
    agent: str = "unknown"
    note: str = ""


# ==================================================================
# 事件行加工
# ==================================================================
def _scored_rows(rows: list[IntelEvent], limit: int, today: dt.date,
                 media: str = "", by_importance: bool = False) -> list[dict]:
    """给事件行注入 stage / 重要度，并在需要时按重要度截断。

    ⚠️ 只有 `by_importance=True`（即 `sort=importance`）才允许重排 —— 否则
    `sort=created` 在「多取一批后截断」时会被悄悄改成按重要度排序。
    """
    out = []
    for e in rows:
        item = intel._event_row(e)
        item["stage"] = e.stage or ""
        item["stage_cn"] = intel.EVENT_STAGES.get(e.stage, "") if e.stage else ""
        s = intel_digest.score_event(item, today=today)
        item["importance"] = s["importance"]
        item["tier"] = s["tier"]
        item["importance_reasons"] = s["reasons"]
        out.append(item)
    if media in ("exclude", "only"):
        want = media == "only"
        out = [x for x in out if bool(x.get("commentary")) is want]
    if limit and len(out) > limit:
        if by_importance:
            out.sort(key=lambda x: -x["importance"])
        out = out[:limit]
    return out
