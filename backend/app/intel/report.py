"""intel 批次报告落盘（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..database import session_scope
from .common import EVENT_CATEGORIES, REC_CN, REPORT_DIR, IntelAnalysis, IntelCompany, IntelEvent, IntelRun


def write_report(run_id: int) -> str:
    """把一次批次的全部节点 + 建议写成 Markdown 存档。返回文件路径。"""
    with session_scope() as db:
        run = db.get(IntelRun, run_id)
        if run is None:
            return ""
        events = (
            db.query(IntelEvent).filter(IntelEvent.run_id == run_id)
            .order_by(IntelEvent.created_at.desc()).all()
        )
        analyses = (
            db.query(IntelAnalysis).filter(IntelAnalysis.run_id == run_id)
            .order_by(IntelAnalysis.created_at.desc()).all()
        )
        companies = {c.symbol: c for c in db.query(IntelCompany).all()}
        path = _render_report(run, events, analyses, companies)
        run.report_path = path
    return path


def _render_report(run: IntelRun, events: list[IntelEvent], analyses: list[IntelAnalysis],
                   companies: dict[str, IntelCompany]) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = run.ended_at.strftime("%Y%m%d-%H%M%S") if run.ended_at else dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"run-{run.id}-{stamp}.md"
    lines: list[str] = []
    lines.append(f"# AI 情报批次报告 · Run #{run.id}")
    lines.append("")
    lines.append(f"- 运行窗口：{run.started_at:%Y-%m-%d %H:%M} UTC → {run.ended_at:%Y-%m-%d %H:%M} UTC" if run.ended_at
                 else f"- 开始：{run.started_at:%Y-%m-%d %H:%M} UTC（未截止）")
    lines.append(f"- 抓取周期：{run.interval_minutes} 分钟｜LLM 自动分析：{'开' if run.auto_analyze else '关'}")
    lines.append(f"- 事件节点：{len(events)} 条｜AI 建议：{len(analyses)} 条｜参与 Agent：{run.agents_seen}")
    lines.append("")
    by_symbol: dict[str, list[IntelEvent]] = {}
    for e in events:
        by_symbol.setdefault(e.symbol, []).append(e)
    lines.append("## 一、公司关键节点（事件时间线）")
    lines.append("")
    if not by_symbol:
        lines.append("（本批次未提交事件节点）")
    for sym in sorted(by_symbol, key=lambda s: -len(by_symbol[s])):
        c = companies.get(sym)
        lines.append(f"### {sym}（{c.name if c else ''}｜{c.theme if c else ''}）")
        lines.append("")
        for e in sorted(by_symbol[sym], key=lambda x: (x.occurred_on or "9999"), reverse=True):
            star = "★" * e.impact
            sent = {"positive": "🟢 利好", "negative": "🔴 利空", "neutral": "⚪ 中性"}.get(e.sentiment, e.sentiment)
            lines.append(
                f"- **{e.occurred_on or '日期未知'}｜{EVENT_CATEGORIES.get(e.category, e.category)}｜{sent}｜影响 {star}** — "
                f"{e.title}（来源：{e.source_name or '未知'}，提交：{e.agent}）"
            )
            if e.summary:
                lines.append(f"  - {e.summary}")
            if e.source_url:
                lines.append(f"  - 链接：{e.source_url}")
        lines.append("")
    lines.append("## 二、AI 买入建议")
    lines.append("")
    if not analyses:
        lines.append("（本批次未产出建议）")
    for a in analyses:
        c = companies.get(a.symbol)
        lines.append(f"### {a.symbol}（{c.name if c else ''}）— {REC_CN.get(a.recommendation, a.recommendation)}")
        lines.append("")
        lines.append(f"- 生成时间：{a.created_at:%Y-%m-%d %H:%M} UTC｜引擎：{a.engine}｜Agent：{a.agent}｜置信度：{a.confidence:.0f}%")
        if a.price_at_analysis:
            lines.append(f"- 分析时价格：{a.price_at_analysis}｜建议仓位：{a.position_pct}%｜周期：{a.horizon}")
        if a.thesis:
            lines.append(f"- 论点：{a.thesis}")
        if a.catalysts:
            lines.append(f"- 催化剂：{a.catalysts}")
        if a.risks:
            lines.append(f"- 风险：{a.risks}")
        if a.invalidation:
            lines.append(f"- 失效条件：{a.invalidation}")
        lines.append("")
    lines.append("## 三、免责说明")
    lines.append("")
    lines.append("本报告由本地流水线归档：事件与建议来自 AI Agent 抓取/分析，仅供研究参考，不构成投资建议。")
    lines.append("数据可溯源性：每条事件带来源名称/链接，每条建议带引擎与 Agent 标注。")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)

