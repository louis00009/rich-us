"""AI 任务 · 运营类（策略草稿 / 订单诊断 / 情报解读 / 提案复核）。"""
from __future__ import annotations

from typing import Any

from .ai_tasks import _GUARD, _j, _num, _register, _snap_facts

# ==================================================================
# 1. 策略草稿生成（策略实验室）
# ==================================================================
def _b_strategy_draft(p: dict) -> tuple[str, dict]:
    desc = str(p.get("description", "")).strip()
    if not desc:
        raise ValueError("请先描述你想要的策略")
    try:
        from .strategies.registry import list_strategies

        lib = [
            {"key": s["key"], "name": s["name"], "category": s["category"],
             "tags": s["tags"], "params": [x.get("key") for x in s["params"]]}
            for s in list_strategies()
        ]
    except Exception:  # noqa: BLE001
        lib = []
    facts = {"user_request": desc, "available_strategies": lib, "market_hint": p.get("market")}
    prompt = (
        "用户想设计一个交易策略，描述如下：\n"
        f"「{desc}」\n\n"
        "平台现有策略库（优先从中选一个最接近的作为基底，避免重复造轮子）：\n"
        f"{_j({'strategies': lib})}\n\n"
        "请输出一份**策略草稿**：\n"
        "## 策略定位（趋势/回归/事件/微观结构，以及适配的市场状态）\n"
        "## 建议基底（从上面策略库中选 key，并说明为什么）\n"
        "## 进场条件（可量化的指标 + 阈值）\n"
        "## 离场条件（止损 / 止盈 / 时间止损）\n"
        "## 参数与默认值建议（每个参数给一个合理区间）\n"
        "## 失效场景与风险\n"
        "## 验证计划（先回测什么区间、看哪几个指标）\n"
        "注意：这只是给用户去「策略实验室」手动配置的草稿，不要声称它一定能盈利。" + _GUARD
    )
    return prompt, facts


_KEYWORD_MAP = [
    (("突破", "breakout", "海龟", "唐奇安"), "donchian_breakout"),
    (("趋势", "动量", "momentum", "跟随"), "tsmom_vol_target"),
    (("均线", "金叉", "死叉", "sma", "ema"), "trend_composite"),
    (("超卖", "反转", "回归", "rsi", "布林"), "rsi_meanrev"),
    (("网格", "震荡", "grid"), "grid_trading"),
    (("配对", "套利", "协整"), "pairs_trading"),
    (("跳空", "gap"), "gap_fade"),
    (("波动率", "vol", "风险平价"), "risk_parity_alloc"),
    (("超级趋势", "supertrend", "atr"), "supertrend"),
    (("状态", "自适应", "regime"), "regime_adaptive"),
]


def _l_strategy_draft(f: dict, _p: dict) -> str:
    desc = f.get("user_request", "")
    lib = f.get("available_strategies") or []
    low = desc.lower()
    hit = ""
    for words, key in _KEYWORD_MAP:
        if any(w in low for w in words):
            hit = key
            break
    name = next((s["name"] for s in lib if s["key"] == hit), "")
    lines = [
        "【策略草稿（规则化匹配，未使用 LLM）】",
        f"你的描述：{desc}",
        "",
        f"建议基底：{hit or '未匹配到明确策略族'}{f'（{name}）' if name else ''}",
    ]
    if hit:
        cand = next((s for s in lib if s["key"] == hit), None)
        if cand and cand.get("params"):
            lines.append(f"可调参数：{', '.join(str(x) for x in cand['params'])}")
    lines.append("")
    lines.append("通用骨架：")
    lines.append("· 进场：明确一个「状态过滤器 + 触发条件」（例如 ADX>25 且价格上破 20 日高点）")
    lines.append("· 离场：固定止损（ATR 的 2–3 倍）+ 时间止损 + 移动止盈")
    lines.append("· 验证：先跑 5 年以上日线，重点看夏普、最大回撤与交易笔数（>30 才有统计意义）")
    lines.append("")
    lines.append("配置 LLM 后可获得针对你描述量身定制的完整草稿。")
    return "\n".join(lines)


