"""AI 任务 · 分析类（回测诊断 / 寻优解读 / 风控体检 / 组合点评）。"""
from __future__ import annotations

from typing import Any

from .ai_tasks import _GUARD, _j, _num, _pct, _register

# ==================================================================
# 1. 回测结果诊断（回测页）
# ==================================================================
def _b_backtest_diagnose(p: dict) -> tuple[str, dict]:
    metrics = p.get("metrics") or {}
    if not metrics:
        raise ValueError("缺少回测指标")
    facts = {
        "strategy": p.get("strategy"),
        "symbols": p.get("symbols"),
        "period": p.get("period"),
        "params": p.get("params"),
        "cost_model": p.get("cost_model"),
        "metrics": metrics,
    }
    prompt = (
        "以下是一次策略回测的配置与绩效指标：\n"
        f"{_j(facts)}\n\n"
        "请按这个顺序诊断：\n"
        "## 结论（这套结果可信度如何，一句话）\n"
        "## 过拟合风险（交易笔数、参数自由度、样本长度、换手率各自意味着什么）\n"
        "## 收益质量（超额来自 Alpha 还是 Beta；回撤与水下期是否可承受）\n"
        "## 三个具体的改进方向（可执行，不要泛泛而谈）\n"
        "## 上线前必须补做的验证\n"
        "特别要求：若交易笔数过少（<30）、参数明显挑过、或 Alpha≈0 而 Beta≈1，"
        "必须明确指出，不要为了好看而美化结论。" + _GUARD
    )
    return prompt, facts


def _l_backtest_diagnose(f: dict, _p: dict) -> str:
    m = f.get("metrics") or {}

    def g(k: str) -> Any:
        return m.get(k)

    lines = [f"【回测规则化诊断 · {f.get('strategy')}】", ""]
    lines.append(
        f"累计收益 {_pct(g('total_return'), 1)}｜年化 {_pct(g('cagr'), 1)}"
        f"｜夏普 {_num(g('sharpe'))}｜最大回撤 {_pct(g('max_drawdown'), 1)}"
    )
    lines.append(
        f"交易 {_num(g('trades'), 0)} 笔｜胜率 {_pct(g('win_rate'), 1)}"
        f"｜盈亏比 {_num(g('profit_factor'))}｜换手 {_pct(g('turnover'), 1)}"
    )
    lines.append("")
    flags: list[str] = []
    trades = g("trades")
    if isinstance(trades, (int, float)):
        if trades < 30:
            flags.append(f"交易笔数仅 {int(trades)} 笔，统计意义弱，结果高度依赖少数几笔运气。")
        elif trades > 800:
            flags.append(f"交易 {int(trades)} 笔且换手 {_pct(g('turnover'), 1)}，"
                         "交易成本与滑点敏感度极高。")
    sh = g("sharpe")
    if isinstance(sh, (int, float)) and sh < 0.5:
        flags.append(f"夏普 {sh:.2f} < 0.5，风险调整后收益偏弱。")
    dd = g("max_drawdown")
    if isinstance(dd, (int, float)) and abs(dd) > 0.3:
        flags.append(f"最大回撤 {_pct(dd, 1)}，超出多数人可承受区间，需先解决回撤再谈收益。")
    alpha, beta = g("alpha"), g("beta")
    if isinstance(alpha, (int, float)) and isinstance(beta, (int, float)):
        if abs(alpha) < 0.02 and beta > 0.8:
            flags.append(f"Alpha {_pct(alpha, 1)} 接近 0 而 Beta {beta:.2f} 偏高 —— "
                         "本质更接近「加了杠杆的买入持有」。")
    if not flags:
        flags.append("未触发内置的规则化红旗；仍需人工检查参数是否被挑过。")
    lines.extend(f"· {x}" for x in flags)
    lines.append("")
    lines.append("配置 LLM 后可获得完整的过拟合诊断与改进方向。")
    return "\n".join(lines)


_register(
    "backtest_diagnose",
    "回测结果诊断",
    "诊断回测结果的过拟合风险、收益质量与改进方向。",
    _b_backtest_diagnose,
    _l_backtest_diagnose,
    max_tokens=1400,
)


