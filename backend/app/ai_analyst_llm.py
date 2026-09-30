"""LLM 分析路径（ai_analyst 的「A 模式」）。

从 ai_analyst.py 按铁律 9（FILE_SIZE_DEBT Batch D-4）拆出：
- 网关配置解析：`_runtime_ai` / `ai_configured` / `extra_ai_models` / `_llm_config_for`；
- 网关调用：`_llm_call`（含 reasoning_effort='low' 的 P0 修复）；
- 上下文与提示词：`SYSTEM_PROMPT` / `_news_context` / `analyze_with_llm`。

⚠️ token 预算与降级语义不要乱动：推理型模型思维链会烧光 max_tokens
（HTTP 200 但正文 0 字符），调用方必须带 `reasoning_effort="low"`。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .ai_analyst_local import analyze_local
from .config import settings


def _runtime_ai() -> dict[str, Any] | None:
    """设置页「AI 分析」存的运行时全局配置；未配置返回 None。

    优先级：state.ai_settings > 环境变量 QD_AI_*。延迟导入避免与 state 的
    加载顺序纠缠（state 只依赖 config，实际无环，但延迟导入最稳）。
    """
    try:
        from . import state as appstate

        ai = appstate.get_ai_settings()
        if ai.get("base_url") and ai.get("api_key"):
            return ai
    except Exception:  # noqa: BLE001 —— 读取失败一律退回环境变量
        pass
    return None


def ai_configured() -> bool:
    if _runtime_ai():
        return True
    return bool(settings.ai_base_url and settings.ai_api_key)


def extra_ai_models() -> list[dict[str, str]]:
    """T-109：解析 QD_AI_EXTRA_MODELS（"name|base_url|api_key|model;..."）。"""
    out: list[dict[str, str]] = []
    for part in (settings.ai_extra_models or "").split(";"):
        seg = [x.strip() for x in part.split("|")]
        if len(seg) == 4 and all(seg):
            out.append({"name": seg[0], "base_url": seg[1], "api_key": seg[2], "model": seg[3]})
    return out


def _llm_config_for(name: str = "") -> tuple[str, str, str]:
    """返回 (base_url, api_key, model)。

    解析顺序：
      1. name 命中 QD_AI_EXTRA_MODELS 里定义的别名 → 用该别名自己的网关配置；
      2. 否则取默认配置（设置页运行时配置 > 环境变量）；
      3. name 非空且不是默认模型名 → 视为**直接的网关模型 id**
         （如 `cn:glm-5.3-flash`），用默认网关 + 该模型发起调用。
         这样 AI Copilot 的模型下拉可以直接列网关 /v1/models 的全部条目，
         选中即用，无需额外注册。
    """
    if name:
        for cfg in extra_ai_models():
            if cfg["name"] == name:
                return cfg["base_url"], cfg["api_key"], cfg["model"]
    rt = _runtime_ai()
    base = rt["base_url"] if rt else (settings.ai_base_url or "")
    key = rt["api_key"] if rt else (settings.ai_api_key or "")
    model = (rt.get("model") if rt else settings.ai_model) or ""
    if name and name != model:
        return base, key, name
    return base, key, model


def _llm_call(messages: list[dict[str, str]], temperature: float = 0.3, max_tokens: int = 1400,
              model_name: str = "", timeout: float = 90,
              reasoning_effort: str | None = None) -> str:
    """调用网关的 chat/completions。

    `timeout` 默认 90s（既有调用方的行为不变）。推理型模型（先输出思维链再写正文）
    单次可能耗时 90s+，AI 任务中枢会显式传更大的值 —— 见 ai_tasks.py 的 `_LLM_TIMEOUT`。

    `reasoning_effort='low'`：P0 修复 —— 推理型模型（cn:glm-5.3-flash）在长上下文
    下思维链会膨胀到 4000+ tokens（实测 finish_reason=length、正文 0 字符，
    95.8s 白等）；`thinking:{"type":"disabled"}` 与 `enable_thinking:false`
    均不被网关透传，只有 OpenAI 风格的 `reasoning_effort` 生效（实测思维链
    4085→70 tokens，95.8s→15.9s 且正文完整）。仅显式传入时生效，其他调用方不变。
    """
    url, api_key, model = _llm_config_for(model_name)
    if not (url and api_key):
        raise RuntimeError("LLM 未配置")
    url = url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions" if url.endswith("/v1") else f"{url}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    with httpx.Client(timeout=timeout) as c:
        r = c.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


def _llm_call_chain(messages: list[dict[str, str]], *,
                    chain: list[str], temperature: float = 0.3, max_tokens: int = 1400,
                    timeout: float = 90, reasoning_effort: str | None = None) -> dict[str, Any]:
    """按链顺序试多个模型（每家独立 fallback —— 09-30 加）。

    设计动机：之前所有抓取共用单一模型，**一个模型挂 = 23 家全挂**。
    现在每家独立尝试 chain[0] → chain[1] → ... → chain[-1]，首个返回
    非空正文的胜出；全失败返回 `text=""` + `model_used=chain[-1]` + `errors`
    列表（按顺序记录每档失败原因，便于日志与重试决策）。

    返回 `{text, model_used, errors: list[str]}` —— 调用方读 model_used 写
    bridge_log（前端「这次抓取用到的实际模型」），读 errors 写 raw_news.last_error。
    """
    errors: list[str] = []
    if not chain:
        chain = [""]
    for name in chain:
        try:
            text = (_llm_call(messages, temperature=temperature, max_tokens=max_tokens,
                              model_name=name, timeout=timeout,
                              reasoning_effort=reasoning_effort) or "").strip()
            if text:
                return {"text": text, "model_used": name or "default", "errors": errors}
            errors.append(f"{name or 'default'}: empty response")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name or 'default'}: {type(exc).__name__}: {str(exc)[:120]}")
    return {"text": "", "model_used": chain[-1] or "default", "errors": errors}


SYSTEM_PROMPT = """你是一位严谨的量化交易分析师，服务于专业交易员。
要求：
1. 只基于给定数据推理，不得编造价格、财报或新闻事实。
2. 明确区分「数据事实」与「概率判断」，判断必须给出依据。
3. 输出使用简体中文，结构化、可执行，避免空泛套话。
4. 必须给出：状态判定、多空观点、关键价位、风控（止损位与仓位）、失效条件。
5. 结尾必须包含一句风险提示。"""


def _news_context(symbol: str, limit: int = 5) -> list[dict[str, Any]]:
    """取该标的最近新闻标题（供 LLM 参考事件面）。失败返回空，绝不阻塞分析。"""
    try:
        from .news import fetch_news

        res = fetch_news(symbol, limit=limit)
        return [
            {
                "标题": it.get("headline", ""),
                "时间": (it.get("published_at") or "")[:16],
                "来源": it.get("source", ""),
                "类型": it.get("category", ""),
            }
            for it in res.get("items", [])
        ]
    except Exception:  # noqa: BLE001
        return []


def analyze_with_llm(snap: dict[str, Any], horizon: str = "swing", question: str = "",
                     model_name: str = "") -> dict[str, Any]:
    local = analyze_local(snap, horizon)
    context = {
        "标的": snap["symbol"], "现价": snap["price"], "数据日期": snap["last_date"],
        "区间收益%": snap["returns"], "均线": snap["ma"], "偏离%": snap["dist"],
        "关键价位": snap["levels"], "指标": snap["indicators"],
        "本地量化引擎结论": {
            "状态": local.get("regime"), "多空": local.get("bias"),
            "综合评分": local.get("composite_score"), "维度分": local.get("dimensions"),
            "建议仓位%": local.get("suggested_position_pct"),
        },
    }
    rt = snap.get("realtime") or {}
    if rt.get("realtime"):
        q = snap.get("quote") or {}
        context["实时盘"] = {
            "实时价": snap["price"],
            "日内涨跌%": q.get("change_pct"),
            "日内最高": q.get("day_high"), "日内最低": q.get("day_low"),
            "报价来源": rt.get("quote_source"), "报价时间": rt.get("quote_ts"),
            "说明": "以上指标已融合实时价计算，非昨日收盘",
        }
    itd = snap.get("intraday")
    if itd:
        context["分钟级结构"] = itd
    news_items = _news_context(snap["symbol"])
    if news_items:
        context["最近新闻与公告"] = news_items
    prompt = (
        f"以下是 {snap['symbol']} 的量化快照（JSON）：\n{json.dumps(context, ensure_ascii=False, indent=1)}\n\n"
        f"投资周期：{horizon}。\n"
        f"{'用户追问：' + question if question else ''}\n"
        "请输出：\n## 状态判定\n## 多空观点（含依据与置信度）\n## 关键价位（支撑/阻力/止损/目标）\n"
        "## 执行建议（仓位、入场方式、加减仓条件）\n## 失效条件（什么情况下判断作废）\n## 风险提示"
        + ("\n若提供了最近新闻与公告，请在观点中评估事件面影响；只引用给定新闻，不得编造。"
           if news_items else "")
    )
    try:
        # P0：推理型模型在长上下文下思维链膨胀到 4000+ tokens（实测 finish=length、
        # 正文 0 字符、95.8s 白等）。reasoning_effort='low' 压缩思维链（4085→70 tokens），
        # 正文 3000 预算足够输出完整 Markdown 报告。
        text = _llm_call([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                         max_tokens=3000, timeout=120, model_name=model_name,
                         reasoning_effort="low")
        local["llm_report"] = text
        local["mode"] = "llm"
    except Exception as exc:  # noqa: BLE001
        local["llm_error"] = f"{type(exc).__name__}: {exc}"
        local["llm_report"] = ""
    return local
