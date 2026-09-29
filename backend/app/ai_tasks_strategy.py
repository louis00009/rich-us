"""AI 任务 · 策略类（自定义策略代码审查）。

单独成模块的原因：`ai_tasks_ops.py`（策略草稿/订单诊断/情报解读/提案复核）与
`ai_tasks_analysis.py`（回测诊断/寻优/风控/组合/复盘）都已接近铁律 9 的
600 行软上限，而「代码审查」自带一套确定性的未来函数检测规则，体量不小，
因此按领域再拆一层。
"""
from __future__ import annotations

import re

from .ai_tasks import _GUARD, _j, _register

# ==================================================================
# 确定性未来函数检测
# ==================================================================
# 「无未来函数」是平台的铁律 2：第 t 根收盘产生的信号只能在 t+1 根开盘成交。
# 但用户提交的 Python 代码策略（CodeStrategy）只经过 AST **安全**白名单校验
# （禁止 os/eval/open 等），**不检查时间语义** —— 也就是说
# `ctx.closes.shift(-1)` 这种读取未来价格的写法能顺利通过校验并跑出一条
# 漂亮但完全虚假的回测曲线。
#
# 这里用高置信度的模式匹配把最典型的几种未来函数找出来。之所以用正则而不是
# AST：这些模式本质是「对 pandas 时间序列的调用」，正则足以覆盖，
# 而 AST 反而更难表达 `shift(-1)` 这类带负常量的调用。
_FUTURE_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (re.compile(r"\.shift\s*\(\s*-"), "high", "FUTURE_SHIFT",
     "使用了负位移 shift(-N)：会取到未来 bar 的值，构成未来函数。"),
    (re.compile(r"\.pct_change\s*\(\s*-"), "high", "FUTURE_PCT_CHANGE",
     "pct_change(-N) 会用到未来价格，构成未来函数。"),
    (re.compile(r"\bbfill\b|\bbackfill\b|method\s*=\s*['\"]bfill['\"]|method\s*=\s*['\"]backfill['\"]"),
     "high", "BACKFILL",
     "bfill / backfill 会把未来值回填到过去，是最隐蔽的未来函数之一。"),
    (re.compile(r"rolling\s*\([^)]*center\s*=\s*True"), "mid", "CENTER_WINDOW",
     "rolling(center=True) 的窗口跨越当前 bar，包含未来数据。"),
    (re.compile(r"\.interpolate\s*\("), "mid", "INTERPOLATE",
     "interpolate() 默认同时参考前后值（含未来）；如需使用请显式限制 limit_direction='forward'。"),
    (re.compile(r"\.iloc\s*\[\s*[^\]]*\+\s*1\s*\]|\[\s*[ij]\s*\+\s*1\s*\]"), "mid", "FUTURE_INDEX",
     "用 i+1 / j+1 访问了下一根 bar。"),
    (re.compile(r"\[\s*::\s*-1\s*\]"), "mid", "REVERSED",
     "对时间序列做了 [::-1] 反转，容易造成时间倒流。"),
    (re.compile(r"\bfillna\s*\([^)]*method\s*=\s*['\"]bfill['\"]"), "high", "FILLNA_BFILL",
     "fillna(method='bfill') 会用未来值填充过去。"),
]


def _code_checks(code: str) -> list[dict]:
    """返回 [{level, code, message}] —— 确定性检测结果。"""
    out: list[dict] = []
    for rx, level, name, msg in _FUTURE_PATTERNS:
        m = rx.search(code)
        if m:
            out.append({"level": level, "code": name, "message": msg, "match": m.group(0)[:60]})

    # 结构性问题
    if "generate" not in code:
        out.append({"level": "high", "code": "NO_GENERATE",
                    "message": "代码里没有 generate 函数（沙箱校验也会拦下）。", "match": ""})
    if "ctx.closes" not in code and "ctx.data" not in code:
        out.append({"level": "high", "code": "NO_DATA_ACCESS",
                    "message": "代码没有访问 ctx.closes / ctx.data，无法产生任何信号。", "match": ""})
    # 有信号但完全没有仓位归零/归一处理，容易一路满仓
    if "generate" in code and not re.search(r"0\.0|zeros|fillna|clip|norm", code):
        out.append({"level": "mid", "code": "NO_ZERO_BASE",
                    "message": "没有看到「默认 0 仓位 / 归一化 / clip」的痕迹，"
                               "返回值可能被当成恒满仓，请确认权重矩阵的初始化方式。", "match": ""})
    return out


