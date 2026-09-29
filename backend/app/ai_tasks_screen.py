"""AI 任务 · 选股类（个股批量分析 / 智能选股）。

为什么单独一个模块：这两个任务的服务对象是**榜单页的筛选动作** ——
一个把「选中的标的」变成对比分析，一个把「自然语言需求」变成筛选条件。
它们与行情类（快评/简报）、分析类（回测/风控）的输入形态不同，单独放更清晰。

单位约定：本模块所有传给模型的字段**把单位写进 key 名**（`r1y_pct` / `roe_pct`），
因为 `r1y`、`vol_ann`、`excess_1y`、`roe`、`div_yield` 在平台里全部是**百分数**，
只写 `r1y` 会让模型按小数解读（把 24.5 当成 2450%）。
"""
from __future__ import annotations

import json
from typing import Any

from .ai_tasks import _GUARD, _j, _num, _register, _extract_json

# ==================================================================
# 1. 个股批量分析（选中 1 只 = 深度分析；选中多只 = 横向对比）
# ==================================================================
_MAX_SYMBOLS = 12


def _slim_row(r: dict) -> dict:
    """把榜单行压成分析用的事实字典（单位进 key 名）。"""
    return {
        "symbol": r.get("symbol"),
        "name": r.get("name_cn") or r.get("name"),
        "sector": r.get("sector"),
        "price": r.get("price"),
        "change_pct": r.get("change_pct"),
        "pe_ttm": r.get("pe"),
        "pb": r.get("pb"),
        "roe_pct": r.get("roe_pct"),
        "div_yield_pct": r.get("div_yield"),
        "market_cap_usd_bn": round(r["market_cap"] / 1e9, 1) if isinstance(r.get("market_cap"), (int, float)) else None,
        "score_0_100": r.get("score"),
        "score_dims": r.get("dimensions"),
        "rsi14": r.get("rsi14"),
        "dist_ma200_pct": r.get("ma200_rel"),
        "r1y_pct": r.get("r1y_pct"),
        "vol_ann_pct": r.get("vol_ann"),
        "beta": r.get("beta"),
    }


def _b_stock_batch_review(p: dict) -> tuple[str, dict]:
    rows = [_slim_row(r) for r in (p.get("rows") or []) if r.get("symbol")][:_MAX_SYMBOLS]
    if not rows:
        raise ValueError("没有选中的标的")
    facts = {"count": len(rows), "source": p.get("context") or "榜单筛选结果", "rows": rows}
    head = (
        f"以下是我从「{facts['source']}」里选中的 {len(rows)} 只标的"
        "（数据来自平台实时行情 + 第三方估值 + 本地计算的技术指标）：\n"
        f"{_j(facts)}\n\n"
    )
    if len(rows) == 1:
        body = (
            "请对这只标的做一次深度分析，按下面的结构输出（用列表，**不要用 Markdown 表格**）：\n"
            "## 一句话结论\n"
            "## 估值（PE / PB / 股息率处于什么水平，是否与它的质量匹配）\n"
            "## 质量（ROE 说明了什么；若 ROE 异常高，注意可能是回购让净资产趋近 0 而虚高）\n"
            "## 位置与趋势（距 MA200、RSI、近一年涨跌幅说明了什么）\n"
            "## 综合评分拆解（四个维度里哪一维拉高了分、哪一维拖低了分）\n"
            "## 需要补充验证的信息\n"
            "**篇幅要求：全文控制在 400 字以内，每节不超过 3 句，直接给结论、不要铺垫。**\n"
        )
    else:
        body = (
            "请做一次**横向对比分析**，按下面的结构输出（用列表，**不要用 Markdown 表格**）：\n"
            "## 一句话结论（这批标的整体是什么风格，谁最突出）\n"
            "## 共同特征（它们在估值 / 质量 / 位置 / 趋势上有什么共性）\n"
            "## 关键差异（逐只一句话：它和其余几只比，强在哪、弱在哪）\n"
            "## 优先关注（挑 1–3 只说明理由；只给研究优先级，不是买入建议）\n"
            "## 主要风险（这批标的共同面临的风险，以及各自特有的风险）\n"
            "**篇幅要求：全文控制在 600 字以内，「关键差异」每只严格一句话，不要复述数据。**\n"
        )
    return head + body + _GUARD, facts


