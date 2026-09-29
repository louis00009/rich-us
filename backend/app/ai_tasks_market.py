"""AI 任务 · 行情类（个股快评 / 新闻要点 / 盘面简报 / 候选池点评）。"""
from __future__ import annotations

from typing import Any

from .ai_tasks import (
    _GUARD,
    _MARKET_SYSTEM,
    _j,
    _num,
    _register,
    _snap_facts,
)

# ==================================================================
# 1. 个股快评（行情分析页）
# ==================================================================
def _b_symbol_brief(p: dict) -> tuple[str, dict]:
    sym = str(p.get("symbol", "")).strip().upper()
    if not sym:
        raise ValueError("缺少 symbol")
    horizon = p.get("horizon") or "swing"
    facts = _snap_facts(sym, horizon)
    prompt = (
        f"标的 {sym} 的量化快照（含本地引擎结论）：\n{_j(facts)}\n\n"
        f"投资周期：{horizon}。\n"
        "请用不超过 6 句话给出：\n"
        "① 当前处于什么状态（趋势市/震荡市/高波动/过渡市）以及判断依据；\n"
        "② 多空倾向与最关键的 1–2 条证据；\n"
        "③ 关键价位（支撑/阻力/止损参考）；\n"
        "④ 在这个位置最该警惕的一件事。" + _GUARD
    )
    return prompt, facts


def _l_symbol_brief(f: dict, _p: dict) -> str:
    le = f.get("local_engine") or {}
    i = f.get("indicators") or {}
    d = f.get("dist_pct") or {}
    lv = le.get("levels") or {}
    lines = [
        f"【本地量化引擎 · {f.get('symbol')} 快评】",
        f"状态：{le.get('regime')}（{le.get('regime_desc')}）",
        f"倾向：{le.get('bias')}｜综合评分 {le.get('score')}｜置信度 {le.get('confidence')}%",
        f"现价 {_num(f.get('price'))}｜RSI {_num(i.get('rsi14'), 1)}｜ADX {_num(i.get('adx14'), 1)}"
        f"｜ATR 占比 {_num(i.get('atr_pct'), 2)}%",
        f"距 SMA50 {_num(d.get('to_sma50'))}%｜距 52 周高 {_num(d.get('to_52w_high'))}%",
    ]
    sup = lv.get("支撑") or []
    res = lv.get("阻力") or []
    if sup or res:
        lines.append(
            "支撑 " + ("/".join(_num(x) for x in sup) or "—")
            + "｜阻力 " + ("/".join(_num(x) for x in res) or "—")
        )
    lines.append(f"建议仓位参考 {le.get('suggested_position_pct')}%")
    for w in (le.get("warnings") or [])[:2]:
        lines.append(f"⚠ {w}")
    lines.append("以上为规则化计算结论；配置 LLM 后可获得自然语言深度解读。")
    return "\n".join(lines)


_register(
    "symbol_brief",
    "个股快评",
    "把单只标的的行情、指标、本地引擎结论压缩成一段可执行快评。",
    _b_symbol_brief,
    _l_symbol_brief,
    system=_MARKET_SYSTEM,
    max_tokens=800,
)


# ==================================================================
# 2. 新闻要点提炼（新闻面板 / 行情页）
# ==================================================================
def _b_news_digest(p: dict) -> tuple[str, dict]:
    sym = str(p.get("symbol", "")).strip().upper()
    items = p.get("items") or []
    if not items and sym:
        try:
            from .news import fetch_news

            items = fetch_news(sym, limit=12).get("items", [])
        except Exception:  # noqa: BLE001 —— 新闻抓取失败不应阻塞 AI 任务
            items = []
    rows = [
        {
            "标题": str(it.get("headline", ""))[:200],
            "来源": it.get("source", ""),
            "时间": str(it.get("published_at") or "")[:16],
            "类型": it.get("category", ""),
            "摘要": str(it.get("summary") or "")[:300],
        }
        for it in items[:15]
        if it.get("headline")
    ]
    if not rows:
        raise ValueError("没有可用的新闻条目")
    facts = {"symbol": sym or "（未指定）", "count": len(rows), "items": rows}
    prompt = (
        f"以下是 {facts['symbol']} 最近的新闻/公告标题与摘要：\n{_j(facts)}\n\n"
        "请输出：\n## 核心要点（3–5 条，每条一句话）\n"
        "## 事件面倾向（偏多 / 偏空 / 中性，说明理由）\n"
        "## 需要留意但尚不确定的事\n"
        "## 对持仓/观察的提示\n"
        "注意：只依据给定标题与摘要，不得补充你记忆中的任何新闻。" + _GUARD
    )
    return prompt, facts


