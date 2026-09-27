"""AI 分析接口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..ai_analyst import ai_configured, analyze, analyze_local, market_snapshot
from ..schemas import AnalyzeRequest, ChatRequest
from .deps import CurrentUser

router = APIRouter(prefix="/ai", tags=["AI 分析"])


@router.get("/status")
def ai_status(user: CurrentUser) -> dict:  # noqa: ARG001
    from ..ai_analyst import extra_ai_models
    from ..config import settings

    return {
        "llm_configured": ai_configured(),
        "base_url": settings.ai_base_url or "",
        "model": settings.ai_model if ai_configured() else "",
        "engine_available": "local",
        "extra_models": [m["name"] for m in extra_ai_models()],
        "note": (
            "未配置 LLM 时使用内置本地量化引擎：完全基于行情数据计算，"
            "结果确定性、可复现、无需外部服务。配置 QD_AI_BASE_URL 与 QD_AI_API_KEY 后可升级为 LLM 解读；"
            "多模型用 QD_AI_EXTRA_MODELS（name|url|key|model;...）。"
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
        text = await run_in_threadpool(_llm_call, msgs, 0.3, 1400, payload.model)
        return {"ok": True, "engine": "llm", "reply": text, "facts": facts}
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
