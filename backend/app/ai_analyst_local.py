"""本地量化分析引擎（ai_analyst 的「B 模式」）。

从 ai_analyst.py 按铁律 9（FILE_SIZE_DEBT Batch D-4）拆出：
- `analyze_local`：六维打分 → 状态识别 → 关键价位 → 风险提示 → 仓位 → 策略匹配；
- `_build_readings`：指标逐项解读；
- `_match_strategies`：状态 → 内置策略库匹配。

完全基于数据推导，结果确定性、可复现、可解释 —— 不是"占位文本"。
对 LLM 模块零依赖（ai_analyst_llm 反向 import 本模块）。
"""
from __future__ import annotations

from typing import Any

import numpy as np


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
