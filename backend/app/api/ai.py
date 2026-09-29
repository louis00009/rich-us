"""AI 分析接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..ai_analyst import ai_configured, analyze, analyze_local, market_snapshot
from ..schemas import AiAssistRequest, AnalyzeRequest, ChatRequest
from .deps import CurrentUser

router = APIRouter(prefix="/ai", tags=["AI 分析"])

# 会写进 decision_logs 的任务（分析/诊断类）——
# 纯展示类的简报（盘面/新闻/情报）只写审计日志，避免把决策历史刷屏。
_DECISION_TASKS = frozenset({
    "symbol_brief", "backtest_diagnose", "optimize_review",
    "risk_review", "portfolio_review", "order_diagnose",
    # 提案复核直接参与「批准/拒绝」的决策链，必须可追溯；
    # 交易复盘与代码审查同属分析/诊断类，与上面保持一致。
    "proposal_review", "period_review", "strategy_code_review",
})


@router.get("/tasks")
def ai_task_catalog(user: CurrentUser) -> dict:  # noqa: ARG001
    """列出全部可用的 AI 任务（AI Task Hub 的接入点清单）。

    前端可用它做「AI 能力总览」，也便于外部 Agent 发现平台内建的 AI 能力。
    """
    from ..ai_tasks import task_catalog

    return {"items": task_catalog()}


@router.post("/assist")
async def ai_assist(payload: AiAssistRequest, user: CurrentUser) -> dict:
    """统一 AI 助手入口 —— 全平台所有 AI 接入点都走这里。

    复用「设置 → AI 分析」里配置的全局网关/密钥/模型；未配置 LLM 时自动
    降级为确定性的规则化兜底（`engine="local"`），因此前端无需区分两种模式。
    """
    from ..ai_tasks import run_task

    try:
        res = await run_in_threadpool(
            run_task, payload.task, payload.payload, payload.model, payload.force_local
        )
    except ValueError as exc:
        # 任务不存在 / 数据不足 —— 属于用户输入问题，返回 400 让前端直接展示
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"AI 任务执行失败：{type(exc).__name__}: {exc}") from exc

    # 同步 DB 写入必须离开事件循环（SQLite 写锁会冻结整个服务）
    await run_in_threadpool(
        appstate.log, "ai_assist", "INFO",
        f"AI 任务 {payload.task}（{res.get('engine')}）", user.username,
    )
    if payload.task in _DECISION_TASKS:
        try:
            from ..config import settings as _s
            from ..decisions import log_decision

            await run_in_threadpool(
                log_decision,
                f"ai:{payload.model or _s.ai_model or 'local'}",
                "ASSIST",
                f"{res.get('title', payload.task)}（{res.get('engine')}）",
                (res.get("text") or "")[:3000],
                str((payload.payload or {}).get("symbol") or ""),
                "US",
                {"task": payload.task, "engine": res.get("engine"), "model": payload.model},
            )
        except Exception:  # noqa: BLE001 —— 落日志失败绝不影响 AI 结果返回
            pass
    return res



@router.get("/status")
def ai_status(user: CurrentUser) -> dict:  # noqa: ARG001
    from ..ai_analyst import extra_ai_models
    from ..config import settings

    # 运行时全局配置（设置页「AI 分析」）优先于环境变量
    rt = None
    try:
        rt = appstate.get_ai_settings()
    except Exception:  # noqa: BLE001
        rt = None
    if not (rt and rt.get("base_url") and rt.get("api_key")):
        rt = None

    # 下拉清单 = 环境变量定义的别名 + 网关 /v1/models 的全部模型 id。
    # 网关按密钥版本归属过滤（国内版密钥只见 cn: 条目）。
    models = {"cn": [], "global": [], "ok": False, "error": ""}
    if rt:
        try:
            from .system import _fetch_gateway_models

            models = _fetch_gateway_models(rt["base_url"], rt["api_key"])
        except Exception as exc:  # noqa: BLE001
            models["error"] = f"{type(exc).__name__}: {exc}"

    extra = [m["name"] for m in extra_ai_models()]
    flat = list(models.get("cn") or []) + list(models.get("global") or [])
    for mid in flat:
        if mid not in extra:
            extra.append(mid)

    return {
        "llm_configured": bool(rt) or bool(settings.ai_base_url and settings.ai_api_key),
        "base_url": (rt or {}).get("base_url", settings.ai_base_url or ""),
        "model": (rt or {}).get("model") or settings.ai_model,
        "engine_available": "local",
        "extra_models": extra,
        "models_by_realm": {"cn": models.get("cn") or [], "global": models.get("global") or []},
        "models_ok": models.get("ok", False),
        "note": (
            "未配置 LLM 时使用内置本地量化引擎：完全基于行情数据计算，"
            "结果确定性、可复现、无需外部服务。在「设置 → AI 分析」里配好网关后，"
            "此处下拉会列出网关的全部国内/国际模型，选中即用。"
        ),
    }


@router.post("/analyze")
async def do_analyze(payload: AnalyzeRequest, user: CurrentUser) -> dict:  # noqa: ARG001
    from ..config import settings

    syms = [s.strip().upper() for s in payload.symbols if s.strip()][:12]
    if not syms:
        raise HTTPException(400, "至少需要一个标的")
    res = await run_in_threadpool(
        analyze, syms, payload.horizon, payload.question, payload.use_llm, payload.use_intraday, payload.model
    )
    appstate.log("ai_analyze", "INFO", f"AI 分析 {','.join(syms)}（{res['engine']}）", actor=user.username)
    # T-107：单标的研判达标时自动生成交易提案（仅 proposed，绝不自动执行）
    if len(syms) == 1:
        try:
            from ..config import settings as _s
            from ..proposals import create_from_analysis

            proposal = create_from_analysis(res.get("results", [{}])[0], _s.ai_model or "local")
            if proposal:
                res["proposal"] = proposal
        except Exception:  # noqa: BLE001
            pass
    # 决策可追溯：AI 分析也是一次"决策动作"，落 decision_logs
    try:
        from ..decisions import log_decision

        for r in res.get("results", []):
            log_decision(
                actor=f"ai:{settings.ai_model or 'local'}",
                action="ANALYZE",
                decision=(
                    f"{r.get('symbol')} {r.get('regime', '')} / {r.get('bias', '')} "
                    f"评分 {r.get('composite_score', 0)} → 建议仓位 {r.get('suggested_position_pct', 0)}%"
                ),
                reasoning=(r.get("llm_report") or r.get("summary") or "")[:3000],
                symbol=r.get("symbol", ""),
                context={
                    "horizon": payload.horizon, "question": payload.question,
                    "engine": res.get("engine"), "dimensions": r.get("dimensions"),
                },
            )
    except Exception:  # noqa: BLE001
        pass
    return res


@router.post("/chat")
async def chat(payload: ChatRequest, user: CurrentUser) -> dict:  # noqa: ARG001
    if not payload.message.strip():
        raise HTTPException(400, "消息不能为空")

    syms = [s.strip().upper() for s in payload.context_symbols if s.strip()][:6]
    facts: list[dict] = []
    for s in syms:
        snap = await run_in_threadpool(market_snapshot, s)
        if snap.get("error"):
            continue
        local = analyze_local(snap, "swing")
        facts.append({
            "symbol": s, "price": snap["price"], "bias": local.get("bias"),
            "regime": local.get("regime"), "score": local.get("composite_score"),
            "rsi": snap["indicators"].get("rsi14"), "adx": snap["indicators"].get("adx14"),
            "atr_pct": snap["indicators"].get("atr_pct"),
            "returns": snap["returns"], "levels": snap["levels"],
            "warnings": local.get("warnings"),
        })

    if not ai_configured():
        return {
            "ok": True,
            "engine": "local",
            "reply": _local_reply(payload.message, facts),
            "facts": facts,
        }

    from ..ai_analyst import SYSTEM_PROMPT, _llm_call
    import json
    import time

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if facts:
        msgs.append({
            "role": "system",
            "content": "当前上下文中的标的量化快照（JSON，仅供你推理使用，不要逐字复述）：\n"
                       + json.dumps(facts, ensure_ascii=False),
        })
    for h in payload.history[-8:]:
        role = h.get("role", "user")
        if role in ("user", "assistant"):
            msgs.append({"role": role, "content": str(h.get("content", ""))[:4000]})
    msgs.append({"role": "user", "content": payload.message})
    try:
        # ⚠️ reasoning_effort="low" 是 P0 铁律：推理型模型（cn:glm-5.3-flash）的思维链
        # 会烧光 max_tokens → finish_reason=length、content 空字符串（HTTP 200 但正文 0 字符）。
        # 实测：long 上下文思维链 4085 tokens；low 后 70 tokens / 15.9s / 正文完整。
        # 预算 5000（用户要求拉高）：网关上限 6144，8192 会失败——勿超 6144。
        t0 = time.monotonic()
        text = await run_in_threadpool(_llm_call, msgs, 0.3, 5000, payload.model, 90, "low")
        # 空返回补试一次（60s 闸门：前端单次等待上限 180s；6000 仍在网关上限内）
        if not (text or "").strip() and time.monotonic() - t0 < 60:
            text = await run_in_threadpool(_llm_call, msgs, 0.3, 6000, payload.model, 90, "low")
        if (text or "").strip():
            return {"ok": True, "engine": "llm", "reply": text.strip(), "facts": facts}
        # 模型返回空内容 → 降级本地引擎（不能把空串当 llm 成功返回）
        return {
            "ok": True, "engine": "local",
            "llm_error": "模型返回空内容（推理型模型思维链耗尽 token 预算），已降级本地量化引擎",
            "reply": _local_reply(payload.message, facts), "facts": facts,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True, "engine": "local", "llm_error": f"{type(exc).__name__}: {exc}",
            "reply": _local_reply(payload.message, facts), "facts": facts,
        }


def _local_reply(message: str, facts: list[dict]) -> str:
    if not facts:
        return (
            "未提供标的上下文。请在右侧选择 1–6 个标的后再提问，我会基于真实行情给出量化判断。\n\n"
            "我可以在本地完成的分析包括：\n"
            "· 状态判定（趋势 / 震荡 / 高波动）与多空评分\n"
            "· 关键支撑阻力位、ATR 止损位、建议仓位\n"
            "· 与内置策略库的匹配建议（哪类策略当前最适配）\n"
            "· 组合相关性检查与集中度提示"
        )
    lines = ["【本地量化引擎 · 基于真实行情计算】", ""]
    for f in facts:
        lines.append(
            f"▎{f['symbol']}  现价 {f['price']}\n"
            f"   状态：{f['regime']} ｜ 偏向：{f['bias']} ｜ 综合评分 {f['score']}\n"
            f"   RSI {f['rsi']} ｜ ADX {f['adx']} ｜ ATR占比 {f['atr_pct']}%\n"
            f"   区间收益：1M {f['returns'].get('1m')}% / 3M {f['returns'].get('3m')}% / 1Y {f['returns'].get('1y')}%"
        )
        sup = f["levels"].get("支撑") or []
        res = f["levels"].get("阻力") or []
        if sup or res:
            lines.append(f"   支撑 {[round(x,2) for x in sup]} ｜ 阻力 {[round(x,2) for x in res]}")
        for w in (f.get("warnings") or [])[:2]:
            lines.append(f"   ⚠ {w}")
        lines.append("")
    lines.append(
        "说明：以上结论由本地量化引擎直接计算得出（非生成式文本），可作为交易决策的第一层过滤。"
        "如需自然语言深度解读与情景推演，请配置 LLM 接口后开启「智能解读」。"
    )
    return "\n".join(lines)
