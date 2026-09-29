"""榜单的**派生字段注入层**：把原始行情补齐成「可排序、可筛选、可评分」的行。

为什么从 `rankings.py` 拆出来（铁律 9）
--------------------------------------
`rankings.py` 的职责是「抓行情 + 组装榜单」；而这里四个函数做的是另一件事 ——
把三个**独立缓存**（基本面 / 技术指标 / 评分）的字段合并进每一行。
两者一起放会超过后端 600 行软上限，且混在一起后「哪些字段从哪来」变得难以追。

调用顺序是**硬约束**，不可颠倒（`rankings.rankings()` 里已按此顺序调用）：
    1. `attach_fundamentals`  —— 先有 PE / PB / ROE / 股息率
    2. `attach_technicals`    —— 再有均线 / RSI / 波动率 / Beta
    3. `add_pe_percentile`    —— PE 分位依赖第 1 步的 PE
    4. `attach_scores`        —— 评分依赖分位（估值维度用 `pe_pct`）
    → 之后才允许筛选与排序（评分本身也是可排序字段）

⚠️ 这里的每个函数都必须「永不阻塞网络」：三个缓存模块都是
stale-while-revalidate，冷启动返回空值 + 后台线程补，前端据此显示「补齐中」。
"""
from __future__ import annotations

from typing import Any


def attach_fundamentals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """注入估值字段并合成 PE / ROE。**必须在排序与筛选之前调用。**"""
    from .fundamentals import meta as f_meta
    from .fundamentals import snapshot as f_snapshot

    fields = f_snapshot([r["symbol"] for r in rows])
    covered = 0
    for r in rows:
        f = fields.get(r["symbol"]) or {}
        price = r.get("price")
        eps, raw_pe, pb = f.get("eps_ttm"), f.get("pe_ttm"), f.get("pb")

        # PE 实时合成：榜单现价 ÷ 缓存 EPS。这正是 PE 不能落长缓存的理由 ——
        # 存下来的 PE 会随价格漂移，而 EPS 一个季度才变一次。
        pe: float | None = None
        state = "na"
        if isinstance(eps, (int, float)) and isinstance(price, (int, float)) and price > 0:
            if eps > 0:
                pe, state = round(price / eps, 2), "ok"
            else:
                state = "loss"              # 亏损：PE 无意义，前端显示「亏损」
        elif isinstance(raw_pe, (int, float)) and raw_pe > 0:
            pe, state = round(raw_pe, 2), "ok"    # 没有 EPS 时回落腾讯原始 PE

        # ROE = PB ÷ PE。用腾讯**原始** PE 而非合成 PE —— ROE 与价格无关。
        # 上限 300%：超过这个数几乎一定是「净资产趋近 0」（大额回购 / 累计亏损）
        # 让分母塌缩，而不是盈利能力强。实测不设限时按 ROE 排序会把 GDDY(12725%)、
        # MTD(6930%)、CL(858%) 顶到最前 —— 这些数字对选股毫无意义。
        roe = None
        if isinstance(pb, (int, float)) and isinstance(raw_pe, (int, float)) and raw_pe > 0:
            _roe = pb / raw_pe * 100
            if 0 < _roe <= 300:
                roe = round(_roe, 1)

        hi = f.get("w52_high")
        pct_high = None
        if isinstance(hi, (int, float)) and hi > 0 and isinstance(price, (int, float)) and price > 0:
            pct_high = round((price - hi) / hi * 100, 1)

        r.update({
            "eps_ttm": eps, "pe_ttm": pe, "pe_state": state, "pb": pb, "roe": roe,
            "div_yield": f.get("div_yield"), "turnover": f.get("turnover"),
            "amplitude": f.get("amplitude"), "w52_high": hi, "w52_low": f.get("w52_low"),
            "pct_from_high": pct_high, "market_cap_float": f.get("market_cap_float"),
        })
        if f.get("market_cap"):             # 用腾讯实时总市值覆盖库里的旧值
            r["market_cap"] = f["market_cap"]
        if pe is not None or pb is not None or f.get("div_yield") is not None:
            covered += 1

    m = f_meta()
    return {
        "covered": covered, "rows": len(rows), "cached": m["count"],
        "age_sec": m["age_sec"], "stale": m["stale"],
        "refreshing": m["refreshing"], "last_refresh_ok": m["last_refresh_ok"],
    }


def add_pe_percentile(rows: list[dict[str, Any]]) -> None:
    """计算 PE 在**同行业**内的分位（0~100），用于前端色条与估值评分。

    为什么按行业而不是全市场：银行 PE 14 与软件 PE 40 都可能是"合理"的，
    拿全市场分位会把整个金融板块标成"极度低估"——那是行业属性，不是机会。

    必须在**筛选之前**、对全集计算：否则用户一加筛选条件，分位基准就变了，
    同一只股票的分位会随筛选条件跳来跳去。
    """
    from bisect import bisect_left

    by_sec: dict[str, list[float]] = {}
    for r in rows:
        v = r.get("pe_ttm")
        if isinstance(v, (int, float)) and v > 0:
            by_sec.setdefault(str(r.get("sector") or ""), []).append(float(v))
    for vals in by_sec.values():
        vals.sort()

    for r in rows:
        r["pe_pct"] = None
        v = r.get("pe_ttm")
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        vals = by_sec.get(str(r.get("sector") or "")) or []
        if len(vals) >= 5:          # 样本太少时分位没有统计意义，宁可不显示
            r["pe_pct"] = round(bisect_left(vals, float(v)) / len(vals) * 100)


# 技术指标字段清单：既用于注入，也用于前端「列」菜单与排序白名单对齐
TECH_KEYS = (
    "r1m", "r3m", "r6m", "r1y", "vol_ann", "rsi14", "atr_pct", "beta",
    "ma20_rel", "ma60_rel", "ma200_rel", "ma_bull", "ma_bear", "excess_1y",
)


def attach_technicals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """注入 1 年日线派生的技术指标。**必须在评分与排序之前调用。**

    与 `attach_fundamentals` 一样是 stale-while-revalidate：冷启动时返回空值，
    后台线程去拉（全量实测约 70s）。前端据此显示「技术指标补齐中」而不是空白。
    """
    from .technicals import meta as t_meta
    from .technicals import snapshot as t_snapshot

    fields = t_snapshot([r["symbol"] for r in rows])
    covered = 0
    for r in rows:
        f = fields.get(r["symbol"]) or {}
        for k in TECH_KEYS:
            r[k] = f.get(k)
        if f.get("ma200_rel") is not None:
            covered += 1

    m = t_meta()
    return {
        "covered": covered, "rows": len(rows), "cached": m["count"],
        "age_sec": m["age_sec"], "stale": m["stale"],
        "refreshing": m["refreshing"], "last_refresh_ok": m["last_refresh_ok"],
        "error": m.get("error"),
    }


def attach_scores(rows: list[dict[str, Any]], weights: dict[str, Any] | None,
                  threshold: float) -> None:
    """注入四维评分。**必须在排序/筛选之前调用**（score 是可排序字段）。

    评分是纯函数（`scoring.score_row`），这里只负责批量应用与展开字段。
    """
    from .scoring import band_of
    from .scoring import normalize_weights
    from .scoring import score_row

    w = normalize_weights(weights)
    for r in rows:
        res = score_row(r, w)
        r["score"] = res["score"]
        r["score_band"] = band_of(res["score"], threshold)
        r["score_dims"] = res["dims"]
        r["score_parts"] = res["parts"]
        r["score_coverage"] = res["coverage"]
        r["score_low_conf"] = res["low_confidence"]
