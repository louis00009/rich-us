"""intel_digest 评分纯函数区（FILE_SIZE_DEBT 新债治理从 intel_digest.py 拆出）。

score_event 及其权重常量/辅助函数 —— 全部纯函数，无 I/O，供 correct 节单测与调参。
intel_digest.py 对本模块全部符号做 re-export（`dig.score_event` 等旧路径不变）。
"""
from __future__ import annotations

import datetime as dt
from typing import Any


# ------------------------------------------------------------------
# 评分权重（集中定义，便于调参与测试）
# ------------------------------------------------------------------
# 事件类别权重：改变中期基本面的类别更值得看
CATEGORY_WEIGHT: dict[str, float] = {
    "earnings": 1.25,       # 财报/业绩指引
    "partnership": 1.20,    # 重大合同/合作（前瞻可见性）
    "regulatory": 1.15,     # 监管/政策（可一票否决）
    "product_launch": 1.10,
    "model_release": 1.10,
    "personnel": 0.85,      # 人事多为噪音，但 CEO/首席科学家级别另说
    "macro": 0.90,
    "other": 0.80,
}

# 前瞻管道阶段权重：已敲定 > 在谈 > 传闻
STAGE_WEIGHT: dict[str, float] = {
    "confirmed": 1.25,
    "negotiating": 1.00,
    "rumor": 0.65,
    "": 1.00,
}

# 来源权重：一手/官方 > 聚合器（缺失不惩罚）
SOURCE_WEIGHT_HINT: list[tuple[str, float]] = [
    ("sec", 1.15), ("gov", 1.15), ("fda", 1.15), ("faa", 1.15),
    ("reuters", 1.10), ("bloomberg", 1.10), ("wsj", 1.10),
    ("cnbc", 1.05), ("ft.com", 1.05), ("company", 1.10), ("ir.", 1.10),
]

# 重要度分档阈值（用于前端徽章与「重点」判定）
# 与下面的修正系数区间配套设计，保证分档与影响度**严格对齐**：
#   新鲜 5★ ∈ [80.9, 96.8] → 必是 critical；新鲜 4★ ∈ [64.8, 77.4] → 必是 high；
#   新鲜 3★ ∈ [48.6, 58.1] → 必是 medium。不会出现「4★ 压过 5★」的错位。
TIER_CRITICAL = 79.0   # 必读·重大
TIER_HIGH = 60.0       # 必读·重要
TIER_MEDIUM = 40.0     # 可看

# 基准分：**不能**让 5★ 一上来就顶到 100，否则 4★ 与 5★ 会因封顶而无法区分
# （第一版就踩了这个坑：全部饱和成 100.0，排序退化成无意义）。
# 取 88 → 17.6 / 35.2 / 52.8 / 70.4 / 88.0。
_BASE_MAX = 88.0
# 修正系数区间刻意收窄到 ±10%：影响度必须是**主导项**。
# 第一版用 [0.70, 1.25] 时，「4★ 财报+已敲定+路透+利空」(88.0) 会压过
# 「5★ 普通利好」(79.2) —— 那是排序错位，不是「综合考量」。
_MOD_MIN, _MOD_MAX = 0.92, 1.10

# 新鲜度曲线（2026-09-30 重写为**两档**）——用户原话：「新闻除了特别重大，时效性也很重要」。
#   · 特别重大（impact 5★）：缓衰减 1.0 → 0.80，窗口内的 5★ 始终 >= TIER_HIGH ——
#     足以改变中期基本面判断的消息，不因隔了一个周末就被埋掉（原 _FRESH_FLOOR 语义）；
#   · 其余（4★ 及以下）：陡衰减 1.0 → 0.88 → 0.66 → 0.45。
#     旧行为对全部影响度共用 0.80 平缓下限：2 天前的 4★ 仍有 ~65 分（high 档）、
#     2 天前的 5★ 83.9 分钉在榜首 ——「必读永远是旧闻」正是当时用户投诉的根因。
#     新曲线下 4★ 第 3 天只剩 ~31 分（low 档），必读位让给新信息；越新越靠前不变。
_FRESH_5STAR: tuple[float, ...] = (1.0, 0.9333, 0.8667, 0.80)
_FRESH_STD: tuple[float, ...] = (1.0, 0.88, 0.66, 0.45)
_FRESH_FLOOR = 0.80  # 兼容 re-export：= 5★ 缓衰减曲线的窗口末值

# 媒体评论/行情播报的重要度**硬上限**（严格低于 TIER_MEDIUM=40）。
# 为什么用封顶而不是乘个系数：系数会被 impact 这个主导项放大 ——
# 「3 AI Stocks With Revenue Growth」若被判 4★，乘 0.5 仍有 32 分，再叠上类别/来源加成
# 就能挤进「必读」。封顶才是硬约束：评论类**永远**进不了必读清单。
_COMMENTARY_CAP = 34.9



DIGEST_DAYS = 3        # 必读回看窗口（覆盖周末与非交易日）



