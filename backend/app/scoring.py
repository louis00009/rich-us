"""候选观察池评分：四维白盒打分。

⚠️ 这不是「买入信号」，页面上必须这么标注
------------------------------------------
本项目自己的复盘结论（2026-09-27 审计）：规则化策略在**收益上打不过买入持有**
（同期 SPY +245%、QQQ +404%），其真实价值在**回撤控制**。所以任何「按规则挑出来的
股票会涨」的说法在本项目内都没有证据支撑。

这个模块只做一件事：把 503 只缩到用户愿意逐个看的一小撮，并且**每一分都能回看到
是哪条规则给的**（`parts` 字段）。判断仍然归用户。

为什么是加性评分而不是布尔筛子
------------------------------
布尔筛子在边界上是非黑即白的：ROE 14.9% 与 15.1% 被分到两个世界，而实际差别可以
忽略。加性评分让「便宜但质量一般」与「贵但极优质」都浮现出来，由用户自己权衡 ——
这也符合用户的选择（「白盒评分 + 可调阈值」）。

缺失值语义（最重要的一条）
--------------------------
**缺数据的维度不计入总分，权重重新归一，并降置信度。**
反面做法（把缺失当 0 分）会让数据不全的股票被系统性判成「差」——
而腾讯不覆盖的那 50 多只小票恰好就是这种，它们会全部沉底，且没有任何提示。
"""
from __future__ import annotations

from typing import Any

# 四个维度的默认权重。用户可在页面上关掉某一维（权重置 0）。
DEFAULT_WEIGHTS: dict[str, float] = {
    "valuation": 0.30,   # 估值：便宜度
    "quality": 0.30,     # 质量：赚钱能力
    "position": 0.20,    # 位置：相对 52 周高的深浅
    "trend": 0.20,       # 趋势：均线与动量
}

DIM_LABEL = {
    "valuation": "估值",
    "quality": "质量",
    "position": "位置",
    "trend": "趋势",
}

# 分档阈值（用户可调）
DEFAULT_THRESHOLD = 70.0

# 参与评分所需的最少维度数。
# ⚠️ 这个门槛**只在用户启用的维度本身就有 2 个以上时才生效** —— 否则会出现：
# 用户故意只勾「趋势」一个维度（完全合理的用法），却因为 available(1) < MIN_DIMS(2)
# 导致所有股票的总分都是 None，页面上看起来就是「功能坏了」。
# 语义区分：
#   · 用户**故意**只启用 1 维 → 尊重他的选择，用这 1 维算分；
#   · 用户启用了 4 维但只有 1 维有数据 → 数据不足，不给分（避免用单一维度瞎猜）。
MIN_DIMS = 2


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _ramp(v: float, good: float, bad: float) -> float:
    """线性斜坡：v=good → 100 分，v=bad → 0 分，中间线性。good/bad 谁大谁小都行。"""
    if good == bad:
        return 50.0
    t = (v - bad) / (good - bad)
    return _clamp(t * 100)


def score_valuation(r: dict[str, Any]) -> tuple[float | None, str]:
    """估值维度：PE 分位（主）+ PB + 股息率（辅）。

    以**同行业 PE 分位**为主而不是绝对 PE：银行 PE 14 与软件 PE 40 都可能是合理的，
    拿绝对 PE 打分会把整个金融板块捧成「最便宜」—— 那是行业属性，不是机会。
    （分位由 rankings._add_pe_percentile 在对全集算好后注入。）
    """
    parts: list[tuple[float, float]] = []   # (分数, 权重)
    reasons: list[str] = []

    pct = r.get("pe_pct")
    pe = r.get("pe_ttm")
    if isinstance(pct, (int, float)) and isinstance(pe, (int, float)):
        s = _clamp(100 - float(pct))        # 分位 0（行业最便宜）→ 100 分
        parts.append((s, 0.6))
        reasons.append(f"PE {pe:.1f}，同行业第 {pct:.0f} 分位")
    elif isinstance(pe, (int, float)):
        # 没有行业分位时退化为绝对 PE 的粗略映射（40 倍 → 0 分）
        parts.append((_ramp(float(pe), 10, 40), 0.6))
        reasons.append(f"PE {pe:.1f}（无行业分位，按绝对值粗评）")
    elif r.get("pe_state") == "loss":
        return 0.0, "亏损（PE 无意义，估值维度按 0 分计）"

    pb = r.get("pb")
    if isinstance(pb, (int, float)) and pb > 0:
        parts.append((_ramp(float(pb), 1.0, 8.0), 0.25))
        reasons.append(f"PB {pb:.2f}")

    dy = r.get("div_yield")
    if isinstance(dy, (int, float)):
        # 股息率 0% → 0 分，5% → 满分。注意「股息陷阱」在上限处不再加分（> 8% 不加权）
        parts.append((_clamp(float(dy) / 5 * 100), 0.15))
        reasons.append(f"股息率 {dy:.2f}%")

    if not parts:
        return None, "无估值数据"
    total_w = sum(w for _, w in parts)
    score = sum(s * w for s, w in parts) / total_w
    return round(_clamp(score), 1), "；".join(reasons)