def _row_flags(r: dict) -> list[str]:
    """单只标的的规则化红旗（本地兜底与「先看谁」排序共用）。"""
    sym = r.get("symbol") or "?"
    out: list[str] = []
    pe = r.get("pe_ttm")
    if isinstance(pe, (int, float)):
        if pe <= 0:
            out.append(f"{sym} PE {_num(pe, 1)}（亏损或数据缺失），PE 不具参考意义")
        elif pe > 60:
            out.append(f"{sym} PE {_num(pe, 1)} 偏高，需确认成长性能否支撑这个估值")
    roe = r.get("roe_pct")
    if isinstance(roe, (int, float)) and roe > 60:
        out.append(f"{sym} ROE {_num(roe, 1)}% 异常高，可能由回购推高（净资产趋近 0），需看绝对利润")
    rsi = r.get("rsi14")
    if isinstance(rsi, (int, float)):
        if rsi >= 70:
            out.append(f"{sym} RSI {_num(rsi, 1)} 已进入超买区，短期回调风险上升")
        elif rsi <= 30:
            out.append(f"{sym} RSI {_num(rsi, 1)} 处于超卖区，注意是否基本面变坏")
    d = r.get("dist_ma200_pct")
    if isinstance(d, (int, float)) and d < -15:
        out.append(f"{sym} 低于 MA200 {_num(abs(d), 1)}%，处于中长期下行趋势")
    y = r.get("r1y_pct")
    if isinstance(y, (int, float)) and y < -30:
        out.append(f"{sym} 近一年 {_num(y, 1)}%，跌幅显著，先弄清是估值杀还是基本面恶化")
    dy = r.get("div_yield_pct")
    if isinstance(dy, (int, float)) and dy > 8:
        out.append(f"{sym} 股息率 {_num(dy, 1)}% 偏高，警惕「股息陷阱」（股价大跌或一次性特别分红）")
    return out


def _fmt_row(r: dict) -> str:
    parts = [f"· {r.get('symbol')} {r.get('name') or ''}".rstrip()]
    pairs = [
        ("评分", _num(r.get("score_0_100"), 1)),
        ("PE", _num(r.get("pe_ttm"), 1)),
        ("ROE", f"{_num(r.get('roe_pct'), 1)}%"),
        ("RSI", _num(r.get("rsi14"), 1)),
        ("近1年", f"{_num(r.get('r1y_pct'), 1)}%"),
    ]
    parts.append("｜".join(f"{k} {v}" for k, v in pairs))
    return " ".join(parts)


def _l_stock_batch_review(f: dict, _p: dict) -> str:
    rows = f.get("rows") or []
    if not rows:
        return "没有可分析的标的。"
    if len(rows) == 1:
        r = rows[0]
        lines = [f"【规则化分析 · {r.get('symbol')} {r.get('name') or ''}】", ""]
        lines.append(_fmt_row(r))
        lines.append("")
        dims = r.get("score_dims")
        if isinstance(dims, dict) and dims:
            lines.append("评分维度：" + "｜".join(f"{k} {_num(v, 1)}" for k, v in dims.items()))
            lines.append("")
        flags = _row_flags(r)
        lines.extend(f"· {x}" for x in flags) if flags else lines.append("· 未触发内置规则化红旗。")
        lines.append("")
        lines.append("配置 LLM 后可获得估值/质量/趋势的分项深度解读。")
        return "\n".join(lines)

    ordered = sorted(rows, key=lambda x: -(x.get("score_0_100") or 0))
    lines = [f"【规则化对比分析 · 共 {len(rows)} 只】", "", "按综合评分排序："]
    lines.extend(_fmt_row(r) for r in ordered)
    scores = [r["score_0_100"] for r in rows if isinstance(r.get("score_0_100"), (int, float))]
    pes = sorted(r["pe_ttm"] for r in rows if isinstance(r.get("pe_ttm"), (int, float)) and r["pe_ttm"] > 0)
    roes = sorted(r["roe_pct"] for r in rows if isinstance(r.get("roe_pct"), (int, float)))
    if scores:
        lines.append("")
        lines.append(f"评分：最高 {max(scores):.1f}｜最低 {min(scores):.1f}｜均值 {sum(scores) / len(scores):.1f}")
    if pes:
        lines.append(f"PE：最低 {pes[0]:.1f}｜中位 {pes[len(pes) // 2]:.1f}｜最高 {pes[-1]:.1f}")
    if roes:
        lines.append(f"ROE：最低 {roes[0]:.1f}%｜中位 {roes[len(roes) // 2]:.1f}%｜最高 {roes[-1]:.1f}%")
    flags: list[str] = []
    for r in ordered:
        flags.extend(_row_flags(r))
    if flags:
        lines.append("")
        lines.append("红旗：")
        lines.extend(f"· {x}" for x in flags[:10])
    lines.append("")
    lines.append("配置 LLM 后可获得共同特征、关键差异与优先关注方向。")
    return "\n".join(lines)


_register(
    "stock_batch_review",
    "个股对比分析",
    "对选中的 1 只或多只标的做深度分析 / 横向对比（含规则化红旗兜底）。",
    _b_stock_batch_review,
    _l_stock_batch_review,
    max_tokens=1600,
)