_register(
    "strategy_draft",
    "策略草稿生成",
    "把自然语言描述的交易想法转成可配置的策略草稿（含基底、进出场、参数）。",
    _b_strategy_draft,
    _l_strategy_draft,
    max_tokens=1500,
)


# ==================================================================
# 2. 订单 / 错误诊断（实盘交易页、AIOps）
# ==================================================================
_REJECT_HINTS: dict[str, str] = {
    "KILL_SWITCH": "熔断开关已启用，所有新订单被拒。需在风控中心用账户口令解除。",
    "LIVE_LOCKED": "实盘三重锁未全部打开。需依次完成环境变量、运行时解锁、口令确认。",
    "SHORT_FORBIDDEN": "风控禁止裸卖空（allow_short=false）。若确实需要做空，先在风控中心显式开启。",
    "MAX_POSITION": "单标的占比超上限，系统会按上限缩减数量后再执行。",
    "MAX_GROSS": "总敞口超上限，需先减仓或提高上限。",
    "MAX_OPEN_POSITIONS": "持仓数量已达上限，先平掉部分持仓。",
    "DAILY_LOSS": "触发日内亏损熔断，当日只允许减仓单。",
    "DRAWDOWN": "触发回撤熔断，需人工复核后再恢复交易。",
    "MARKET_CLOSED": "当前不在交易时段（或未开启盘前盘后）。",
    "LOT_SIZE": "港股按每手整数倍交易，数量已向下取整到整手。",
    "INSUFFICIENT_CASH": "现金不足，需降低数量或先卖出部分持仓。",
    "BLACKLIST": "标的在风控黑名单中。",
    "NOT_WHITELISTED": "白名单已启用且该标的不在其中。",
    "MIN_NOTIONAL": "订单名义金额低于最小下单金额。",
    "MAX_NOTIONAL": "订单名义金额超过单笔上限。",
    "MAX_DAILY_ORDERS": "当日订单笔数已达上限。",
    "MAX_ORDERS_PER_MINUTE": "每分钟订单笔数超限，稍后再试。",
    "EXTENDED_HOURS": "盘前盘后交易未开启。",
}

_OK_STATUS = ("FILLED", "SUBMITTED", "PRESUBMITTED", "PENDING", "PENDINGSUBMIT", "CANCELLED")