# ==================================================================
# 2. 寻优结果解读（优化页）
# ==================================================================
def _b_optimize_review(p: dict) -> tuple[str, dict]:
    facts = {
        "method": p.get("method"),
        "symbols": p.get("symbols"),
        "objective": p.get("objective"),
        "grid_size": p.get("grid_size"),
        "best": p.get("best"),
        "best_metrics": p.get("best_metrics"),
        "baseline": p.get("baseline"),
        "top_neighbors": (p.get("top_neighbors") or [])[:12],
        "constraints": p.get("constraints"),
    }
    if not facts["best"]:
        raise ValueError("缺少寻优结果")
    prompt = (
        "以下是组合权重寻优（或参数寻优）的结果：\n"
        f"{_j(facts)}\n\n"
        "请输出：\n## 结论（这个最优解可信吗）\n"
        "## 参数稳定性（最优解周边邻居的表现是否接近 —— 平台期还是孤峰）\n"
        "## 与基准/等权相比，超额来自哪里，代价是什么\n"
        "## 落地建议（是否直接采用、要不要收缩权重、需不需要再加约束）" + _GUARD
    )
    return prompt, facts


def _l_optimize_review(f: dict, _p: dict) -> str:
    best = f.get("best") or {}
    lines = [f"【寻优规则化解读 · {f.get('method')}｜目标 {f.get('objective')}】", ""]
    if isinstance(best, dict):
        for k, v in list(best.items())[:8]:
            lines.append(f"· {k}: {_num(v, 4) if isinstance(v, (int, float)) else v}")
    bm = f.get("best_metrics") or {}
    if bm:
        lines.append("")
        lines.append(
            f"最优解指标：年化 {_pct(bm.get('cagr'), 1)}｜波动 {_pct(bm.get('volatility'), 1)}"
            f"｜夏普 {_num(bm.get('sharpe'))}｜最大回撤 {_pct(bm.get('max_drawdown'), 1)}"
        )
    n = len(f.get("top_neighbors") or [])
    lines.append("")
    lines.append(
        f"已评估 {f.get('grid_size') or '—'} 组，前 {n} 组邻居数据已附带；"
        "邻居表现接近 = 参数平台期（较可信），差距悬殊 = 孤峰（过拟合嫌疑）。"
    )
    lines.append("配置 LLM 后可获得参数稳定性与落地建议。")
    return "\n".join(lines)


_register(
    "optimize_review",
    "寻优结果解读",
    "解读组合寻优结果，判断参数稳定性与过拟合风险。",
    _b_optimize_review,
    _l_optimize_review,
    max_tokens=1200,
)


# ==================================================================
# 3. 风控体检（风控中心）
# ==================================================================
def _b_risk_review(p: dict) -> tuple[str, dict]:
    facts = {
        "config": p.get("config"),
        "exposure": p.get("exposure"),
        "account": p.get("account"),
        "positions": (p.get("positions") or [])[:20],
        "recent_rejections": (p.get("recent_rejections") or [])[:10],
    }
    if not facts["config"]:
        raise ValueError("缺少风控配置")
    prompt = (
        "以下是当前的风控参数、账户敞口与持仓：\n"
        f"{_j(facts)}\n\n"
        "请做一次风控体检：\n## 总体评价（这套参数与当前敞口是否匹配，一句话）\n"
        "## 参数之间的内部矛盾（例如单标的上限 × 持仓数 与 总敞口上限 的关系）\n"
        "## 当前敞口的具体风险点（集中度、方向暴露、币种）\n"
        "## 建议调整的 2–3 条（给具体数值区间，说明理由）\n"
        "## 极端行情下这套参数会怎样（给出情景推演）" + _GUARD
    )
    return prompt, facts