# ==================================================================
# 2. 智能选股（自然语言 → 结构化筛选条件）
# ==================================================================
# 可用的筛选字段：与前端 RankingFiltersValue 的 key **一一对应**，
# 前端拿到 data.filters 后可直接 merge 进筛选面板并生效。
# 新增筛选维度时，这里和 RankingFilters.tsx 必须同步改（否则 AI 生成的条件会被前端丢弃）。
_SCREEN_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("peMin", "number", "市盈率下限（TTM），可为负"),
    ("peMax", "number", "市盈率上限（TTM）"),
    ("pbMax", "number", "市净率上限"),
    ("capMin", "number", "总市值下限（亿美元）"),
    ("divMin", "number", "股息率下限（%）"),
    ("roeMin", "number", "ROE 下限（%）"),
    ("fromHighMax", "number", "距 52 周高的上限（%），负数。-30 表示「从高点回撤至少 30%」"),
    ("rsiMin", "number", "RSI(14) 下限（0~100）"),
    ("rsiMax", "number", "RSI(14) 上限（0~100）"),
    ("volMax", "number", "年化波动率上限（%）"),
    ("betaMax", "number", "Beta 上限（相对 SPY）"),
    ("req1yMin", "number", "近 1 年收益下限（%）"),
    ("excessMin", "number", "相对 SPY 超额收益下限（%）"),
    ("excludeLoss", "boolean", "排除亏损标的（EPS ≤ 0，PE 无意义）"),
    ("onlyBull", "boolean", "只看均线多头排列（价 > MA20 > MA60 > MA200）"),
    ("maPos", '"above" | "below"', "只看站上 / 跌破 200 日均线的标的"),
)

_SCREEN_KEYS = frozenset(k for k, _t, _d in _SCREEN_FIELDS)


def _b_smart_screen(p: dict) -> tuple[str, dict]:
    query = str(p.get("query", "")).strip()
    if not query:
        raise ValueError("请先描述你想找什么样的标的")
    sectors = [s for s in (p.get("sectors") or []) if s][:60]
    sorts = [s for s in (p.get("sorts") or []) if s][:60]
    facts = {
        "query": query,
        "available_fields": [{"key": k, "type": t, "desc": d} for k, t, d in _SCREEN_FIELDS],
        "available_sectors": sectors,
        "available_sorts": sorts,
    }
    prompt = (
        "用户想从美股全市场（S&P 500）里筛选标的，他的需求原话是：\n"
        f"「{query}」\n\n"
        "你可以使用的筛选字段（**只能**用这些 key，不要自创字段名）：\n"
        f"{_j([{'key': k, 'type': t, 'desc': d} for k, t, d in _SCREEN_FIELDS])}\n\n"
        f"可选行业（sector 只能取其中之一或留空）：{_j(sectors)}\n"
        f"可选排序字段（sort 只能取其中之一或留空）：{_j(sorts)}\n\n"
        "请把需求翻译成筛选条件，**只输出一个 JSON 对象**（不要解释文字、不要 Markdown 围栏）：\n"
        "{\n"
        '  "filters": {"字段名": 值},\n'
        '  "sector": "行业名或空串",\n'
        '  "sort": "排序字段或空串",\n'
        '  "direction": "asc 或 desc",\n'
        '  "view": "pool 或 all",\n'
        '  "explain": "一句话说明这些条件如何对应你的需求"\n'
        "}\n"
        "硬性要求：\n"
        "1. filters 里只填用户**确实提到**的条件，不要为了凑数加限制；宁可少填。\n"
        "2. 数值字段填数字（不要带单位、不要写成字符串）；布尔字段填 true / false。\n"
        "3. 用户说「不要超买」这类否定需求时，用 rsiMax（上限）表达，不要用 rsiMin。\n"
        "4. 用户强调「优质 / 评分高」时，view 填 \"pool\" 并 sort 填 \"score\"。\n"
        "5. 如果需求无法用上面的字段表达（例如营收增速、分析师评级、ESG），"
        "**不要编造字段**，在 explain 里明确写「该需求平台暂无对应字段」，并把能表达的部分填上。\n"
        "6. 不要给出「买入信号」这类绝对指令 —— 你只是在把需求翻译成筛选条件。"
    )
    return prompt, facts