_POS_WORDS = ("beat", "record", "surge", "rally", "upgrade", "buyback", "dividend", "growth",
              "approval", "wins", "contract", "expands", "raise", "profit", "超预期", "增长",
              "中标", "签约", "回购", "分红", "上调", "突破", "利好")
_NEG_WORDS = ("miss", "cut", "downgrade", "lawsuit", "probe", "recall", "layoff", "warn",
              "decline", "drop", "loss", "delay", "halt", "fraud", "低于预期", "下滑",
              "裁员", "诉讼", "调查", "召回", "下调", "亏损", "延期", "利空")


def _l_news_digest(f: dict, _p: dict) -> str:
    rows = f.get("items") or []
    pos, neg = [], []
    for it in rows:
        text = f"{it.get('标题', '')} {it.get('摘要', '')}".lower()
        if any(w in text for w in _POS_WORDS):
            pos.append(it.get("标题", ""))
        if any(w in text for w in _NEG_WORDS):
            neg.append(it.get("标题", ""))
    lines = [f"【新闻要点（规则化提取）· {f.get('symbol')}｜共 {len(rows)} 条】", ""]
    for it in rows[:6]:
        lines.append(f"· [{it.get('时间') or '—'}] {it.get('标题')}")
    lines.append("")
    lines.append(f"倾向统计：偏多关键词命中 {len(pos)} 条，偏空关键词命中 {len(neg)} 条"
                 "（关键词匹配较粗糙，仅供参考）")
    if pos:
        lines.append("偏多线索：" + "；".join(pos[:3]))
    if neg:
        lines.append("偏空线索：" + "；".join(neg[:3]))
    lines.append("配置 LLM 后可获得带事件面推理的深度摘要。")
    return "\n".join(lines)


_register(
    "news_digest",
    "新闻要点提炼",
    "把多源新闻标题提炼成要点、事件面倾向与不确定性提示。",
    _b_news_digest,
    _l_news_digest,
    max_tokens=1100,
)


# ==================================================================
# 3. 候选池点评（榜单页）
# ==================================================================
def _b_ranking_review(p: dict) -> tuple[str, dict]:
    rows = p.get("rows") or []
    if not rows:
        raise ValueError("候选池为空")
    slim: list[dict[str, Any]] = []
    for r in rows[:40]:
        slim.append({
            "symbol": r.get("symbol"),
            "name": r.get("name_cn") or r.get("name"),
            "price": r.get("price"),
            "change_pct": r.get("change_pct"),
            "pe": r.get("pe"),
            "pb": r.get("pb"),
            "roe_pct": r.get("roe_pct"),
            "score": r.get("score"),
            "dimensions": r.get("dimensions"),
            "rsi14": r.get("rsi14"),
            "ret_1y_pct": r.get("ret_1y_pct"),
            "sector": r.get("sector"),
        })
    facts = {
        "universe_total": p.get("universe_total"),
        "matched": p.get("matched") or len(rows),
        "score_min": p.get("score_min"),
        "sort": p.get("sort"),
        "rows": slim,
    }
    prompt = (
        "以下是按用户当前筛选条件（评分阈值/排序字段）从美股全市场中挑出的候选池：\n"
        f"{_j(facts)}\n\n"
        "请输出：\n## 候选池画像（这批标的共同的特征是什么）\n"
        "## 值得优先深挖的 3 个（各自给一句理由）\n"
        "## 需要警惕的 2 类陷阱（例如估值分位高、ROE 由回购推高、动量已透支）\n"
        "## 下一步建议（该补看什么数据、该做什么验证）\n"
        "再次强调：这是筛选结果的解读，不是买入建议。" + _GUARD
    )
    return prompt, facts


