"""
AI 分析师（门面模块）
====================
两种模式：
  A. LLM 模式（配置了 QD_AI_BASE_URL + QD_AI_API_KEY）
     把量化快照作为上下文交给任意 OpenAI 兼容接口，返回结构化解读。
  B. 本地量化引擎（默认，无需任何外部服务）
     完全基于数据推导：趋势/动量/波动率/量能/状态识别/关键价位/风险提示。
     结果确定性、可复现、可解释 —— 这不是"占位文本"，而是真实计算出的结论。

本地引擎输出：
  · 状态判定（趋势/震荡/高波动，含置信度）
  · 多空评分（-100 ~ 100，由 6 个维度加权）
  · 关键价位（支撑/阻力/枢轴/ATR 目标）
  · 指标明细（每项附读法与解读）
  · 风险提示与仓位建议
  · 策略匹配建议（从内置策略库中挑选与当前状态最契合的）

结构（铁律 9 / FILE_SIZE_DEBT Batch D-4）：
  · 数据准备 + analyze 门面 + 组合视角 → 本文件；
  · 本地规则引擎 → ai_analyst_local.py；
  · LLM 路径（网关配置 / 调用 / 提示词）→ ai_analyst_llm.py；
  · 下方 re-export 保持 `from app.ai_analyst import _llm_call` 等旧引用路径不变。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from .data_provider import fetch_history, get_quote
from .strategies import indicators as ind

# 门面 re-export：测试与外部调用一直从 ai_analyst 取这些名字（含运行时打桩，
# 如 run_checks 对 ai_configured / _news_context / market_snapshot / analyze_local
# 的 monkeypatch —— 它们都在调用时经本模块属性解析，必须继续可写）。
from .ai_analyst_llm import (  # noqa: E402,F401
    SYSTEM_PROMPT,
    _llm_call,
    _llm_config_for,
    _news_context,
    _runtime_ai,
    ai_configured,
    analyze_with_llm,
    extra_ai_models,
)
from .ai_analyst_local import (  # noqa: E402,F401
    _build_readings,
    _match_strategies,
    analyze_local,
)


# ==================================================================
# 数据准备
# ==================================================================
def _merge_realtime(df: pd.DataFrame, quote: dict | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """把实时报价融合进日线序列，使所有指标反映**盘中实时价**而非昨日收盘。

    曾 symptom：AI 研判"根本不是实时盘的数据"。旧实现 price/指标全部取自
    日线 df（缓存 TTL 6h，盘中最后一根往往是昨日收盘），实时 quote 只作为
    附件展示、不参与计算 —— 对日内交易而言整个分析建立在过期价格上。

    规则：
      · 报价日期 == 序列最后一根 → 盘中更新该根的 close/high/low/volume；
      · 报价日期 > 最后一根（缓存止于昨日）→ 追加今日实时 bar；
      · 报价日期 < 最后一根（休市/旧报价）→ 不动序列，仅标记。
    返回 (融合后的 df, realtime 信息块)。
    """
    info: dict[str, Any] = {"realtime": False}
    if df is None or df.empty or not isinstance(quote, dict) or quote.get("price", 0) <= 0:
        return df, info
    try:
        px = float(quote["price"])
        src = str(quote.get("source", ""))
        ts_raw = str(quote.get("ts") or "")
        try:
            q_day = pd.Timestamp(ts_raw[:10])
        except Exception:  # noqa: BLE001
            q_day = pd.Timestamp.now().normalize()
        last_day = df.index[-1].normalize()

        if q_day == last_day:
            # 同一根 bar：盘中实时更新
            dh = float(quote.get("day_high") or px)
            dl = float(quote.get("day_low") or px)
            ci = df.columns.get_loc("close")
            hi = df.columns.get_loc("high")
            lo = df.columns.get_loc("low")
            df.iloc[-1, ci] = px
            df.iloc[-1, hi] = max(float(df.iloc[-1, hi]), dh, px)
            df.iloc[-1, lo] = min(float(df.iloc[-1, lo]), dl, px)
            if quote.get("volume"):
                vi = df.columns.get_loc("volume")
                df.iloc[-1, vi] = max(float(df.iloc[-1, vi]), float(quote["volume"]))
            info = {"realtime": True, "mode": "intraday_update"}
        elif q_day > last_day:
            # 缓存止于昨日：追加今日实时 bar
            o = float(quote.get("open") or px)
            h = max(float(quote.get("day_high") or px), o, px)
            l = min(float(quote.get("day_low") or px), o, px)
            v = float(quote.get("volume") or 0.0)
            row = pd.DataFrame(
                {"open": [o], "high": [h], "low": [l], "close": [px], "volume": [v]},
                index=[q_day],
            )
            df = pd.concat([df, row])
            df = df[~df.index.duplicated(keep="last")].sort_index()
            info = {"realtime": True, "mode": "appended_today"}
        else:
            info = {"realtime": False,
                    "note": f"报价日期 {q_day.date()} 早于最后一根 bar {last_day.date()}（可能休市）"}
        info.update({"quote_source": src, "quote_ts": ts_raw, "realtime_price": px})
    except Exception as exc:  # noqa: BLE001 —— 实时融合失败绝不阻塞分析，退化为纯日线
        info = {"realtime": False, "note": f"融合失败 {type(exc).__name__}: {exc}"[:120]}
    return df, info


def _intraday_structure(symbol: str) -> dict[str, Any] | None:
    """当日分钟级结构（T-104）：分时 VWAP / 开盘区间 / 分钟 RSI / 日内波动。"""
    try:
        start = datetime.now().strftime("%Y-%m-%d")
        df, src = fetch_history(symbol, start=start, interval="5m")
        if df.empty:
            return None
        day = df.index[-1].normalize()
        df = df[df.index.normalize() == day]
        if len(df) < 6:
            return None
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        vwap = float((c * v).sum() / max(float(v.sum()), 1e-9))
        last_px = float(c.iloc[-1])
        or_high = float(h.head(6).max())     # 开盘 30 分钟（6 根 5m）
        or_low = float(l.head(6).min())
        rsi_m = ind.rsi(c, 14)
        rsi_val = None if rsi_m is None or pd.isna(rsi_m.iloc[-1]) else round(float(rsi_m.iloc[-1]), 1)
        rets = c.pct_change().dropna()
        rv = float(rets.std() * (96 ** 0.5) * 100) if len(rets) > 10 else None   # 日化 %
        pos = "上破" if last_px > or_high else ("下破" if last_px < or_low else "区间内")
        return {
            "source": src, "bars_5m": int(len(df)),
            "vwap": round(vwap, 4),
            "price_vs_vwap_pct": round((last_px / vwap - 1) * 100, 2) if vwap else None,
            "opening_range": {"high": round(or_high, 4), "low": round(or_low, 4)},
            "or_position": pos,
            "rsi14_5m": rsi_val,
            "intraday_vol_pct": round(rv, 2) if rv else None,
            "day_high": round(float(h.max()), 4), "day_low": round(float(l.min()), 4),
        }
    except Exception:  # noqa: BLE001
        return None


def market_snapshot(symbol: str, lookback_days: int = 400, with_intraday: bool = False) -> dict[str, Any]:
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    df, source = fetch_history(symbol, start=start, interval="1d")
    if df.empty:
        return {"symbol": symbol, "error": "无数据", "source": source}

    quote = get_quote(symbol)
    df, rt = _merge_realtime(df, quote)

    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    sma20, sma50, sma200 = ind.sma(c, 20), ind.sma(c, 50), ind.sma(c, 200)
    r = ind.rsi(c, 14)
    m = ind.macd(c)
    a = ind.atr(h, l, c, 14)
    bb = ind.bollinger(c, 20, 2)
    ad = ind.adx(h, l, c, 14)
    rv20 = ind.realized_vol(c, 20)
    rv60 = ind.realized_vol(c, 60)
    vr = ind.volume_ratio(v, 20)
    z = ind.zscore(c, 20)
    don = ind.donchian(h, l, 20)
    er = ind.efficiency_ratio(c, 20)
    hv = ind.hurst(c, 128)

    def last(s: pd.Series, r_: int = 0) -> float | None:
        try:
            val = s.iloc[-1 - r_]
            return None if pd.isna(val) else float(val)
        except (IndexError, KeyError):
            return None

    high_52w = float(h.tail(252).max()) if len(h) >= 60 else float(h.max())
    low_52w = float(l.tail(252).min()) if len(l) >= 60 else float(l.min())
    px = float(c.iloc[-1])

    snap = {
        "symbol": symbol,
        "source": source,
        "bars": len(df),
        "last_date": str(df.index[-1])[:10],
        "price": px,
        "quote": quote,
        "realtime": rt,
        "returns": {
            "1d": _pct(c, 1), "5d": _pct(c, 5), "1m": _pct(c, 21),
            "3m": _pct(c, 63), "6m": _pct(c, 126), "1y": _pct(c, 252),
            "ytd": _ytd(c),
        },
        "ma": {"sma20": last(sma20), "sma50": last(sma50), "sma200": last(sma200)},
        "dist": {
            "to_sma20": _rel(px, last(sma20)), "to_sma50": _rel(px, last(sma50)),
            "to_sma200": _rel(px, last(sma200)),
            "to_52w_high": _rel(px, high_52w), "to_52w_low": _rel(px, low_52w),
        },
        "levels": {
            "high_52w": round(high_52w, 4), "low_52w": round(low_52w, 4),
            "donchian_upper": last(don["upper"]), "donchian_lower": last(don["lower"]),
            "bb_upper": last(bb["upper"]), "bb_mid": last(bb["mid"]), "bb_lower": last(bb["lower"]),
            "pivot": round((high_52w + low_52w + px) / 3, 4),
            "atr14": last(a),
        },
        "indicators": {
            "rsi14": last(r),
            "macd": last(m["macd"]), "macd_signal": last(m["signal"]), "macd_hist": last(m["hist"]),
            "atr14": last(a), "atr_pct": last(ind.natr(h, l, c, 14)),
            "bb_pctb": last(bb["pctb"]), "bb_width": last(bb["width"]),
            "adx14": last(ad["adx"]), "plus_di": last(ad["plus_di"]), "minus_di": last(ad["minus_di"]),
            "rv20": last(rv20), "rv60": last(rv60),
            "vol_ratio": last(vr), "cmf20": last(ind.cmf(h, l, c, v, 20)),
            "zscore20": last(z), "efficiency_ratio": last(er), "hurst": hv,
            "obv_slope": _slope(ind.obv(c, v).tail(20)),
        },
        "series_tail": {
            "dates": [str(d)[:10] for d in df.index[-120:]],
            "close": [round(float(x), 4) for x in c.tail(120)],
            "sma50": [None if pd.isna(x) else round(float(x), 4) for x in sma50.tail(120)],
            "sma200": [None if pd.isna(x) else round(float(x), 4) for x in sma200.tail(120)],
            "rsi": [None if pd.isna(x) else round(float(x), 2) for x in r.tail(120)],
            "volume": [round(float(x), 0) for x in v.tail(120)],
        },
    }
    if with_intraday:
        snap["intraday"] = _intraday_structure(symbol)
    return snap

def _pct(c: pd.Series, n: int) -> float | None:
    if len(c) <= n:
        return None
    return round(float(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100, 2)


def _ytd(c: pd.Series) -> float | None:
    try:
        year_start = c[c.index.year == c.index[-1].year]
        if len(year_start) < 2:
            return None
        return round(float(c.iloc[-1] / year_start.iloc[0] - 1) * 100, 2)
    except Exception:  # noqa: BLE001
        return None


def _rel(a: float, b: float | None) -> float | None:
    if b is None or b == 0:
        return None
    return round((a / b - 1) * 100, 2)


def _slope(s: pd.Series) -> float | None:
    try:
        y = s.dropna().to_numpy(dtype=float)
        if len(y) < 5:
            return None
        x = np.arange(len(y), dtype=float)
        return round(float(np.polyfit(x, y, 1)[0] / (abs(y.mean()) + 1e-9)), 6)
    except Exception:  # noqa: BLE001
        return None


def analyze(symbols: list[str], horizon: str = "swing", question: str = "", use_llm: bool = False,
            use_intraday: bool = False, model_name: str = "") -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    snaps: list[dict[str, Any]] = []
    for s in symbols[:12]:
        snap = market_snapshot(s, with_intraday=use_intraday or horizon == "intraday")
        snaps.append(snap)
        if use_llm and (ai_configured() or model_name) and not snap.get("error"):
            results.append(analyze_with_llm(snap, horizon, question, model_name))
        else:
            r = analyze_local(snap, horizon)
            r["mode"] = "local"
            results.append(r)

    portfolio_view = _portfolio_view(snaps, results) if len(results) > 1 else None
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "engine": "llm" if (use_llm and ai_configured()) else "local",
        "llm_available": ai_configured(),
        "results": results,
        "portfolio": portfolio_view,
        "snapshots": snaps,
    }


def _portfolio_view(snaps: list[dict], results: list[dict]) -> dict[str, Any]:
    valid = [(s, r) for s, r in zip(snaps, results) if not s.get("error") and "composite_score" in r]
    if not valid:
        return {}
    scores = {r["symbol"]: r["composite_score"] for _, r in valid}
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    corr = _correlation({s["symbol"]: s for s, _ in valid})
    avg_rv = float(np.mean([s["indicators"].get("rv20") or 0.2 for s, _ in valid]))
    return {
        "ranking": [{"symbol": k, "score": v} for k, v in ranked],
        "strongest": ranked[0][0] if ranked else "",
        "weakest": ranked[-1][0] if ranked else "",
        "avg_volatility": round(avg_rv, 4),
        "suggested_gross_pct": round(float(np.clip(0.15 / max(avg_rv, 1e-4), 0.2, 1.2)) * 100, 1),
        "correlation": corr,
        "concentration_note": (
            "候选标的平均相关性偏高，建议控制在 3 个以内持仓以降低集中度风险"
            if corr and np.mean([abs(v) for row in corr.values() for v in row.values() if v is not None]) > 0.7
            else "相关性结构健康，可按评分顺序分批建仓"
        ),
    }


def _correlation(snap_map: dict[str, dict]) -> dict[str, dict[str, float | None]] | None:
    ser: dict[str, pd.Series] = {}
    for sym, snap in snap_map.items():
        st = snap.get("series_tail") or {}
        if st.get("close") and len(st["close"]) > 30:
            ser[sym] = pd.Series(st["close"])
    if len(ser) < 2:
        return None
    df = pd.DataFrame(ser)
    corr = df.pct_change().corr()
    return {
        a: {b: (None if pd.isna(corr.loc[a, b]) else round(float(corr.loc[a, b]), 3)) for b in corr.columns}
        for a in corr.index
    }