# 关键词 → 筛选条件（本地兜底）。带否定前缀的词不触发（「不要超买」≠「超买」）。
_NEG = ("不", "别", "非", "避免", "不要", "无需", "没有", "排除", "不想")
_SCREEN_RULES: tuple[tuple[tuple[str, ...], dict], ...] = (
    (("低估值", "便宜", "低估", "价值股", "估值低"), {"peMax": 20, "excludeLoss": True}),
    (("高股息", "股息", "分红", "红利"), {"divMin": 3}),
    # ROE 的词序很随意（「高ROE」「ROE 高」「ROE高的」），所以把常见写法都列上
    (("高roe", "高 roe", "roe高", "roe 高", "roe高的", "优质", "赚钱", "盈利能力强"), {"roeMin": 20}),
    (("破净", "跌破净资产"), {"pbMax": 1}),
    (("超跌", "回撤大", "跌下来", "位置低", "跌得多"), {"fromHighMax": -30}),
    (("超卖",), {"rsiMax": 30}),
    (("大盘", "蓝筹", "龙头", "大市值", "大公司"), {"capMin": 2000}),
    (("趋势", "强势", "上升通道", "多头排列"), {"maPos": "above", "onlyBull": True}),
    (("低波动", "稳健", "防御", "波动小"), {"volMax": 25, "betaMax": 1.2}),
    # 只映射**价格动量**；「成长股」是基本面概念，见 _UNSUPPORTED —— 不能拿近 1 年涨跌幅顶替。
    (("动量", "涨得好", "涨幅大", "强势上涨"), {"req1yMin": 15}),
    (("跑赢", "超额", "强于大盘"), {"excessMin": 5}),
    (("超买", "涨太多", "涨过头"), {"rsiMin": 70}),
)

# 平台**没有**对应字段的需求。命中时不做任何映射，只在 explain 里如实说明 ——
# 静默拿一个含义不同的指标顶替（如用「近 1 年涨跌幅」冒充「营收增速」）会误导用户。
_UNSUPPORTED: tuple[tuple[tuple[str, ...], str], ...] = (
    (("营收", "收入", "净利", "利润", "毛利", "增速", "增长率", "成长", "业绩"), "基本面增速（营收 / 利润）"),
    (("分析师", "评级", "目标价", "卖方", "一致预期"), "分析师评级与目标价"),
    (("esg", "碳中和", "社会责任"), "ESG 评分"),
    (("研发", "专利"), "研发投入与专利"),
    (("股东", "内部人", "增持", "减持"), "股东与内部人行为"),
    (("市盈率相对盈利增长", "peg"), "PEG"),
)


def _has(low: str, kw: str) -> bool:
    """关键词是否**未被否定**地出现（「不要超买」里的「超买」不算命中）。"""
    i = low.find(kw)
    while i >= 0:
        if not any(n in low[max(0, i - 4):i] for n in _NEG):
            return True
        i = low.find(kw, i + 1)
    return False


def _l_smart_screen(f: dict, _p: dict) -> str:
    """规则化解析：关键词映射 + 行业匹配。输出与 LLM 相同的 JSON 结构。"""
    query = f.get("query", "")
    low = query.lower()
    filters: dict[str, Any] = {}
    hits: list[str] = []
    for words, patch in _SCREEN_RULES:
        if any(_has(low, w) for w in words):
            filters.update(patch)
            hits.append(words[0])
    # 否定式：说了「不要超买」但没命中任何规则 → 用上限（rsiMax）表达
    if "超买" in low and not _has(low, "超买") and "rsiMax" not in filters:
        filters["rsiMax"] = 70
        hits.append("不要超买")
    sector = ""
    for s in f.get("available_sectors") or []:
        if s and (s in query or s.lower() in low):
            sector = s
            break
    sort, view = "", "all"
    # 「优质」已在上面映射为 ROE 门槛，这里不再重复触发候选池视图，避免语义叠加
    if any(w in query for w in ("评分", "综合分", "最好", "最值得", "优选")):
        sort, view = "score", "pool"
    unsupported = [label for words, label in _UNSUPPORTED if any(w in low for w in words)]
    explain = (
        f"规则化匹配到：{'、'.join(hits)}" if hits else "未能从描述中识别出可用的筛选条件"
    )
    if sector:
        explain += f"；行业限定为「{sector}」"
    if unsupported:
        explain += f"。注意：{ '、'.join(unsupported) } 平台暂无对应字段，未纳入筛选"
    explain += "。以上为关键词规则匹配（未使用 LLM，较为粗糙），请确认后再应用。"
    return json.dumps(
        {"filters": filters, "sector": sector, "sort": sort, "direction": "desc",
         "view": view, "explain": explain},
        ensure_ascii=False,
    )


_register(
    "smart_screen",
    "智能选股",
    "把自然语言选股需求翻译成榜单页的筛选条件（结构化，可一键应用）。",
    _b_smart_screen,
    _l_smart_screen,
    max_tokens=900,
    temperature=0.1,
    parse=_extract_json,
)