def _parse_day(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def _freshness(age_days: int | None, impact: int = 5) -> float:
    """新鲜度（两档时效曲线）：特别重大（5★）缓衰减，其余陡衰减。

    设计取舍（都有真实教训）：
      · 5★ 不能衰减太狠 —— 第一版统一 1.0 → 0.5，两天前的 5★ 只剩 54 分被判
        「可看」，用户投诉「重点被周末冲淡」；5★ 窗口内必须始终 >= TIER_HIGH。
      · 其余档位也不能衰减太缓 —— 0.80 统一下限时 2 天前的 4★ 还有 ~65 分占着
        「重要」档，必读清单连日不变（2026-09-30 用户投诉「必读都是旧闻」）。
        4★ 及以下按日陡降：隔日 0.88、第 3 天 0.66、窗口末 0.45（掉出可看档）。
    新鲜度始终参与排序（越新越靠前）；impact 缺省按 5★（保守：日期未知时退路更宽）。
    """
    if age_days is None:
        return 0.85          # 日期未知：中性（约等于 1.5 天前），不臆造时间也不排除
    a = max(0, age_days)
    curve = _FRESH_5STAR if impact >= 5 else _FRESH_STD
    idx = a if a < len(curve) else len(curve) - 1
    return curve[idx]


def _source_weight(name: str) -> float:
    low = (name or "").lower()
    for hint, w in SOURCE_WEIGHT_HINT:
        if hint in low:
            return w
    return 1.0


def score_event(event: dict[str, Any], today: dt.date | None = None) -> dict[str, Any]:
    """确定性重要度评分（纯函数，无 I/O）。

    重要度 = 基准分(影响度) × 新鲜度 × 修正系数
      · 基准分 = impact/5 × 88（见 _BASE_MAX 注释：不能一上来就顶到 100）
      · 修正系数 = 1 + 类别/阶段/来源/方向 四项加成，夹取到 [0.70, 1.25]
        —— 加成是**有界的**，保证影响度始终是主导项：4★ 无论来源多好都压不过 5★。
      · 利空加成最高（下跌风险优先于机会）；中性轻微扣分。

    返回 {importance, tier, reasons, age_days}
    """
    today = today or dt.date.today()
    impact = event.get("impact")
    try:
        impact = max(1, min(5, int(impact)))
    except (TypeError, ValueError):
        impact = 3

    day = _parse_day(event.get("occurred_on"))
    age = None if day is None else max(0, (today - day).days)
    fresh = _freshness(age, impact)

    cat = str(event.get("category") or "other")
    cw = CATEGORY_WEIGHT.get(cat, 0.85)
    stage = str(event.get("stage") or "")
    sw = STAGE_WEIGHT.get(stage, 1.0)
    src = _source_weight(str(event.get("source_name") or ""))
    sentiment = str(event.get("sentiment") or "neutral")
    sent_coef = 1.08 if sentiment == "negative" else (1.0 if sentiment == "positive" else 0.92)

    mod = 1.0 + (cw - 1.0) * 0.5 + (sw - 1.0) * 0.5 + (src - 1.0) * 0.5 + (sent_coef - 1.0) * 0.5
    mod = max(_MOD_MIN, min(_MOD_MAX, mod))
    importance = round(max(0.0, min(100.0, (impact / 5.0) * _BASE_MAX * fresh * mod)), 1)

    # 媒体评论/行情播报/分析师调价不是公司自身事件 → 重要度封顶（见 _COMMENTARY_CAP）。
    # 依据来自 intel_classify.is_commentary，是**可核对**的规则命中，不是黑箱。
    commentary = bool(event.get("commentary"))
    if commentary:
        importance = min(importance, _COMMENTARY_CAP)

    if importance >= TIER_CRITICAL:
        tier = "critical"
    elif importance >= TIER_HIGH:
        tier = "high"
    elif importance >= TIER_MEDIUM:
        tier = "medium"
    else:
        tier = "low"

    # 理由：只写真正起作用的因素，避免套话
    reasons: list[str] = []
    if commentary:
        # 评论类的「低分理由」必须说清楚，否则用户会以为是评分出错。
        return {"importance": importance, "tier": tier, "age_days": age,
                "reasons": ["媒体评论/行情播报，非公司自身事件（不参与重点判定）"]}
    if impact >= 5:
        reasons.append("影响度 5★：足以改变中期基本面判断")
    elif impact == 4:
        reasons.append("影响度 4★：重大合同/指引调整级别")
    if impact < 5 and age is not None and age >= 1:
        # 时效衰减必须说出口：用户看到次新事件分数低，要知道是「时效」而非「评分出错」
        reasons.append(f"时效衰减：非特别重大事件，已隔 {age} 天")
    if age is not None and age <= 1:
        reasons.append("当日/隔日新信息")
    if sentiment == "negative":
        reasons.append("利空：下跌风险优先处理")
    if stage == "confirmed":
        reasons.append("已敲定事实（非传闻）")
    elif stage == "negotiating":
        reasons.append("官方口径在谈：尚未落地")
    elif stage == "rumor":
        reasons.append("仅为传闻：需等证实")
    if cw >= 1.20:
        reasons.append({"earnings": "财报/指引直接改盈利预期",
                        "partnership": "合同管道前瞻未来 3-6 个月经营"}.get(cat, "高信息量类别"))
    if src >= 1.10:
        reasons.append("一手/权威来源")

    return {"importance": importance, "tier": tier, "reasons": reasons[:4], "age_days": age}