def _l_risk_review(f: dict, _p: dict) -> str:
    c = f.get("config") or {}
    e = f.get("exposure") or {}
    lines = ["【风控规则化体检】", ""]
    pos_cap = c.get("max_position_pct")
    gross_cap = c.get("max_gross_exposure_pct")
    n_cap = c.get("max_open_positions")
    lines.append(
        f"单标的上限 {_num(pos_cap, 1)}%｜总敞口上限 {_num(gross_cap, 1)}%"
        f"｜最大持仓数 {_num(n_cap, 0)}｜单日亏损上限 {_num(c.get('max_daily_loss_pct'), 1)}%"
        f"｜回撤熔断 {_num(c.get('max_drawdown_pct'), 1)}%"
    )
    flags: list[str] = []
    if all(isinstance(x, (int, float)) for x in (pos_cap, n_cap, gross_cap)):
        theoretical = pos_cap * n_cap
        if theoretical < gross_cap:
            flags.append(
                f"参数不自洽：单标的上限 {pos_cap:.0f}% × 最多 {n_cap:.0f} 个持仓 = "
                f"{theoretical:.0f}%，低于总敞口上限 {gross_cap:.0f}% —— "
                "总敞口约束实际上永远不会被触发。"
            )
        else:
            flags.append(
                f"理论上限 {theoretical:.0f}% ≥ 总敞口上限 {gross_cap:.0f}%，"
                "总敞口是真正的约束条件（合理）。"
            )
    if isinstance(e.get("gross_pct"), (int, float)) and isinstance(gross_cap, (int, float)):
        if e["gross_pct"] > gross_cap * 0.9:
            flags.append(f"当前总敞口 {e['gross_pct']:.1f}% 已接近上限 {gross_cap:.0f}%，"
                         "新开仓空间很小。")
    if c.get("allow_short"):
        flags.append("做空已开启：请确认组合层面同时暴露多空两腿时的净敞口与保证金占用。")
    if not flags:
        flags.append("未触发内置规则化红旗。")
    lines.extend(f"· {x}" for x in flags)
    lines.append("")
    lines.append("配置 LLM 后可获得情景推演与具体调整建议。")
    return "\n".join(lines)


_register(
    "risk_review",
    "风控体检",
    "体检风控参数的自洽性与当前敞口风险，给出调整建议。",
    _b_risk_review,
    _l_risk_review,
    max_tokens=1300,
)


# ==================================================================
# 4. 持仓组合点评（持仓页）
# ==================================================================
def _b_portfolio_review(p: dict) -> tuple[str, dict]:
    facts = {
        "account": p.get("account"),
        "exposure": p.get("exposure"),
        "limits": p.get("limits"),
        "positions": [
            {
                "symbol": x.get("symbol"),
                "qty": x.get("quantity"),
                "avg_cost": x.get("avg_cost"),
                "last": x.get("last_price"),
                "unrealized_pnl": x.get("unrealized_pnl"),
                "unrealized_pct": x.get("unrealized_pct"),
                "weight_pct": x.get("weight") if x.get("weight") is not None else x.get("weight_pct"),
                "currency": x.get("currency"),
            }
            for x in (p.get("positions") or [])[:25]
        ],
        "recent_orders": (p.get("recent_orders") or [])[:15],
    }
    if not facts["positions"]:
        raise ValueError("当前没有持仓")
    prompt = (
        "以下是当前账户与持仓明细：\n"
        f"{_j(facts)}\n\n"
        "请输出：\n## 组合画像（风格、集中度、方向暴露）\n"
        "## 风险体检（单标的集中度、行业/币种集中、盈亏结构是否健康）\n"
        "## 值得关注的持仓（各一句：为什么值得关注，该继续持有还是复核）\n"
        "## 再平衡思路（只给方向与优先级，不要给具体下单指令）\n"
        "## 需要补充的信息\n" + _GUARD
    )
    return prompt, facts


def _l_portfolio_review(f: dict, _p: dict) -> str:
    ps = f.get("positions") or []
    lines = [f"【组合规则化点评】共 {len(ps)} 个持仓", ""]
    win = [p for p in ps if (p.get("unrealized_pnl") or 0) > 0]
    lines.append(f"盈利 {len(win)} 个｜亏损 {len(ps) - len(win)} 个")
    top = sorted(ps, key=lambda p: -(p.get("weight_pct") or 0))[:5]
    lines.append("")
    lines.append("占比前列：")
    for p in top:
        lines.append(
            f"· {p.get('symbol')}｜权重 {_num(p.get('weight_pct'), 1)}%"
            f"｜浮动盈亏 {_num(p.get('unrealized_pnl'))}（{_num(p.get('unrealized_pct'))}%）"
        )
    if ps and (ps[0].get("weight_pct") or 0) > 40:
        lines.append(f"⚠ {ps[0].get('symbol')} 占比 {_num(ps[0].get('weight_pct'), 1)}%，"
                     "单标的集中度偏高。")
    lines.append("")
    lines.append("配置 LLM 后可获得组合画像与再平衡思路。")
    return "\n".join(lines)


_register(
    "portfolio_review",
    "持仓组合点评",
    "点评当前持仓的风格、集中度与盈亏结构，给出再平衡方向。",
    _b_portfolio_review,
    _l_portfolio_review,
    max_tokens=1400,
)