def _b_strategy_code_review(p: dict) -> tuple[str, dict]:
    code = str(p.get("code") or "")
    if not code.strip():
        raise ValueError("请先填写策略代码")
    checks = _code_checks(code)
    facts = {
        "symbols": p.get("symbols"),
        "code": code[:6000],
        "rule_checks": checks,
        "platform_notes": {
            "sandbox": "AST 白名单：仅允许 pandas/numpy/math/datetime/statistics，"
                       "禁止 os/sys/eval/exec/open/getattr/双下划线属性/while True。",
            "timing": "平台铁律：第 t 根收盘产生的信号在 t+1 根开盘成交（无未来函数）。"
                      "沙箱只查安全性，不查时间语义，未来函数需靠本次审查发现。",
        },
    }
    high = [c for c in checks if c["level"] == "high"]
    prompt = (
        "以下是用户为量化平台编写的一个自定义策略 Python 代码，以及平台已经"
        "用确定性规则检测出的问题 `rule_checks`：\n"
        f"{_j(facts)}\n\n"
        "请做一次**策略代码审查**，重点在时间语义与工程健壮性。"
        "严格按以下结构输出（总篇幅 700 字以内）：\n"
        "## 结论（这段代码能不能安全地用于回测？一句话，并说明最主要的理由）\n"
        "## 未来函数风险（逐条列出 rule_checks 里的 high 项并解释后果；"
        "如果你还发现了 rule_checks 没覆盖的未来函数写法，务必补充）\n"
        "## 逻辑与工程问题（数据对齐、标的数量变化时的列错位、除零、NaN 处理、权重是否越界）\n"
        "## 这份代码最可能在什么行情下失效\n"
        "## 上线前建议补做的验证（具体到「改哪一行、看什么指标」）\n"
        "注意：不要重写整段代码，只指出问题与修改方向；"
        "如果 rule_checks 为空，也要明确说明「确定性检查未发现未来函数，"
        "但这不等于没有」，不要给出虚假的安心感。" + _GUARD
    )
    return prompt, facts


def _l_strategy_code_review(f: dict, _p: dict) -> str:
    checks = f.get("rule_checks") or []
    high = [c for c in checks if c["level"] == "high"]
    mid = [c for c in checks if c["level"] == "mid"]
    lines = ["【策略代码规则化审查（未使用 LLM）】", ""]
    if high:
        lines.append("结论：检测到高置信度的未来函数或结构性问题，回测结果不可信，请先修复。")
    elif mid:
        lines.append("结论：未发现高置信度未来函数，但有可疑写法需要人工确认。")
    else:
        lines.append("结论：确定性检查未发现未来函数 —— 但这不等于没有问题，仍需人工复核逻辑。")
    lines.append("")
    if high:
        lines.append("【必须修复（high）】")
        for c in high:
            lines.append(f"· {c['message']}" + (f"（命中：{c['match']}）" if c.get("match") else ""))
        lines.append("")
    if mid:
        lines.append("【需人工确认（mid）】")
        for c in mid:
            lines.append(f"· {c['message']}" + (f"（命中：{c['match']}）" if c.get("match") else ""))
        lines.append("")
    lines.append("通用检查清单：")
    lines.append("· 信号是否只用了当前及历史 bar（平台在 t+1 开盘成交）")
    lines.append("· 标的数量变化时，权重矩阵是否按 ctx.closes.columns 对齐")
    lines.append("· 权重是否可能超过 1（超杠杆）或出现 NaN")
    lines.append("· 是否处理了停牌/缺失数据")
    lines.append("")
    lines.append("配置 LLM 后可获得逐条解释与修改方向。")
    return "\n".join(lines)


_register(
    "strategy_code_review",
    "策略代码审查",
    "审查自定义策略代码的未来函数风险与工程健壮性（沙箱只查安全，不查时间语义）。",
    _b_strategy_code_review,
    _l_strategy_code_review,
    max_tokens=1600,
    temperature=0.2,
)