def _l_ranking_review(f: dict, _p: dict) -> str:
    rows = f.get("rows") or []
    if not rows:
        return "候选池为空。"
    scores = [r.get("score") for r in rows if isinstance(r.get("score"), (int, float))]
    pe = [r.get("pe") for r in rows if isinstance(r.get("pe"), (int, float))]
    lines = [
        f"【候选池规则化点评】共 {f.get('matched')} 只"
        f"（评分阈值 {f.get('score_min')}，排序 {f.get('sort')}）",
    ]
    if scores:
        lines.append(f"评分：最高 {max(scores):.1f}｜最低 {min(scores):.1f}"
                     f"｜均值 {sum(scores) / len(scores):.1f}")
    if pe:
        lines.append(f"市盈率：最低 {min(pe):.1f}｜中位 {sorted(pe)[len(pe) // 2]:.1f}｜最高 {max(pe):.1f}")
    top = sorted(rows, key=lambda r: -(r.get("score") or 0))[:5]
    lines.append("")
    lines.append("评分前列：")
    for r in top:
        lines.append(
            f"· {r.get('symbol')} {r.get('name') or ''}｜评分 {_num(r.get('score'), 1)}"
            f"｜PE {_num(r.get('pe'), 1)}｜PB {_num(r.get('pb'), 2)}｜ROE {_num(r.get('roe_pct'), 1)}%"
        )
    if pe:
        expensive = [r for r in rows if isinstance(r.get("pe"), (int, float)) and r["pe"] > 60]
        if expensive:
            lines.append(f"提示：{len(expensive)} 只 PE > 60，估值分位偏高，需确认成长性是否支撑。")
    lines.append("配置 LLM 后可获得候选池画像与陷阱提示。")
    return "\n".join(lines)


_register(
    "ranking_review",
    "候选池点评",
    "解读当前筛选出的候选池结构，指出值得深挖的标的与潜在陷阱。",
    _b_ranking_review,
    _l_ranking_review,
    max_tokens=1300,
)


# ==================================================================
# 4. 盘面简报（首页）
# ==================================================================
def _b_market_briefing(p: dict) -> tuple[str, dict]:
    quotes = p.get("quotes") or []
    if not quotes:
        raise ValueError("没有可用的行情数据")
    facts = {
        "as_of": p.get("as_of"),
        "quotes": [
            {"symbol": q.get("symbol"), "price": q.get("price"),
             "change_pct": q.get("change_pct"), "volume": q.get("volume")}
            for q in quotes[:20]
        ],
        "account": p.get("account"),
        "positions": (p.get("positions") or [])[:10],
        "system": p.get("system"),
    }
    prompt = (
        "以下是主要指数/资产类别的实时快照与账户概况：\n"
        f"{_j(facts)}\n\n"
        "请用一段简洁的「盘面简报」输出（不超过 8 句话）：\n"
        "① 风险偏好处于什么状态（进攻/防御/轮动），依据是哪些标的的背离；\n"
        "② 最值得注意的 2 个异动；\n"
        "③ 对当前持仓的含义（只讲方向性影响）；\n"
        "④ 今天需要盯的一件事。" + _GUARD
    )
    return prompt, facts


def _l_market_briefing(f: dict, _p: dict) -> str:
    qs = f.get("quotes") or []
    lines = ["【盘面规则化简报】", ""]
    up = [q for q in qs if (q.get("change_pct") or 0) > 0]
    lines.append(f"上涨 {len(up)} / 下跌 {len(qs) - len(up)}（共 {len(qs)} 个标的）")
    movers = sorted(qs, key=lambda q: -abs(q.get("change_pct") or 0))[:5]
    if movers:
        lines.append("异动前列：")
        for q in movers:
            lines.append(f"· {q.get('symbol')} {_num(q.get('change_pct'), 2)}%｜{_num(q.get('price'))}")
    vix = next((q for q in qs if str(q.get("symbol", "")).upper() in ("^VIX", "VIX")), None)
    if vix and isinstance(vix.get("change_pct"), (int, float)):
        if vix["change_pct"] > 3:
            lines.append("波动率指数上行，风险偏好转弱，注意降仓。")
        elif vix["change_pct"] < -3:
            lines.append("波动率指数回落，风险偏好改善。")
    lines.append("")
    lines.append("配置 LLM 后可获得带推理的盘面简报。")
    return "\n".join(lines)


_register(
    "market_briefing",
    "盘面简报",
    "把主要指数与账户概况压缩成一段可读的盘面简报。",
    _b_market_briefing,
    _l_market_briefing,
    max_tokens=900,
)
