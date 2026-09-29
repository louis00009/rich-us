"""美股 Top 500 榜单 API。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Query

from .. import rankings as rankmod
from ..scoring import DEFAULT_THRESHOLD, DEFAULT_WEIGHTS
from .deps import CurrentUser
from .watchlist import annotate_watched

router = APIRouter(prefix="/market/rankings", tags=["榜单"])

# ⚠️ 排序白名单**只在一处定义**（rankings.SORT_FIELDS），这里动态生成正则。
# 原先是硬编码的 6 个 key —— 加了新指标却忘了同步这里，前端一点新列头就 422。
_SORT_PATTERN = "^(" + "|".join(rankmod.SORT_FIELDS) + ")$"


def _parse_weights(raw: str) -> dict:
    """解析四维权重。非法输入一律回落默认值 —— 不能因为一个坏参数让整页 500。"""
    if not raw:
        return dict(DEFAULT_WEIGHTS)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else dict(DEFAULT_WEIGHTS)
    except (json.JSONDecodeError, TypeError):
        return dict(DEFAULT_WEIGHTS)


@router.get("")
def get_rankings(
    user: CurrentUser,
    sort: str = Query("change_pct", pattern=_SORT_PATTERN),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=3000),
    q: str = "",
    sector: str = "",
    pe_min: float | None = Query(None, ge=-1e4, le=1e4, description="市盈率下限（TTM）"),
    pe_max: float | None = Query(None, ge=-1e4, le=1e4, description="市盈率上限（TTM）"),
    pb_max: float | None = Query(None, ge=0, le=1e4, description="市净率上限"),
    cap_min: float | None = Query(None, ge=0, description="总市值下限（亿美元）"),
    div_min: float | None = Query(None, ge=0, le=100, description="股息率下限（%）"),
    roe_min: float | None = Query(None, ge=-1e4, le=1e4, description="ROE 下限（%）"),
    from_high_max: float | None = Query(
        None, ge=-100, le=0,
        description="距 52 周高上限（%）。-30 表示「从高点回撤至少 30%」（超跌筛选）",
    ),
    exclude_loss: bool = Query(False, description="排除亏损标的（EPS ≤ 0，PE 无意义）"),
    # ---- 技术面（需 1 年日线；数据未就绪时这些筛选会排除该标的）----
    rsi_min: float | None = Query(None, ge=0, le=100, description="RSI(14) 下限"),
    rsi_max: float | None = Query(None, ge=0, le=100, description="RSI(14) 上限"),
    above_ma200: bool = Query(False, description="只看站上 200 日均线的标的"),
    below_ma200: bool = Query(False, description="只看跌破 200 日均线的标的"),
    vol_max: float | None = Query(None, ge=0, le=500, description="年化波动率上限（%）"),
    beta_max: float | None = Query(None, ge=-5, le=10, description="Beta 上限（相对 SPY）"),
    req_1y_min: float | None = Query(None, ge=-100, le=1000, description="近 1 年收益下限（%）"),
    excess_min: float | None = Query(None, ge=-100, le=1000, description="相对 SPY 超额收益下限（%）"),
    only_bull: bool = Query(False, description="只看均线多头排列（价 > MA20 > MA60 > MA200）"),
    # ---- 综合评分 ----
    score_min: float | None = Query(None, ge=0, le=100, description="综合评分下限（0~100）"),
    threshold: float = Query(DEFAULT_THRESHOLD, ge=0, le=100, description="候选池分档阈值"),
    weights: str = Query("", description='四维权重 JSON，如 {"valuation":30,"quality":30,"position":20,"trend":20}'),
    # ---- 选股中心信号 ----
    signal: str = Query("", max_length=32, description="只看触发了该信号（key）的标的，空 = 不过滤"),
) -> dict:
    res = rankmod.rankings(
        sort=sort, direction=direction, limit=limit, q=q, sector=sector,
        pe_min=pe_min, pe_max=pe_max, pb_max=pb_max, cap_min=cap_min,
        div_min=div_min, roe_min=roe_min, from_high_max=from_high_max,
        exclude_loss=exclude_loss,
        rsi_min=rsi_min, rsi_max=rsi_max, above_ma200=above_ma200,
        below_ma200=below_ma200, vol_max=vol_max, beta_max=beta_max,
        score_min=score_min, only_bull=only_bull,
        req_1y_min=req_1y_min, excess_min=excess_min,
        signal=signal,
        weights=_parse_weights(weights), threshold=threshold,
    )
    # name_cn / market_cap / 估值字段已在 rankmod.rankings 注入；这里只补 watched
    res["rows"] = annotate_watched(res["rows"])
    return res


@router.post("/refresh-quotes")
def refresh_rankings(user: CurrentUser) -> dict:
    """触发后台强制刷新（立即返回，不阻塞 —— 由 stale-while-revalidate 接管）。

    行情 / 基本面 / 技术指标一起刷：三者是不同 TTL 的独立缓存，只刷一个会让
    PE 与现价脱节、或评分与实际均线脱节。
    """
    rankmod.quotes(force=True)
    syms = [c["symbol"] for c in rankmod.constituents()["constituents"]]
    try:
        from ..fundamentals import snapshot as _f_snapshot

        _f_snapshot(syms, force=True)
    except Exception:  # noqa: BLE001 —— 基本面刷新失败不影响行情
        pass
    try:
        from ..technicals import snapshot as _t_snapshot

        _t_snapshot(syms, force=True)
    except Exception:  # noqa: BLE001 —— 技术指标刷新失败不影响行情
        pass
    return {"ok": True, "refreshing": True}


@router.get("/movers")
def get_movers(
    user: CurrentUser,
    threshold: float = Query(3.0, ge=0.5, le=20, description="暴涨暴跌阈值（%），如 3 表示 ±3%"),
    limit: int = Query(15, ge=1, le=50, description="涨/跌榜各返回多少只"),
    force: bool = Query(False, description="强制刷新行情（手动刷新按钮用；立即返回旧数据，后台抓完由下次轮询取到）"),
) -> dict:
    """每日开盘监控：美股全池（~2240 只）+ 全市场涨跌幅榜补盲，实时扫描。

    stale-while-revalidate：永远秒回，行情在后台按 TTL 节律刷新。
    非盘中时返回最近交易日快照并带 note 说明；命中行带当日上榜统计。
    响应含常驻监控任务状态（monitor：enabled/running/scans/last_scan）
    与行情真实更新时刻（quotes_updated）。
    """
    from ..movers import monitor_status, movers

    res = movers(threshold=threshold, limit=limit, force=force)
    res["monitor"] = monitor_status()
    return res


@router.post("/movers/monitor")
def set_movers_monitor(user: CurrentUser, payload: dict = Body(default={})) -> dict:
    """开启 / 关停常驻监控，或只改参数（threshold / interval / model）。

    配置持久化到 state（movers_monitor 键），服务重启后 lifespan 自动恢复。
    enabled=true 立即起后台扫描线程；false 立即停。
    """
    from ..movers import set_monitor_cfg

    return set_monitor_cfg(
        enabled=payload.get("enabled"),
        threshold=payload.get("threshold"),
        interval=payload.get("interval"),
        model=payload.get("model"),
    )


@router.post("/movers/analyze")
def analyze_movers(user: CurrentUser, payload: dict = Body(default={})) -> dict:
    """AI 解读当前暴涨/暴跌榜单。

    model：QD_AI_EXTRA_MODELS 别名 / 网关模型 id（如 cn:glm-5.3-flash）/ 空 = 设置页默认模型。
    与「设置 → AI 分析」「AI Copilot」共用同一套接入与解析顺序。
    """
    from ..movers import analyze

    return analyze(
        model=str(payload.get("model") or ""),
        threshold=payload.get("threshold") or 3.0,
        limit=min(int(payload.get("limit") or 10), 20),
    )


@router.get("/premarket")
def premarket_overview(
    user: CurrentUser,
    threshold: float = Query(2.0, ge=0.5, le=20, description="盘前异动阈值（%），盘前流动性薄默认 2%"),
    limit: int = Query(12, ge=1, le=30, description="涨/跌各取前 N 只"),
    with_news: bool = Query(True, description="是否附新闻标题（并发抓取 yahoo-rss）"),
    force: bool = Query(False, description="强制刷新盘前数据（手动刷新按钮用；立即返回旧数据，后台抓完由下次轮询取到）"),
) -> dict:
    """盘前监控：美东 04:00–09:30 的盘前价 / 涨跌幅 / 盘前量 + 新闻标题。

    非盘前时段返回最近一次盘前快照并带时段说明（前端据此展示）。
    响应带 quotes_updated = 盘前数据真实抓取完成的时刻。
    """
    from ..premarket import movers

    return movers(threshold=threshold, limit=limit, with_news=with_news, force=force)


@router.post("/premarket/analyze")
def premarket_analyze(
    user: CurrentUser,
    model: str = Query("", max_length=64, description="AI 模型（空 = 默认配置）"),
    threshold: float = Query(2.0, ge=0.5, le=20),
) -> dict:
    """AI 盘前综述：top movers + 新闻 → 盘前主线 / 重点关注 / 风险。

    LLM 失败自动降级本地统计（engine="local"）。
    """
    from ..premarket import analyze as _analyze

    return _analyze(model=model, threshold=threshold)


@router.get("/signal-catalog")
def signal_catalog(user: CurrentUser) -> dict:
    """信号目录：每个信号的名称 / 类型 / 触发条件 / 逻辑 / 局限。

    选股中心的「说明」来源 —— 前端渲染 tooltip 与折叠目录都吃这份数据，
    与 signals.py 的注入规则是同一份单一事实源。
    """
    from ..signals import SIGNAL_DEFS

    return {"signals": SIGNAL_DEFS}


@router.get("/profile")
def company_profile(
    user: CurrentUser,
    symbol: str = Query(..., min_length=1, max_length=32),
    force: bool = False,
) -> dict:
    """公司档案：英文名 / 行业 / 英文介绍（longBusinessSummary）/ 市值 / 官网。缓存 30 天。"""
    from ..company import get_profile

    return get_profile(symbol, force=force)