def score_quality(r: dict[str, Any]) -> tuple[float | None, str]:
    """质量维度：ROE（主）+ 盈利状态。

    映射：8% → 0 分，30% → 满分。

    ⚠️ **不要在 30% 之上继续加分，而是封顶并标注。** 实测 S&P 500 的
    ROE（= PB ÷ PE 推算）中位数是 17%，但 LVS 287%、MA 284%、AAPL 118% ——
    这些**不是**数据错误：大额回购会让净资产趋近 0，分母塌缩把 ROE 推成天文数字
    （Apple 就是典型）。把它当作「极优质」会系统性高估一批靠回购撑 ROE 的公司。
    所以 30% 以上一律 100 分封顶，并在理由里标出「回购推高」的可能是。
    """
    roe = r.get("roe")
    if not isinstance(roe, (int, float)):
        if r.get("pe_state") == "loss":
            return 0.0, "亏损，ROE 无意义"
        return None, "无 ROE 数据（需 PB 与 PE 同时可得）"

    score = _ramp(float(roe), 30.0, 8.0)
    if roe >= 30:
        return 100.0, f"ROE {roe:.0f}%（偏高，可能由回购使净资产变小推高）"
    reasons = [f"ROE {roe:.1f}%"]
    # 亏损标的即使 ROE 算得出也压一档（避免一次性损益制造的假高质量）
    if r.get("pe_state") == "loss":
        score *= 0.4
        reasons.append("但 EPS 为负")
    return round(_clamp(score), 1), "；".join(reasons)


def score_position(r: dict[str, Any]) -> tuple[float | None, str]:
    """位置维度：距 52 周高的回撤深度。

    这里**故意做成中性偏好「回撤更深」**（即越跌越加分），因为选股场景问的是
    「哪里可能有便宜货」。但跌幅大也可能是基本面变坏 —— 所以它权重只有 20%，
    且必须在提示文案里说明：位置低 ≠ 值得买。
    """
    fh = r.get("pct_from_high")
    if not isinstance(fh, (int, float)):
        return None, "无 52 周高低数据"
    # 0%（在最高点）→ 40 分；-25% → 约 80 分；-50% 及以下 → 100 分
    score = _clamp(40 + abs(float(fh)) * 1.6)
    if fh > -5:
        return round(score, 1), f"接近 52 周高点（{fh:.1f}%），位置偏高"
    return round(score, 1), f"距 52 周高 {fh:.1f}%"