def _b_order_diagnose(p: dict) -> tuple[str, dict]:
    orders = p.get("orders") or []
    if not orders:
        raise ValueError("没有可诊断的订单")
    facts = {
        "mode": p.get("mode"),
        "orders": [
            {
                "id": o.get("id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "type": o.get("order_type"),
                "qty": o.get("quantity"),
                "status": o.get("status"),
                "reason": o.get("reason"),
                "created_at": o.get("created_at"),
            }
            for o in orders[:20]
        ],
        "risk_limits": p.get("limits"),
        "system": p.get("system"),
    }
    prompt = (
        "以下是最近的订单流水（含被拒绝的）与当时的系统状态：\n"
        f"{_j(facts)}\n\n"
        "请输出：\n## 逐笔说明（每笔被拒/异常的订单：原因是什么、属于风控还是配置问题）\n"
        "## 共性问题（如果多笔被同一原因拦下，指出来）\n"
        "## 修复步骤（按优先级，可执行；例如「去某页做某事」）\n"
        "## 需要人工确认的点\n"
        "注意：不要建议绕过任何风控护栏，也不要建议 AI 自动下单。" + _GUARD
    )
    return prompt, facts


def _l_order_diagnose(f: dict, _p: dict) -> str:
    orders = f.get("orders") or []
    bad = [o for o in orders if str(o.get("status", "")).upper() not in _OK_STATUS]
    lines = [f"【订单规则化诊断】共 {len(orders)} 笔，其中异常 {len(bad)} 笔", ""]
    if not bad:
        lines.append("没有发现被拒或异常的订单。")
        return "\n".join(lines)
    for o in bad[:12]:
        reason = str(o.get("reason") or "")
        hint = ""
        for code, txt in _REJECT_HINTS.items():
            if code.lower() in reason.lower() or code.lower() in str(o.get("status", "")).lower():
                hint = txt
                break
        lines.append(
            f"· #{o.get('id')} {o.get('symbol')} {o.get('side')} {o.get('qty')}"
            f" → {o.get('status')}｜原因：{reason or '未记录'}"
            + (f"\n   说明：{hint}" if hint else "")
        )
    lines.append("")
    lines.append("配置 LLM 后可获得共性问题归纳与修复步骤。")
    return "\n".join(lines)


_register(
    "order_diagnose",
    "订单与错误诊断",
    "解释被拒/异常订单的原因，归纳共性问题并给出修复步骤。",
    _b_order_diagnose,
    _l_order_diagnose,
    max_tokens=1300,
)


# ==================================================================
# 3. 情报解读（Intel 情报中心 / 公司情报）
# ==================================================================
def _b_intel_brief(p: dict) -> tuple[str, dict]:
    sym = str(p.get("symbol", "")).strip().upper()
    events = p.get("events") or []
    if not sym and not events:
        raise ValueError("缺少标的或事件")
    facts = {
        "symbol": sym,
        "company": p.get("company"),
        "window_days": p.get("window_days"),
        "pipeline": p.get("pipeline"),
        "events": [
            {
                "date": e.get("occurred_on") or e.get("published_at") or e.get("date"),
                "title": e.get("title"),
                "stage": e.get("stage"),
                "sentiment": e.get("sentiment"),
                "impact": e.get("impact"),
                "source": e.get("source"),
            }
            for e in events[:25]
        ],
        "latest_recommendation": p.get("recommendation"),
        "quote": p.get("quote"),
    }
    prompt = (
        "以下是某公司近期的情报事件流（含管道阶段：已敲定/在谈/传闻）与 AI 建议：\n"
        f"{_j(facts)}\n\n"
        "请输出：\n## 事件脉络（按时间讲清楚发生了什么，3–5 句）\n"
        "## 经营前瞻（这些事件对未来 1–2 个季度经营的可能影响，注意区分已敲定与传闻）\n"
        "## 管道质量（已敲定/在谈/传闻的比例说明了什么）\n"
        "## 需要继续跟踪的 3 个信号\n"
        "## 与行情的一致性（价格走势是否已反映这些事件）\n"
        "注意：传闻类事件必须明确标注为未证实。" + _GUARD
    )
    return prompt, facts


def _l_intel_brief(f: dict, _p: dict) -> str:
    ev = f.get("events") or []
    pipe = f.get("pipeline") or {}
    lines = [f"【情报规则化摘要 · {f.get('symbol') or '—'}】", ""]
    if pipe:
        lines.append(
            f"管道：已敲定 {pipe.get('confirmed', 0)}｜在谈 {pipe.get('negotiating', 0)}"
            f"｜传闻 {pipe.get('rumor', 0)}"
        )
    if not ev:
        lines.append("窗口期内没有事件记录。")
        return "\n".join(lines)
    lines.append("")
    lines.append(f"事件 {len(ev)} 条：")
    for e in ev[:10]:
        lines.append(
            f"· [{str(e.get('date') or '')[:10]}] {e.get('title')}"
            f"（{e.get('stage') or '—'}｜{e.get('sentiment') or '—'}）"
        )
    neg = [e for e in ev if str(e.get("sentiment", "")).lower() in ("negative", "bearish", "利空")]
    lines.append("")
    lines.append(f"其中偏负面 {len(neg)} 条。"
                 + ("负面占比较高，需谨慎。" if len(neg) * 2 > len(ev) else "整体情绪偏中性/正面。"))
    lines.append("配置 LLM 后可获得经营前瞻与跟踪信号。")
    return "\n".join(lines)


_register(
    "intel_brief",
    "情报解读",
    "把公司情报事件流解读成事件脉络、经营前瞻与跟踪信号。",
    _b_intel_brief,
    _l_intel_brief,
    max_tokens=1400,
)


# ==================================================================
# 4. 提案二次研判（AI 接管中心 · 批准前反方质询）
# ==================================================================
# 这是全平台**唯一真正动钱**的环节：人看到提案 → 批准 → 立即走完整下单链。
# 因此这里不做「再夸一遍提案」，而是固定扮演**反方**，尽力找出这笔提案的问题。
# 所有能确定性算出来的冲突（超限、追高、无止损、方向矛盾）都在
# `_proposal_checks` 里先算好，既喂给 LLM，也直接作为本地兜底 ——
# 避免让模型去「猜」本可以算准的数字。
_ACTION_CN = {"BUY": "买入", "SELL": "卖出", "CLOSE": "平仓"}


def _proposal_checks(prop: dict, sym: str, action: str, size_pct: float,
                     held: dict | None, positions: list, limits: dict,
                     snap: dict | None) -> list[dict]:
    """确定性交叉检查：返回 [{level, code, message}]。

    level: high（必须人工确认）/ mid（值得注意）/ info（提示）
    """
    out: list[dict] = []

    def add(level: str, code: str, message: str) -> None:
        out.append({"level": level, "code": code, "message": message})

    def _f(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    pos_cap = _f(limits.get("max_position_pct"))
    gross_cap = _f(limits.get("max_gross_exposure_pct"))
    n_cap = _f(limits.get("max_open_positions"))
    held_w = _f((held or {}).get("weight"))
    if held_w is None:
        held_w = _f((held or {}).get("weight_pct"))
    gross_now = sum(
        (_f(x.get("weight")) if _f(x.get("weight")) is not None else _f(x.get("weight_pct"))) or 0.0
        for x in positions
    )

    # 1) 方向与持仓是否自洽
    if action == "BUY":
        if held:
            if pos_cap and held_w is not None and held_w + size_pct > pos_cap + 1e-9:
                add("high", "MAX_POSITION",
                    f"加仓后 {sym} 权重约 {held_w + size_pct:.1f}%，"
                    f"超过单标的上限 {pos_cap:.0f}%（现持 {held_w:.1f}% + 本单 {size_pct:.1f}%）。"
                    "下单链会按上限缩减数量，实际成交可能小于提案。")
            else:
                add("info", "ADD_TO_POSITION",
                    f"{sym} 已有持仓（权重 {held_w:.1f}%），本单为加仓，请确认是有意为之。")
        elif n_cap and len(positions) >= n_cap:
            add("high", "MAX_OPEN_POSITIONS",
                f"当前已有 {len(positions)} 个持仓，达上限 {n_cap:.0f} 个；"
                "这是新开仓，下单链会直接拒单。")
        if gross_cap and gross_now + size_pct > gross_cap + 1e-9:
            add("high", "MAX_GROSS",
                f"开仓后总敞口约 {gross_now + size_pct:.1f}%，超过上限 {gross_cap:.0f}%。")
    elif action in ("SELL", "CLOSE"):
        if not held:
            lvl = "high" if action == "SELL" else "mid"
            add(lvl, "NO_POSITION",
                f"当前账户没有 {sym} 持仓，这笔{_ACTION_CN.get(action, action)}"
                + ("会被风控按裸卖空拦截（除非 allow_short=true）。"
                   if not limits.get("allow_short") else "属于裸卖空，请确认保证金占用。"))

    # 2) 止损 / 止盈
    if action == "BUY":
        if not prop.get("stop"):
            add("high", "NO_STOP", "提案未设置止损价 —— 这是最容易被忽略、代价最大的缺口。")
        if not prop.get("take_profit"):
            add("mid", "NO_TAKE_PROFIT", "提案未设置止盈价，退出完全依赖人工判断。")

    # 3) 限价偏离现价
    entry = _f(prop.get("entry"))
    live = _f((snap or {}).get("price"))
    if entry and live:
        dev = (entry / live - 1) * 100
        if abs(dev) >= 2:
            add("mid", "ENTRY_DEVIATION",
                f"提案入场价 {entry:g} 与现价 {live:g} 偏离 {dev:+.1f}%，"
                "限价单可能长期不成交（或一成交就是不利方向）。")

    # 4) 追高 / 方向与量化引擎矛盾
    ind = (snap or {}).get("indicators") or {}
    rsi = _f(ind.get("rsi14"))
    bias = ((snap or {}).get("local_engine") or {}).get("bias")
    if action == "BUY":
        if rsi is not None and rsi >= 70:
            add("mid", "OVERBOUGHT", f"现价 RSI(14)={rsi:.0f}，处于超买区，追多性价比低。")
        if bias == "空头":
            add("mid", "BIAS_CONFLICT",
                "平台本地量化引擎当前判为「空头」，与这笔买入方向相反。")
    elif action == "SELL" and bias == "多头":
        add("mid", "BIAS_CONFLICT", "平台本地量化引擎当前判为「多头」，与这笔卖出方向相反。")

    # 5) 单笔仓位是否过大
    if action == "BUY" and size_pct >= 20:
        add("mid", "SIZE_LARGE", f"单笔目标仓位 {size_pct:.1f}%，属重仓，请确认风险预算。")

    # 6) 依据是否为空
    if not str(prop.get("rationale") or "").strip():
        add("mid", "NO_RATIONALE", "提案没有给出决策依据（rationale 为空），无法复核逻辑。")

    return out


def _b_proposal_review(p: dict) -> tuple[str, dict]:
    prop = p.get("proposal") or {}
    sym = str(prop.get("symbol", "")).strip().upper()
    action = str(prop.get("action", "")).strip().upper()
    if not sym or not action:
        raise ValueError("缺少提案标的或方向")
    try:
        size_pct = float(prop.get("size_pct") or 0)
    except (TypeError, ValueError):
        size_pct = 0.0
    limits = p.get("limits") or {}
    raw_positions = p.get("positions") or []

    # 不同调用方给的持仓字段不一致（/ops/overview 只有 market_value，
    # /trading/positions 才有 weight）。这里统一补齐 weight（百分数），
    # 否则「加仓后是否超单标的上限」这类检查会静默失效。
    equity = None
    try:
        equity = float((p.get("account") or {}).get("equity") or 0) or None
    except (TypeError, ValueError):
        equity = None
    positions: list[dict] = []
    for x in raw_positions:
        y = dict(x)
        if y.get("weight") is None and y.get("weight_pct") is None and equity:
            try:
                y["weight"] = round(float(y.get("market_value") or 0) / equity * 100, 2)
            except (TypeError, ValueError):
                pass
        positions.append(y)

    held = next((x for x in positions if str(x.get("symbol", "")).upper() == sym), None)

    # 实时快照尽力而为：拿不到也要能复核（此时只少了行情相关的几条检查）
    snap: dict | None = None
    try:
        snap = _snap_facts(sym, "swing")
    except Exception:  # noqa: BLE001
        snap = None

    checks = _proposal_checks(prop, sym, action, size_pct, held, positions, limits, snap)
    gross_now = 0.0
    for x in positions:
        w = x.get("weight") if x.get("weight") is not None else x.get("weight_pct")
        try:
            gross_now += float(w or 0)
        except (TypeError, ValueError):
            pass

    facts = {
        "proposal": {
            "symbol": sym,
            "action": action,
            "action_cn": _ACTION_CN.get(action, action),
            "size_pct": size_pct,
            "entry": prop.get("entry"),
            "stop": prop.get("stop"),
            "take_profit": prop.get("take_profit"),
            "rationale": (str(prop.get("rationale") or ""))[:1500],
            "factors": prop.get("factors") or prop.get("factors_json"),
            "created_by": prop.get("created_by"),
        },
        "mode": p.get("mode"),
        "risk_limits": limits,
        "account": p.get("account"),
        "portfolio_summary": {
            "position_count": len(positions),
            "gross_exposure_pct": round(gross_now, 2),
            "same_symbol_position": held,
        },
        "live_snapshot": snap,
        "rule_checks": checks,
    }
    high = [c for c in checks if c["level"] == "high"]
    prompt = (
        "你是这笔交易提案的**风控反方**（devil's advocate）。"
        "你的任务不是复述提案，而是**尽力找出它的问题**。\n\n"
        "提案与当前账户/风控/行情的结构化事实：\n"
        f"{_j(facts)}\n\n"
        "其中 `rule_checks` 是平台已经用确定性规则算出的冲突项"
        "（high 表示下单链大概率会拦或造成超限），你必须逐条采纳，不要推翻。\n\n"
        "请严格按以下结构输出（总篇幅控制在 700 字以内）：\n"
        "## 结论（一句话：可直接批准 / 建议修改后再批 / 建议拒绝，并给最主要的一条理由）\n"
        "## 与持仓和风控的冲突（逐条，带具体数字；没有冲突就明说「未发现」）\n"
        "## 提案自身的弱点（依据是否充分、是否追高、止损止盈是否合理）\n"
        "## 若批准，最坏情况是什么（给一个具体的亏损/回撤情景，标出触发条件）\n"
        "## 批准前必须人工确认的 2–3 个问题（用问句）\n"
        "不要建议绕过任何风控护栏，也不要替用户做决定 —— 批准与否由人负责。" + _GUARD
    )
    return prompt, facts


def _l_proposal_review(f: dict, _p: dict) -> str:
    prop = f.get("proposal") or {}
    checks = f.get("rule_checks") or []
    high = [c for c in checks if c["level"] == "high"]
    mid = [c for c in checks if c["level"] == "mid"]
    sym = prop.get("symbol")
    act = prop.get("action_cn") or prop.get("action")
    lines = [
        f"【提案规则化复核 · {act} {sym} {_num(prop.get('size_pct'), 1)}%】",
        "",
    ]
    if high:
        lines.append("结论：存在高优先级冲突，建议修改后再批准。")
    elif mid:
        lines.append("结论：未发现硬性冲突，但有几处值得人工确认。")
    else:
        lines.append("结论：规则层面未发现冲突（注意：这不等于这笔交易合理）。")
    lines.append("")

    def dump(title: str, items: list[dict]) -> None:
        if not items:
            return
        lines.append(title)
        lines.extend(f"· {c['message']}" for c in items)
        lines.append("")

    dump("【必须确认（high）】", high)
    dump("【值得注意（mid）】", mid)
    info = [c for c in checks if c["level"] == "info"]
    dump("【提示】", info)

    # 最坏情况：用止损距离做保守估计
    stop = prop.get("stop")
    entry = prop.get("entry")
    size = prop.get("size_pct")
    try:
        if stop and entry and float(entry) > 0:
            loss_pct = (float(stop) / float(entry) - 1) * 100
            lines.append(
                f"最坏情况（触及止损）：单笔约 {loss_pct:.1f}% 的标的价格波动，"
                f"按 {_num(size, 1)}% 仓位计，对总权益影响约 {loss_pct * float(size or 0) / 100:.2f}%。"
            )
        else:
            lines.append("未设置止损，无法估算最坏情况 —— 这本身就是最大的风险点。")
    except (TypeError, ValueError):
        lines.append("止损/入场价数据不完整，无法估算最坏情况。")
    lines.append("")
    lines.append("配置 LLM 后可获得完整的反方质询与情景推演。")
    return "\n".join(lines)


_register(
    "proposal_review",
    "提案二次研判",
    "批准前对 AI 交易提案做反方质询：与持仓/风控的冲突、自身弱点与最坏情况。",
    _b_proposal_review,
    _l_proposal_review,
    max_tokens=1600,
    temperature=0.2,
)