# ==================================================================
# 5. 交易复盘（持仓页 · 周期复盘）
# ==================================================================
# 复盘的价值不在「赚了多少」，而在「决策链条哪里断了」：
# 被风控拦下的订单在反复暴露同一个配置问题吗？止损是不是形同虚设？
# 是不是在同一类标的上反复进出（过度交易）？
# 这些都能从订单流水 + 决策日志 + 账户盈亏里确定性算出来。
_FILLED = ("FILLED", "PARTIALLY_FILLED", "SUBMITTED", "PRESUBMITTED", "PENDING", "PENDINGSUBMIT")
_BAD = ("REJECTED", "CANCELLED", "INACTIVE", "ERROR", "FAILED")


def _period_stats(orders: list[dict], positions: list[dict], account: dict,
                  decisions: list[dict]) -> dict:
    """把订单/持仓/决策压成一组确定性统计量（喂 LLM + 本地兜底共用）。"""
    filled, bad = [], []
    buys = sells = 0
    commission = 0.0
    by_symbol: dict[str, int] = {}
    for o in orders:
        st = str(o.get("status") or "").upper()
        sym = str(o.get("symbol") or "").upper()
        if sym:
            by_symbol[sym] = by_symbol.get(sym, 0) + 1
        try:
            commission += float(o.get("commission") or 0)
        except (TypeError, ValueError):
            pass
        if st in _BAD:
            bad.append(o)
        else:
            filled.append(o)
            side = str(o.get("side") or "").upper()
            if side == "BUY":
                buys += 1
            elif side == "SELL":
                sells += 1

    # 被拒原因频次（同一 code 反复出现 = 配置问题，不是偶发）
    reasons: dict[str, int] = {}
    for o in bad:
        r = str(o.get("reason") or "").strip() or "未记录原因"
        reasons[r] = reasons.get(r, 0) + 1

    unreal = 0.0
    winners, losers = 0, 0
    for p in positions:
        try:
            v = float(p.get("unrealized_pnl") or 0)
        except (TypeError, ValueError):
            v = 0.0
        unreal += v
        if v > 0:
            winners += 1
        elif v < 0:
            losers += 1

    return {
        "order_count": len(orders),
        "filled_count": len(filled),
        "rejected_count": len(bad),
        "buy_count": buys,
        "sell_count": sells,
        "distinct_symbols": len(by_symbol),
        "top_symbols": sorted(by_symbol.items(), key=lambda kv: -kv[1])[:8],
        "commission_total": round(commission, 2),
        "reject_reasons": sorted(reasons.items(), key=lambda kv: -kv[1])[:6],
        "position_count": len(positions),
        "unrealized_pnl_total": round(unreal, 2),
        "winners": winners,
        "losers": losers,
        "realized_pnl": account.get("realized_pnl"),
        "equity": account.get("equity"),
        "day_pnl": account.get("day_pnl"),
        "decision_count": len(decisions),
        "rejected_by_risk": sum(1 for d in decisions
                                if "REJECT" in str(d.get("decision") or "").upper()
                                or "拒绝" in str(d.get("decision") or "")),
    }


