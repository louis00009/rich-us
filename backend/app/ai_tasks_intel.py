"""AI 任务 · 情报类
==================
本模块只登记一个任务：`intel_digest`（每日必读解读）。

为什么单独开一个模块：`ai_tasks_ops.py` 已 528 行、`ai_tasks_analysis.py` 499 行，
都逼近 600 行软上限 —— 按项目约定「再加任务要新开模块」。

任务定位
--------
把 `intel_digest.build_digest()` 产出的**确定性必读清单**（重要度、入选理由、
买入时机区间）交给大模型，让它回答三个问题：
  1. 今天真正重要的是哪几条，为什么（不能复述标题，要说因果）；
  2. 哪些标的值得放进观察序列，按什么顺序；
  3. 时机上要注意什么（区分「已反映在价格里」与「尚未反映」）。

数据来源铁律：清单里的每条事件都带真实来源，重要度与价位区间由规则算出。
模型只做归纳与排序解释，**不得新增清单之外的事实**；提示词里也明确禁止
输出买卖指令（平台交易动作必须走 ai_proposals + 人工批准）。
"""
from __future__ import annotations

from typing import Any

from .ai_tasks import _GUARD, _j, _register


def _b_intel_digest(p: dict) -> tuple[str, dict]:
    digest = p.get("digest") or {}
    if not isinstance(digest, dict) or not digest:
        raise ValueError("缺少必读清单数据")
    top = digest.get("top") or []
    if not top:
        raise ValueError("必读清单为空，无需解读")
    totals = digest.get("totals") or {}
    facts = {
        "日期": digest.get("date"),
        "回看窗口天数": digest.get("days"),
        "总量统计": totals,
        "必读条目": [
            {
                "重要度": t.get("importance"),
                "分档": t.get("tier"),
                "标的": t.get("symbol"),
                "日期": t.get("occurred_on"),
                "类别": t.get("category"),
                "方向": t.get("sentiment"),
                "影响度": t.get("impact"),
                "管道阶段": t.get("stage") or "普通",
                "标题": t.get("title"),
                "摘要": (t.get("summary") or "")[:240],
                "规则入选理由": t.get("reasons"),
                "来源": t.get("source_name"),
            }
            for t in top[:14]
        ],
        "标的汇总": [
            {
                "标的": s.get("symbol"), "主题": s.get("theme"),
                "事件数": s.get("count"), "高影响事件数": s.get("high_impact"),
                "利好": s.get("positive"), "利空": s.get("negative"),
                "最高重要度": s.get("max_importance"), "AI判定": s.get("recommendation"),
                "置信度": s.get("confidence"),
            }
            for s in (digest.get("by_symbol") or [])[:10]
        ],
        "时机候选": [
            {
                "标的": w.get("symbol"), "入选理由": w.get("reason"),
                "关注区间": [w.get("zone_low"), w.get("zone_high")],
                "触发条件": w.get("trigger"), "失效参考": w.get("invalidation"),
                "RSI14": w.get("rsi14"), "现价": w.get("price"), "ATR14": w.get("atr14"),
            }
            for w in (digest.get("watch") or [])[:6]
        ],
    }
    prompt = (
        "以下是平台今日从多源新闻里提取、并按确定性重要度排序后的「必读清单」"
        "（重要度 = 影响度×新鲜度×类别×阶段×来源，由规则算出，非模型判断）：\n"
        f"{_j(facts)}\n\n"
        "请严格按下列结构输出，用简体中文，**不要复述标题**，要讲清因果：\n"
        "## 今日必看（按重要性排序）\n"
        "逐条写：`标的 · 一句话结论` → 为什么重要（对盈利预期/竞争格局/估值的作用路径）"
        " → 市场是否可能已经反映（结合现价与关注区间判断）。最多 6 条。\n"
        "## 该盯哪几家\n"
        "按「值得投入研究时间」排序给出 3–5 家，每家一句理由。区分："
        "「信息改变基本面」与「信息只是情绪扰动」。\n"
        "## 时机与风险\n"
        "对「时机候选」里的标的，逐条说明关注区间是否合理、什么信号出现才算成立、"
        "什么情况直接放弃。若某标的的量化价位缺失，明确写「价位数据未覆盖」，不要编造数字。\n"
        "## 容易被忽略的利空\n"
        "从清单里的负面/中性条目中挑出 1–3 条被低估的风险。\n"
        "## 今日结论\n"
        "三句话以内收束：最值得跟踪的标的、最需要警惕的方向、以及本清单的局限。" + _GUARD
    )
    return prompt, facts


def _l_intel_digest(f: dict, _p: dict) -> str:
    """规则化兜底：清单本身已经是确定性结论，这里只做可读化重排。"""
    top = f.get("必读条目") or []
    totals = f.get("总量统计") or {}
    lines = [f"【每日必读 · 规则化摘要 · {f.get('日期') or '—'}】", ""]
    lines.append(
        f"窗口 {f.get('回看窗口天数')} 天：事件 {totals.get('events', 0)} 条，"
        f"其中重大 {totals.get('critical', 0)} 条、重要 {totals.get('high', 0)} 条；"
        f"利好 {totals.get('positive', 0)} / 利空 {totals.get('negative', 0)}；"
        f"涉及 {totals.get('symbols', 0)} 只标的。"
    )
    lines.append("")
    if not top:
        lines.append("没有达到必读阈值的条目。")
    else:
        lines.append(f"必读 {len(top)} 条（按重要度排序）：")
        for t in top[:10]:
            lines.append(
                f"· {t.get('标的')}｜重要度 {t.get('重要度')}（{t.get('分档')}）"
                f"｜{str(t.get('日期') or '')[:10]}｜{t.get('类别')}｜{t.get('方向')}"
                f"｜影响 {t.get('影响度')}★"
            )
            lines.append(f"  {t.get('标题')}")
            rs = t.get("规则入选理由") or []
            if rs:
                lines.append(f"  为什么重要：{'；'.join(rs)}")
    watch = f.get("时机候选") or []
    if watch:
        lines.append("")
        lines.append("时机候选（价位来自平台量化支撑/阻力，非估算）：")
        for w in watch:
            zone = f"{w.get('关注区间')[0]}~{w.get('关注区间')[1]}" if w.get("关注区间") and w["关注区间"][0] else "数据未覆盖"
            lines.append(f"· {w.get('标的')}｜{w.get('入选理由')}｜关注区间 {zone}｜现价 {w.get('现价')}")
            if w.get("触发条件"):
                lines.append(f"  触发：{w.get('触发条件')}")
            if w.get("失效参考"):
                lines.append(f"  失效：{w.get('失效参考')}")
    lines.append("")
    lines.append("以上为规则化排序结果，不构成投资建议；交易动作仍需走 AI 提案 + 人工批准。")
    return "\n".join(lines)


_register(
    "intel_digest",
    "每日必读解读",
    "对当日确定性排序后的情报必读清单做深度解读：谁最重要、为什么、时机与风险。",
    _b_intel_digest,
    _l_intel_digest,
    max_tokens=1800,
    temperature=0.25,
)