def score_trend(r: dict[str, Any]) -> tuple[float | None, str]:
    """趋势维度：均线位置（主）+ 中期动量 + 相对基准超额，波动率作为扣分项。

    用 200 日均线为核心：这是最经典的多空分界。站上 MA200 视为中期趋势向上。
    """
    rel = r.get("ma200_rel")
    ma60 = r.get("ma60_rel")
    if not isinstance(rel, (int, float)):
        return None, "无均线数据（需 1 年日线）"

    # MA200 偏离：-20%（深度空头）→ 20 分，+20%（强势）→ 100 分
    score = _ramp(float(rel), 20.0, -20.0)
    reasons = [f"现价相对 MA200 {rel:+.1f}%"]
    if isinstance(ma60, (int, float)):
        score = score * 0.7 + _ramp(float(ma60), 15.0, -15.0) * 0.3

    r6 = r.get("r6m")
    if isinstance(r6, (int, float)):
        score = score * 0.8 + _clamp(50 + float(r6) * 0.8) * 0.2
        reasons.append(f"近 6 月 {r6:+.1f}%")

    # 波动率惩罚：年化 > 60% 每超 10% 扣 6 分（高波动标的即使趋势好也不该满仓）
    vol = r.get("vol_ann")
    if isinstance(vol, (int, float)) and float(vol) > 60:
        penalty = (float(vol) - 60) / 10 * 6
        score -= penalty
        reasons.append(f"年化波动 {vol:.0f}%，扣 {penalty:.0f} 分")

    return round(_clamp(score), 1), "；".join(reasons)


_DIM_FUNCS = {
    "valuation": score_valuation,
    "quality": score_quality,
    "position": score_position,
    "trend": score_trend,
}


def score_row(row: dict[str, Any], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """给一行算总分。返回 {score, band, dims, parts, coverage, low_confidence}。

    `coverage` = 有数据的维度数 / 启用的维度数。
    缺数据的维度**权重重新归一**（而不是当 0 分），并标记 low_confidence。
    """
    w = dict(weights or DEFAULT_WEIGHTS)
    dims: dict[str, float | None] = {}
    parts: dict[str, str] = {}
    weighted = 0.0
    used_w = 0.0
    enabled = 0

    for key, fn in _DIM_FUNCS.items():
        wt = float(w.get(key, 0.0) or 0.0)
        if wt <= 0:
            dims[key] = None
            parts[key] = "已关闭"
            continue
        enabled += 1
        try:
            val, why = fn(row)
        except Exception:  # noqa: BLE001
            val, why = None, "计算失败"
        dims[key] = val
        parts[key] = why
        if val is not None and wt > 0:
            weighted += val * wt
            used_w += wt

    available = sum(1 for k in _DIM_FUNCS if dims.get(k) is not None)
    if used_w <= 0 or enabled == 0 or available == 0:
        return {
            "score": None, "band": "na", "dims": dims, "parts": parts,
            "coverage": round(available / enabled, 2) if enabled else 0.0,
            "low_confidence": True,
        }
    # 启用维度足够多（≥2）却只有 1 维有数据 → 数据不足，不给分（见 MIN_DIMS 注释）
    if enabled >= MIN_DIMS and available < MIN_DIMS:
        return {
            "score": None, "band": "na", "dims": dims, "parts": parts,
            "coverage": round(available / enabled, 2),
            "low_confidence": True,
        }

    total = round(weighted / used_w, 1)
    return {
        "score": total,
        "band": "buy" if total >= DEFAULT_THRESHOLD else ("mid" if total >= 50 else "low"),
        "dims": dims,
        "parts": parts,
        "coverage": round(available / enabled, 2),
        "low_confidence": available < enabled,   # 有维度缺数据 → 分数只是参考
    }


def band_of(score: float | None, threshold: float = DEFAULT_THRESHOLD) -> str:
    """按用户当前阈值分档。前端用阈值滑杆时会调它。"""
    if score is None:
        return "na"
    if score >= threshold:
        return "buy"
    return "mid" if score >= threshold - 20 else "low"


def normalize_weights(raw: dict[str, Any] | None) -> dict[str, float]:
    """把外部传入的权重（可能含未知键、负数、全 0）规整成合法权重。

    全 0 时回落默认值 —— 否则所有股票都会因为没有可用维度而变成 na，
    页面看起来像「功能坏了」，但其实是参数问题。
    """
    if not raw:
        return dict(DEFAULT_WEIGHTS)
    out: dict[str, float] = {}
    for k in DEFAULT_WEIGHTS:
        try:
            v = float(raw.get(k, 0.0) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        out[k] = max(0.0, v)
    if sum(out.values()) <= 0:
        return dict(DEFAULT_WEIGHTS)
    return out
