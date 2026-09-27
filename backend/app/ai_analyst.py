"""
AI 分析师
==========
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
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np
import pandas as pd

from .config import settings
from .data_provider import fetch_history, get_quote
from .strategies import indicators as ind


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


# ==================================================================
# 本地量化分析引擎
# ==================================================================
def analyze_local(snap: dict[str, Any], horizon: str = "swing") -> dict[str, Any]:
    if snap.get("error"):
        return {"symbol": snap["symbol"], "error": snap["error"]}

    i = snap["indicators"]
    d = snap["dist"]
    px = snap["price"]

    # ---------- 1. 维度打分（每项 -100 ~ +100）----------
    def score_trend() -> float:
        pts, wts = [], []
        for key, v in (("to_sma20", 15), ("to_sma50", 25), ("to_sma200", 35)):
            dv = d.get(key)
            if dv is None:
                continue
            pts.append(float(np.clip(dv / 5.0, -1, 1)) * 100)
            wts.append(v)
        adx_v, pdi, mdi = i.get("adx14"), i.get("plus_di"), i.get("minus_di")
        if adx_v is not None and pdi is not None and mdi is not None:
            di = float(np.clip((pdi - mdi) / 25.0, -1, 1)) * 100
            strength = min(float(adx_v) / 40.0, 1.0)
            pts.append(di * strength)
            wts.append(25)
        if not pts:
            return 0.0
        return float(np.average(pts, weights=wts))

    def score_momentum() -> float:
        pts = []
        for k in ("1m", "3m", "6m"):
            v = snap["returns"].get(k)
            if v is not None:
                pts.append(float(np.clip(v / 12.0, -1, 1)) * 100)
        hist = i.get("macd_hist")
        if hist is not None:
            pts.append(float(np.clip(hist / (px * 0.01 + 1e-9), -1, 1)) * 100)
        return float(np.mean(pts)) if pts else 0.0

    def score_reversion() -> float:
        """正值表示"超卖、具备反弹动能"。"""
        pts = []
        r = i.get("rsi14")
        if r is not None:
            pts.append(float(np.clip((50 - r) / 25.0, -1, 1)) * 100)
        pb = i.get("bb_pctb")
        if pb is not None:
            pts.append(float(np.clip((0.5 - pb) / 0.4, -1, 1)) * 100)
        z = i.get("zscore20")
        if z is not None:
            pts.append(float(np.clip(-z / 2.0, -1, 1)) * 100)
        return float(np.mean(pts)) if pts else 0.0

    def score_volume() -> float:
        pts = []
        cmf_v = i.get("cmf20")
        if cmf_v is not None:
            pts.append(float(np.clip(cmf_v / 0.15, -1, 1)) * 100)
        os_ = i.get("obv_slope")
        if os_ is not None:
            pts.append(float(np.clip(os_ * 50, -1, 1)) * 100)
        return float(np.mean(pts)) if pts else 0.0

    def score_risk() -> float:
        """风险维度：波动率高 → 负分（降低总体吸引力）。"""
        rv = i.get("rv20")
        rv60 = i.get("rv60")
        if rv is None:
            return 0.0
        base = 0.18
        s = -float(np.clip((rv - base) / base, -1, 1)) * 100
        if rv60 and rv > rv60 * 1.4:
            s -= 25
        if rv60 and rv < rv60 * 0.7:
            s += 20
        return float(np.clip(s, -100, 100))

    horizon_w = {
        "intraday": {"trend": 0.20, "momentum": 0.20, "reversion": 0.35, "volume": 0.15, "risk": 0.10},
        "swing": {"trend": 0.30, "momentum": 0.25, "reversion": 0.20, "volume": 0.10, "risk": 0.15},
        "position": {"trend": 0.35, "momentum": 0.30, "reversion": 0.05, "volume": 0.10, "risk": 0.20},
    }[horizon if horizon in ("intraday", "swing", "position") else "swing"]

    dims = {
        "trend": score_trend(),
        "momentum": score_momentum(),
        "reversion": score_reversion(),
        "volume": score_volume(),
        "risk": score_risk(),
    }
    composite = sum(dims[k] * horizon_w[k] for k in dims)

    # ---------- 2. 状态识别 ----------
    adx_v = i.get("adx14") or 0.0
    er = i.get("efficiency_ratio") or 0.5
    rv = i.get("rv20") or 0.15
    rv60 = i.get("rv60") or 0.15
    hurst_v = i.get("hurst") or 0.5

    if rv > rv60 * 1.6:
        regime, regime_desc = "高波动", "波动率显著抬升，任何策略都应先降低仓位"
    elif adx_v >= 28 and er >= 0.45:
        regime, regime_desc = "趋势市", "趋势强度与效率比同时达标，趋势跟随类策略胜率最高"
    elif adx_v < 20 and er < 0.35:
        regime, regime_desc = "震荡市", "方向性弱、来回摆动，均值回归与网格策略占优"
    else:
        regime, regime_desc = "过渡市", "状态不明确，建议降低仓位或等待信号确认"

    trend_bias = "多头" if composite > 15 else ("空头" if composite < -15 else "中性")
    confidence = float(np.clip(abs(composite) / 60.0, 0.05, 0.95)) * 100

    # ---------- 3. 关键价位 ----------
    a14 = i.get("atr14") or px * 0.02
    atr_pct = (a14 / px * 100) if px else 0.0
    levels = {
        "支撑": sorted([x for x in [
            snap["levels"].get("donchian_lower"), snap["levels"].get("bb_lower"),
            snap["ma"].get("sma50"), snap["levels"].get("low_52w"),
            round(px - 2 * a14, 4),
        ] if x is not None and x < px], reverse=True)[:3],
        "阻力": sorted([x for x in [
            snap["levels"].get("donchian_upper"), snap["levels"].get("bb_upper"),
            snap["ma"].get("sma200"), snap["levels"].get("high_52w"),
            round(px + 2 * a14, 4),
        ] if x is not None and x > px])[:3],
    }

    # ---------- 4. 风险提示 ----------
    warnings: list[str] = []
    if atr_pct > 4:
        warnings.append(f"日均波动 {atr_pct:.1f}%，高于常态，止损应放宽至 ≥{2.5*a14/px*100:.1f}% 以免被噪声扫出")
    if d.get("to_52w_high") is not None and d["to_52w_high"] > -2 and composite < 20:
        warnings.append("价格贴近 52 周高点但动能评分偏弱，存在假突破风险")
    if (i.get("rsi14") or 50) > 75:
        warnings.append("RSI 处于超买区，追高需等待回踩确认")
    if (i.get("rsi14") or 50) < 25:
        warnings.append("RSI 处于超卖区，左侧接刀风险高，建议等待企稳信号")
    if rv > 0.5:
        warnings.append("已实现波动率超过 50%，仓位建议压缩至常态的 1/2 以下")
    if i.get("vol_ratio") and i["vol_ratio"] < 0.6:
        warnings.append(f"量比仅 {i['vol_ratio']:.2f}，成交萎缩，突破可靠性下降")
    if not warnings:
        warnings.append("未检测到显著异常信号，按常规风控执行即可")

    # ---------- 5. 仓位建议 ----------
    target_vol = 0.15
    pos_mult = float(np.clip(target_vol / max(rv, 1e-4), 0.15, 1.5))
    suggested_pct = round(min(abs(composite) / 100.0, 1.0) * pos_mult * 20.0, 1)

    # ---------- 6. 策略匹配 ----------
    matches = _match_strategies(regime, i, composite)

    return {
        "symbol": snap["symbol"],
        "as_of": snap["last_date"],
        "mode": "local",
        "price": px,
        "realtime": snap.get("realtime", {"realtime": False}),
        "bias": trend_bias,
        "composite_score": round(composite, 1),
        "confidence": round(confidence, 1),
        "regime": regime,
        "regime_desc": regime_desc,
        "dimensions": {k: round(v, 1) for k, v in dims.items()},
        "weights": horizon_w,
        "levels": levels,
        "atr_pct": round(atr_pct, 2),
        "suggested_position_pct": suggested_pct,
        "warnings": warnings,
        "strategy_matches": matches,
        "readings": _build_readings(snap),
        "horizon": horizon,
    }


def _build_readings(snap: dict[str, Any]) -> list[dict[str, Any]]:
    i = snap["indicators"]
    d = snap["dist"]
    out: list[dict[str, Any]] = []

    def add(name: str, value: Any, text: str, signal: str = "neutral") -> None:
        out.append({"name": name, "value": value, "reading": text, "signal": signal})

    r = i.get("rsi14")
    if r is not None:
        sig = "bull" if r < 35 else ("bear" if r > 70 else "neutral")
        add("RSI(14)", round(r, 1),
            "超卖区，具备反弹基础" if r < 35 else ("超买区，短线过热" if r > 70 else "中性区间，无极端信号"), sig)

    adx_v = i.get("adx14")
    if adx_v is not None:
        sig = "bull" if adx_v > 25 else "neutral"
        add("ADX(14)", round(adx_v, 1),
            "趋势明确（>25），趋势策略适用" if adx_v > 25 else ("方向不明（<20），均值回归适用" if adx_v < 20 else "趋势初成"),
            sig)

    mh = i.get("macd_hist")
    if mh is not None:
        sig = "bull" if mh > 0 else "bear"
        add("MACD 柱", round(mh, 4), "多头动能占优" if mh > 0 else "空头动能占优", sig)

    pb = i.get("bb_pctb")
    if pb is not None:
        sig = "bull" if pb < 0.15 else ("bear" if pb > 0.85 else "neutral")
        add("布林 %B", round(pb, 3),
            "贴近下轨，超卖" if pb < 0.15 else ("贴近上轨，超买" if pb > 0.85 else "位于通道中部"), sig)

    ap = i.get("atr_pct")
    if ap is not None:
        add("ATR 占比", f"{ap:.2f}%",
            f"日均波幅约 {ap:.2f}%，按 {2.5*ap:.1f}% 设置止损较稳健", "neutral")

    vr = i.get("vol_ratio")
    if vr is not None:
        add("量比", round(vr, 2),
            "放量，资金活跃" if vr > 1.3 else ("缩量，观望情绪浓" if vr < 0.7 else "成交量正常"),
            "bull" if vr > 1.3 else "neutral")

    for key, label in (("to_sma50", "距 SMA50"), ("to_sma200", "距 SMA200")):
        v = d.get(key)
        if v is not None:
            add(label, f"{v:+.2f}%", "位于均线上方（多头结构）" if v > 0 else "位于均线下方（空头结构）",
                "bull" if v > 0 else "bear")

    hv = i.get("hurst")
    if hv is not None:
        add("Hurst 指数", round(hv, 3),
            ">0.5，价格具趋势持续性" if hv > 0.5 else "<0.5，价格倾向均值回归", "neutral")

    er = i.get("efficiency_ratio")
    if er is not None:
        add("效率比", round(er, 3),
            "走势高效，趋势可靠" if er > 0.45 else ("走势拖沓，多为噪声" if er < 0.3 else "效率中等"), "neutral")

    itd = snap.get("intraday")
    if itd:
        dv = itd.get("price_vs_vwap_pct")
        if dv is not None:
            sig = "bull" if dv > 0 else "bear"
            add("分时 VWAP", itd.get("vwap"),
                f"现价{'高于' if dv > 0 else '低于'}VWAP {abs(dv):.2f}%，开盘区间{itd.get('or_position', '—')}"
                + (f"，5 分钟 RSI {itd['rsi14_5m']}" if itd.get("rsi14_5m") is not None else ""),
                sig)

    return out


def _match_strategies(regime: str, ind_data: dict[str, Any], composite: float) -> list[dict[str, str]]:
    pool: list[tuple[str, str, str]] = []
    if regime == "趋势市":
        pool = [
            ("tsmom_vol_target", "时序动量·波动率目标", "波动率目标机制天然适配趋势市，回撤可控"),
            ("vol_managed_momentum", "波动率管理动量", "用已实现方差缩放仓位，趋势市中夏普最优"),
            ("supertrend", "Supertrend 超级趋势", "ATR 通道跟随，趋势市入场早、持仓久"),
            ("trend_composite", "趋势综合评分", "多证据融合，换手低、稳健"),
            ("donchian_breakout", "唐奇安通道突破", "突破顺势，正偏度收益结构"),
        ]
    elif regime == "震荡市":
        pool = [
            ("rsi_meanrev", "RSI 超卖反转", "震荡市高胜率，配合 200 日均线过滤"),
            ("bollinger_meanrev", "布林带均值回归", "触轨反转，带宽分位过滤无效区间"),
            ("grid_trading", "ATR 自适应网格", "震荡市收益最稳定的一类机械策略"),
            ("pairs_trading", "协整配对交易", "市场中性，与大盘方向无关"),
            ("keltner_reversion", "肯特纳通道回归", "ATR 口径对跳空更鲁棒"),
        ]
    elif regime == "高波动":
        pool = [
            ("regime_adaptive", "状态自适应切换", "极端波动时自动降仓，最稳的选择"),
            ("risk_parity_alloc", "风险平价配置", "按波动率倒数分配，天然抗波动抬升"),
            ("keltner_reversion", "肯特纳通道回归", "ATR 通道随波动放宽，不易被扫"),
            ("gap_fade", "跳空回补", "高波动日跳空频繁，回补机会多（须严格止损）"),
        ]
    else:
        pool = [
            ("regime_adaptive", "状态自适应切换", "过渡市首选，自动在趋势与回归间切换"),
            ("ensemble_vote", "多策略集成投票", "集成多条腿，降低单策略失效风险"),
            ("risk_parity_alloc", "风险平价配置", "底仓型配置，稳定优先"),
        ]
    if composite < -20:
        pool.insert(0, ("zscore_reversion", "Z 分数回归（含做空）", "当前偏空，可启用做空腿或保持空仓"))
    return [{"key": k, "name": n, "reason": r} for k, n, r in pool[:5]]


# ==================================================================
# LLM 模式
# ==================================================================
def ai_configured() -> bool:
    return bool(settings.ai_base_url and settings.ai_api_key)


def extra_ai_models() -> list[dict[str, str]]:
    """T-109：解析 QD_AI_EXTRA_MODELS（"name|base_url|api_key|model;..."）。"""
    out: list[dict[str, str]] = []
    for part in (settings.ai_extra_models or "").split(";"):
        seg = [x.strip() for x in part.split("|")]
        if len(seg) == 4 and all(seg):
            out.append({"name": seg[0], "base_url": seg[1], "api_key": seg[2], "model": seg[3]})
    return out


def _llm_config_for(name: str = "") -> tuple[str, str, str]:
    """返回 (base_url, api_key, model)。name 为空或未匹配 → 默认配置。"""
    if name:
        for cfg in extra_ai_models():
            if cfg["name"] == name:
                return cfg["base_url"], cfg["api_key"], cfg["model"]
    return settings.ai_base_url or "", settings.ai_api_key or "", settings.ai_model or ""


def _llm_call(messages: list[dict[str, str]], temperature: float = 0.3, max_tokens: int = 1400,
              model_name: str = "") -> str:
    url, api_key, model = _llm_config_for(model_name)
    if not (url and api_key):
        raise RuntimeError("LLM 未配置")
    url = url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions" if url.endswith("/v1") else f"{url}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=90) as c:
        r = c.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


SYSTEM_PROMPT = """你是一位严谨的量化交易分析师，服务于专业交易员。
要求：
1. 只基于给定数据推理，不得编造价格、财报或新闻事实。
2. 明确区分「数据事实」与「概率判断」，判断必须给出依据。
3. 输出使用简体中文，结构化、可执行，避免空泛套话。
4. 必须给出：状态判定、多空观点、关键价位、风控（止损位与仓位）、失效条件。
5. 结尾必须包含一句风险提示。"""


def _news_context(symbol: str, limit: int = 5) -> list[dict[str, Any]]:
    """取该标的最近新闻标题（供 LLM 参考事件面）。失败返回空，绝不阻塞分析。"""
    try:
        from .news import fetch_news

        res = fetch_news(symbol, limit=limit)
        return [
            {
                "标题": it.get("headline", ""),
                "时间": (it.get("published_at") or "")[:16],
                "来源": it.get("source", ""),
                "类型": it.get("category", ""),
            }
            for it in res.get("items", [])
        ]
    except Exception:  # noqa: BLE001
        return []


def analyze_with_llm(snap: dict[str, Any], horizon: str = "swing", question: str = "",
                     model_name: str = "") -> dict[str, Any]:
    local = analyze_local(snap, horizon)
    context = {
        "标的": snap["symbol"], "现价": snap["price"], "数据日期": snap["last_date"],
        "区间收益%": snap["returns"], "均线": snap["ma"], "偏离%": snap["dist"],
        "关键价位": snap["levels"], "指标": snap["indicators"],
        "本地量化引擎结论": {
            "状态": local.get("regime"), "多空": local.get("bias"),
            "综合评分": local.get("composite_score"), "维度分": local.get("dimensions"),
            "建议仓位%": local.get("suggested_position_pct"),
        },
    }
    rt = snap.get("realtime") or {}
    if rt.get("realtime"):
        q = snap.get("quote") or {}
        context["实时盘"] = {
            "实时价": snap["price"],
            "日内涨跌%": q.get("change_pct"),
            "日内最高": q.get("day_high"), "日内最低": q.get("day_low"),
            "报价来源": rt.get("quote_source"), "报价时间": rt.get("quote_ts"),
            "说明": "以上指标已融合实时价计算，非昨日收盘",
        }
    itd = snap.get("intraday")
    if itd:
        context["分钟级结构"] = itd
    news_items = _news_context(snap["symbol"])
    if news_items:
        context["最近新闻与公告"] = news_items
    prompt = (
        f"以下是 {snap['symbol']} 的量化快照（JSON）：\n{json.dumps(context, ensure_ascii=False, indent=1)}\n\n"
        f"投资周期：{horizon}。\n"
        f"{'用户追问：' + question if question else ''}\n"
        "请输出：\n## 状态判定\n## 多空观点（含依据与置信度）\n## 关键价位（支撑/阻力/止损/目标）\n"
        "## 执行建议（仓位、入场方式、加减仓条件）\n## 失效条件（什么情况下判断作废）\n## 风险提示"
        + ("\n若提供了最近新闻与公告，请在观点中评估事件面影响；只引用给定新闻，不得编造。"
           if news_items else "")
    )
    try:
        text = _llm_call([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                         model_name=model_name)
        local["llm_report"] = text
        local["mode"] = "llm"
    except Exception as exc:  # noqa: BLE001
        local["llm_error"] = f"{type(exc).__name__}: {exc}"
        local["llm_report"] = ""
    return local


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
