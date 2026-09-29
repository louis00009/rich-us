"""选股中心 —— 白盒信号引擎（机会提示 / 风险提示 / 今日关注）。

与 scoring.py 同一立场：这是「筛选辅助 + 解释」，**不是买入信号**。
每个信号都是确定性规则：触发条件、含义、局限全部公开在 SIGNAL_DEFS，
前端渲染完整目录 —— 用户必须能看到「为什么亮这个灯」，也必须能看到
「这个灯什么时候会骗人」。

设计原则
--------
1. 机会信号必须有**至少两个独立证据**（如「行业里便宜」+「盈利强」）。
   单一指标亮灯是噪音放大器：RSI<30 单独出现大概率只是跌得多的弱者。
2. 风险信号是「需要再看一眼」的提示，不是否定 —— 强趋势里 RSI>70 会
   长期钝化，把超买当卖出信号会被趋势教育。
3. 缺数据绝不触发信号（全部 isinstance 前置检查），宁缺勿滥：
   数据未就绪时页面安静地没有提示，好过一条错误提示。
4. 每条 reason 带触发时的**具体数值**，让用户能自行验算。
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 信号目录：单一事实源。后端注入信号、前端渲染说明，都从这里出发。
# kind: opportunity = 机会（值得进一步看）；warning = 风险（需要再看一眼）。
# ---------------------------------------------------------------------------
SIGNAL_DEFS: list[dict[str, str]] = [
    # ---------------- 机会 ----------------
    {
        "key": "value_anchor",
        "label": "价值锚",
        "kind": "opportunity",
        "brief": "同行业里便宜，且盈利能力强",
        "condition": "PE 处于同行业后 30% 分位，且 ROE ≥ 15%，且当前未亏损",
        "logic": "「低估值 + 高 ROE」是最经典的组合筛选：又便宜又能赚钱。PE 用行业内分位而不是绝对值 —— 银行 PE 14 和软件 PE 40 都可能是合理的，绝对 PE 会把整个金融板块误判成『最便宜』。",
        "limitation": "行业整体高估时，分位偏低依然会亮灯；PE 由 TTM 数据计算，一次性损益（卖资产、大额减值）会失真。周期股在盈利顶点 PE 最低，是典型陷阱。",
    },
    {
        "key": "quality_trend",
        "label": "优质趋势",
        "kind": "opportunity",
        "brief": "盈利能力强 + 均线多头排列 + 跑赢大盘",
        "condition": "ROE ≥ 15%，且现价 > MA20 > MA60 > MA200（多头排列），且近 1 年相对 SPY 超额收益 > 0",
        "logic": "质量决定『能不能买』，趋势决定『什么时候买』。基本面强 + 三个周期均线依次抬升 + 已跑赢大盘，是动量策略与质量策略共振的状态。",
        "limitation": "三者同时满足时估值往往已不便宜（强势股很少便宜）。趋势是滞后指标：多头排列形成时涨幅已发生一部分。",
    },
    {
        "key": "oversold_bounce",
        "label": "超跌关注",
        "kind": "opportunity",
        "brief": "深度回撤 + 短期超卖，反弹候选",
        "condition": "距 52 周高点回撤 ≥ 30%，且 RSI(14) < 40，且当前未亏损",
        "logic": "跌得深 + 短期卖压接近衰竭（RSI 低），是超跌反弹策略的经典入场区。排除亏损标的 —— 亏损股的『超跌』往往是基本面坏了，跌得多是应该的。",
        "limitation": "『便宜』不等于『会涨』：回撤可能是基本面恶化所致（业绩暴雷、行业拐点）。请先看公司档案确认跌的原因，再谈反弹。",
    },
    {
        "key": "new_high_break",
        "label": "强势新高",
        "kind": "opportunity",
        "brief": "逼近 52 周新高 + 跑赢大盘 + 站上 200 日线",
        "condition": "距 52 周高点不足 3%，且近 1 年相对 SPY 超额收益 > 0，且现价站上 MA200",
        "logic": "52 周新高常被视为压力位突破：上方没有套牢盘，且能创新高本身就证明有资金持续买入。趋势跟踪策略（如欧奈尔体系）把创新高作为核心买点。",
        "limitation": "创新高 ≠ 便宜：此时 PE 往往也在高位，追高需自担回撤风险。假突破存在，创新高后回落 5~10% 很常见。",
    },
    {
        "key": "income_defense",
        "label": "高股息",
        "kind": "opportunity",
        "brief": "股息率 ≥ 3%，且波动可控",
        "condition": "股息率 ≥ 3% 且年化波动 ≤ 40%（无波动数据时要求股息率 ≥ 3.5% 才亮灯）",
        "logic": "股息率明显高于无风险利率（美债）时，持有期的现金回报有吸引力；波动可控说明分红大概率不必削减。适合追求现金流、回撤敏感的配置。",
        "limitation": "分红政策会变；高股息常出现在成熟低增长行业（能源、公用事业、金融），错过成长是机会成本。",
    },
    # ---------------- 风险 ----------------
    {
        "key": "overbought",
        "label": "短期超买",
        "kind": "warning",
        "brief": "RSI(14) > 75，短期涨幅过大",
        "condition": "RSI(14) > 75",
        "logic": "短期买盘占绝对优势，历史统计上继续追高的赔率变差。更适合当作『别在这里重仓追』的提醒，而不是卖出信号。",
        "limitation": "强趋势中 RSI 可以长期停在 70 以上（钝化）—— 2013~2020 的 NVDA 式走势里『超买』能持续数月。不要单独把它当卖出依据。",
    },
    {
        "key": "high_vol",
        "label": "高波动",
        "kind": "warning",
        "brief": "年化波动率 > 60%，仓位需要相应减小",
        "condition": "年化波动率 > 60%",
        "logic": "波动率是仓位管理的锚：同样 1 万元，60% 波动的标的带给组合的回撤风险是 20% 波动标的的三倍。综合评分里它也是扣分项。",
        "limitation": "波动率只描述『晃得厉害不厉害』，不区分上涨还是下跌 —— 正在翻倍的股票波动率同样高。",
    },
    {
        "key": "div_trap",
        "label": "股息陷阱嫌疑",
        "kind": "warning",
        "brief": "股息率 > 8%，很可能是股价大跌推高",
        "condition": "股息率 > 8%",
        "logic": "股息率 = 分红 ÷ 股价。超过 8% 通常不是『分红变多』而是『股价崩了』，且市场在定价『分红不可持续』。历史上大量高息股在减息公告日再跌一轮。",
        "limitation": "REITs、MLP 等结构化高息品种例外 —— 它们的分红政策天然高派息率，需按行业惯例判断。",
    },
    {
        "key": "weak_trend",
        "label": "趋势破位",
        "kind": "warning",
        "brief": "深度跌破 200 日线，且近 3 个月仍在下跌",
        "condition": "现价低于 MA200 达 15% 以上，且近 63 个交易日累计跌幅超过 5%",
        "logic": "MA200 是最经典的中长期多空分界，深跌其下且短期仍在走弱，说明下跌趋势没有结束的迹象。左侧接飞刀前先问自己依据是什么。",
        "limitation": "极端恐慌（如 2020-03）时几乎所有股票都触发，之后往往就是大底 —— 配合基本面与估值判断，不要机械执行。",
    },
    {
        "key": "pe_distorted",
        "label": "估值失真",
        "kind": "warning",
        "brief": "PE > 200，数字已不可比",
        "condition": "PE(TTM) > 200（盈利趋近于零或为一次性损益）",
        "logic": "PE 的分母太小会让数字失去意义：盈利刚好打平时 PE 可以是任意大。此时『PE 高 = 贵』的直觉完全失效，估值维度评分也已将其排除。",
        "limitation": "极少数高研发投入公司（早期 AMZN、NVDA 低谷）PE 超高但随后盈利爆发 —— 这正是 PE 指标的盲区，需看远期一致预期而非当期 TTM。",
    },
]

CATALOG: dict[str, dict[str, str]] = {d["key"]: d for d in SIGNAL_DEFS}

_OPP_KEYS = [d["key"] for d in SIGNAL_DEFS if d["kind"] == "opportunity"]


# ---------------------------------------------------------------------------
# 规则函数：返回动态 reason（None = 未触发）。所有取值先过 isinstance。
# ---------------------------------------------------------------------------
def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _rule_value_anchor(r: dict[str, Any]) -> str | None:
    if r.get("pe_state") == "loss":
        return None
    pct = _num(r.get("pe_pct"))
    roe = _num(r.get("roe"))
    if pct is None or roe is None:
        return None
    if pct <= 30 and roe >= 15:
        return f"同行业 PE 第 {pct:.0f} 分位（偏便宜），ROE {roe:.0f}%（盈利强）"
    return None


def _rule_quality_trend(r: dict[str, Any]) -> str | None:
    roe = _num(r.get("roe"))
    excess = _num(r.get("excess_1y"))
    if roe is None or roe < 15:
        return None
    if r.get("ma_bull") is not True or excess is None or excess <= 0:
        return None
    return f"ROE {roe:.0f}%，均线多头排列，近 1 年跑赢 SPY {excess:.0f} 个百分点"


def _rule_oversold_bounce(r: dict[str, Any]) -> str | None:
    if r.get("pe_state") == "loss":
        return None
    fh = _num(r.get("pct_from_high"))
    rsi = _num(r.get("rsi14"))
    if fh is None or rsi is None:
        return None
    if fh <= -30 and rsi < 40:
        return f"距 52 周高 {fh:.0f}%（深度回撤），RSI {rsi:.0f}（短期超卖）"
    return None


def _rule_new_high_break(r: dict[str, Any]) -> str | None:
    fh = _num(r.get("pct_from_high"))
    excess = _num(r.get("excess_1y"))
    rel200 = _num(r.get("ma200_rel"))
    if fh is None or excess is None or rel200 is None:
        return None
    if fh >= -3 and excess > 0 and rel200 > 0:
        return f"距 52 周高仅 {fh:.1f}%（逼近新高），近 1 年跑赢 SPY {excess:.0f} pct，站上 MA200"
    return None


def _rule_income_defense(r: dict[str, Any]) -> str | None:
    dy = _num(r.get("div_yield"))
    if dy is None:
        return None
    vol = _num(r.get("vol_ann"))
    # 无波动数据时提高股息门槛（3.5%），避免盲区亮灯
    if vol is not None:
        if dy >= 3 and vol <= 40:
            return f"股息率 {dy:.1f}%，年化波动 {vol:.0f}%（可控）"
    elif dy >= 3.5:
        return f"股息率 {dy:.1f}%（波动数据未就绪，按更高门槛判定）"
    return None


def _rule_overbought(r: dict[str, Any]) -> str | None:
    rsi = _num(r.get("rsi14"))
    if rsi is not None and rsi > 75:
        return f"RSI {rsi:.0f}（>75），短期涨幅过大"
    return None


def _rule_high_vol(r: dict[str, Any]) -> str | None:
    vol = _num(r.get("vol_ann"))
    if vol is not None and vol > 60:
        return f"年化波动 {vol:.0f}%（>60%），仓位需相应减小"
    return None


def _rule_div_trap(r: dict[str, Any]) -> str | None:
    dy = _num(r.get("div_yield"))
    if dy is not None and dy > 8:
        return f"股息率 {dy:.1f}%（>8%），多为股价大跌推高，警惕分红削减"
    return None


def _rule_weak_trend(r: dict[str, Any]) -> str | None:
    rel200 = _num(r.get("ma200_rel"))
    r3m = _num(r.get("r3m"))
    if rel200 is None or r3m is None:
        return None
    if rel200 <= -15 and r3m <= -5:
        return f"现价低于 MA200 达 {abs(rel200):.0f}%，近 3 月再跌 {abs(r3m):.0f}%，下跌趋势未止"
    return None


def _rule_pe_distorted(r: dict[str, Any]) -> str | None:
    pe = _num(r.get("pe_ttm"))
    if pe is not None and pe > 200:
        return f"PE {pe:.0f}（>200），分母塌缩，数字已不可比"
    return None


_RULES = {
    "value_anchor": _rule_value_anchor,
    "quality_trend": _rule_quality_trend,
    "oversold_bounce": _rule_oversold_bounce,
    "new_high_break": _rule_new_high_break,
    "income_defense": _rule_income_defense,
    "overbought": _rule_overbought,
    "high_vol": _rule_high_vol,
    "div_trap": _rule_div_trap,
    "weak_trend": _rule_weak_trend,
    "pe_distorted": _rule_pe_distorted,
}


def signals_for_row(r: dict[str, Any]) -> list[dict[str, str]]:
    """计算一行触发的全部信号。输出按 目录顺序 → 每条带动态 reason。"""
    out: list[dict[str, str]] = []
    for d in SIGNAL_DEFS:
        try:
            reason = _RULES[d["key"]](r)
        except Exception:  # noqa: BLE001 —— 单条信号计算失败不影响其他信号
            reason = None
        if reason:
            out.append({"key": d["key"], "kind": d["kind"], "label": d["label"], "reason": reason})
    return out


def attach_signals(rows: list[dict[str, Any]]) -> None:
    """给每行注入 signals / signal_count（机会数）/ risk_count（风险数）。

    调用时机：必须在 `attach_scores` 之后（依赖 pe_pct / roe / 技术指标）、
    筛选之前（信号本身也要可筛选）。纯内存计算，503 行耗时 < 10ms。
    """
    for r in rows:
        sigs = signals_for_row(r)
        r["signals"] = sigs
        r["signal_count"] = sum(1 for s in sigs if s["kind"] == "opportunity")
        r["risk_count"] = sum(1 for s in sigs if s["kind"] == "warning")


def pick_focus(rows: list[dict[str, Any]], k: int = 12) -> list[dict[str, Any]]:
    """今日关注：全池（筛选前）里挑机会信号最多、评分最高的前 k 只。

    两级挑选：
      1) 机会信号 ≥ 2 的（多证据共振），按（机会数，评分）降序 —— 最值得看；
      2) 不足 k 只时，用「机会信号 = 1 且综合评分 ≥ 70」的高分标的补足 ——
         否则常态下多证据标的太少，今日关注几乎总是空白，功能形同虚设。
    排除亏损标的 —— 亏损公司的「便宜」多数是价值陷阱。
    """

    def _score(r: dict[str, Any]) -> float:
        v = r.get("score")
        return float(v) if isinstance(v, (int, float)) else -1.0

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    multi = [r for r in rows if r.get("signal_count", 0) >= 2 and r.get("pe_state") != "loss"]
    multi.sort(key=lambda r: (r.get("signal_count", 0), _score(r)), reverse=True)
    for r in multi[:k]:
        picked.append(r)
        seen.add(str(r.get("symbol")))

    if len(picked) < k:
        single = [
            r for r in rows
            if r.get("signal_count", 0) == 1 and r.get("pe_state") != "loss"
            and isinstance(r.get("score"), (int, float)) and r["score"] >= 70
        ]
        single.sort(key=_score, reverse=True)
        for r in single:
            if len(picked) >= k:
                break
            if str(r.get("symbol")) in seen:
                continue
            picked.append(r)
            seen.add(str(r.get("symbol")))

    focus: list[dict[str, Any]] = []
    for r in picked:
        focus.append({
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "name_cn": r.get("name_cn"),
            "sector": r.get("sector"),
            "price": r.get("price"),
            "change_pct": r.get("change_pct"),
            "score": r.get("score"),
            "signal_count": r.get("signal_count"),
            "signals": r.get("signals"),
        })
    return focus


def signal_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    """统计当前筛选结果里各信号触发的数量（前端展示「这一批里有什么」）。"""
    out: dict[str, int] = {}
    for r in rows:
        for s in r.get("signals") or []:
            out[s["key"]] = out.get(s["key"], 0) + 1
    return out