def _b_period_review(p: dict) -> tuple[str, dict]:
    orders = p.get("orders") or []
    positions = p.get("positions") or []
    decisions = p.get("decisions") or []
    account = p.get("account") or {}
    if not orders and not positions:
        raise ValueError("没有订单或持仓可供复盘")
    stats = _period_stats(orders, positions, account, decisions)
    facts = {
        "period": p.get("period") or "近期",
        "stats": stats,
        "recent_orders": [
            {
                "ts": o.get("created_at") or o.get("ts"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "qty": o.get("quantity"),
                "filled_qty": o.get("filled_qty"),
                "avg_fill_price": o.get("avg_fill_price"),
                "status": o.get("status"),
                "reason": (str(o.get("reason") or ""))[:200],
            }
            for o in orders[:40]
        ],
        "positions": [
            {
                "symbol": x.get("symbol"),
                "qty": x.get("quantity"),
                "avg_cost": x.get("avg_cost"),
                "last": x.get("last_price"),
                "unrealized_pnl": x.get("unrealized_pnl"),
                "unrealized_pct": x.get("unrealized_pct"),
                "weight_pct": x.get("weight") if x.get("weight") is not None else x.get("weight_pct"),
            }
            for x in positions[:25]
        ],
        "recent_decisions": [
            {
                "ts": d.get("ts"),
                "actor": d.get("actor"),
                "action": d.get("action"),
                "symbol": d.get("symbol"),
                "decision": (str(d.get("decision") or ""))[:200],
            }
            for d in decisions[:30]
        ],
    }
    prompt = (
        "以下是一个交易账户在一段时间内的**订单流水、持仓与决策日志**，"
        "以及平台预先算好的确定性统计 `stats`：\n"
        f"{_j(facts)}\n\n"
        "请做一次交易复盘。重点不是复述盈亏数字，而是**找出决策链条上的问题**。"
        "严格按以下结构输出（总篇幅 700 字以内）：\n"
        "## 这段做了什么（3–4 句：交易频率、方向偏好、标的集中度）\n"
        "## 盈亏归因（已实现/浮动盈亏、赢家与输家各说明了什么）\n"
        "## 决策质量问题（重点看 stats.reject_reasons —— "
        "同一原因反复出现说明是配置问题而非偶发；再看是否过度交易、是否缺止损）\n"
        "## 三个可执行的改进项（具体到「去某页改某配置」，不要泛泛而谈）\n"
        "## 需要补充的数据（如果现有数据不足以支撑某个判断，直说）\n"
        "特别要求：如果样本太小（订单少于 20 笔）或时间跨度太短，"
        "必须明确指出「结论的统计意义有限」，不要过度解读。" + _GUARD
    )
    return prompt, facts


def _l_period_review(f: dict, _p: dict) -> str:
    s = f.get("stats") or {}
    lines = [f"【交易复盘 · {f.get('period')}】", ""]
    lines.append(
        f"订单 {s.get('order_count', 0)} 笔（成交 {s.get('filled_count', 0)}｜"
        f"异常 {s.get('rejected_count', 0)}）｜买入 {s.get('buy_count', 0)}｜卖出 {s.get('sell_count', 0)}"
    )
    lines.append(
        f"涉及 {s.get('distinct_symbols', 0)} 个标的｜手续费合计 {_num(s.get('commission_total'))}"
    )
    lines.append(
        f"账户：权益 {_num(s.get('equity'))}｜已实现盈亏 {_num(s.get('realized_pnl'))}"
        f"｜浮动盈亏 {_num(s.get('unrealized_pnl_total'))}"
    )
    lines.append("")

    flags: list[str] = []
    n = s.get("order_count") or 0
    if n < 20:
        flags.append(f"订单仅 {n} 笔，样本偏小，以下结论的统计意义有限。")
    if s.get("rejected_count") and n:
        ratio = s["rejected_count"] / n
        if ratio >= 0.3:
            flags.append(
                f"异常订单占比 {ratio * 100:.0f}%（{s['rejected_count']}/{n}）偏高 —— "
                "多半是配置问题而非偶发，建议逐条看被拒原因。"
            )
    rr = s.get("reject_reasons") or []
    if rr:
        top_reason, top_cnt = rr[0]
        if top_cnt >= 2:
            flags.append(f"最高频被拒原因出现 {top_cnt} 次：「{top_reason[:80]}」—— 反复出现说明需要改配置。")
    if s.get("buy_count") and s.get("sell_count") and n:
        if s["buy_count"] + s["sell_count"] > 0:
            churn = s["buy_count"] / max(1, s["buy_count"] + s["sell_count"])
            if 0.4 <= churn <= 0.6 and n >= 40:
                flags.append(f"买卖接近对半（{s['buy_count']} 买 / {s['sell_count']} 卖），"
                             "注意是否在反复进出、被手续费侵蚀。")
    w, l = s.get("winners", 0), s.get("losers", 0)
    if w or l:
        flags.append(f"当前持仓中盈利 {w} 个、亏损 {l} 个"
                     + ("（亏损面更大，检查是否该止损的没止）。" if l > w else "。"))
    if s.get("unrealized_pnl_total") is not None and (s.get("unrealized_pnl_total") or 0) < 0:
        flags.append("浮动盈亏为负：确认这些亏损是否仍在止损纪律之内。")
    if not flags:
        flags.append("未触发内置的规则化红旗。")
    lines.extend(f"· {x}" for x in flags)
    lines.append("")
    lines.append("配置 LLM 后可获得盈亏归因与可执行的改进项。")
    return "\n".join(lines)


_register(
    "period_review",
    "交易复盘",
    "用订单流水、持仓与决策日志复盘一段时间的交易：盈亏归因与决策链条问题。",
    _b_period_review,
    _l_period_review,
    max_tokens=1600,
)
