"""做空可行性校验数据与规则。

两个市场的规则完全不同，不能共用一套判断：

**港股**：只有港交所《可进行卖空的指定证券名单》内的标的才能做空，
且需要先借到券。名单由港交所定期更新（通常每季度）。

**美股**：原则上大部分流动性好的标的都可做空，但受两件事约束：
1. Reg SHO —— 标的若触发短线卖出规则（SSR，单日跌幅 ≥10%），
   当日及次日的卖出价必须**高于**当前最高买价（不能主动砸盘）。
2. 券源（locate）—— 做空需要券商能借到券，冷门标的可能借不到或借券费极高。

诚实原则
--------
港交所名单会变、借券费随供需波动。本表是**快照**，`is_shortable()` 会返回
`source`，`"default"` 表示未收录并采用保守拒绝策略（港股）/ 放行但告警（美股）。
真正的券源可用性必须由券商确认 —— 本模块只做**下单前的第一道粗筛**，
避免把明显违规的单子发到交易所。
"""
from __future__ import annotations

from dataclasses import dataclass

from .symbols import SymbolRef, parse

SHORTLIST_AS_OF = "2026-09"

# 港股可卖空名单（港交所《可进行卖空的指定证券名单》常见标的快照）
# 键为 IB symbol（去掉前导零）
HK_SHORTABLE: frozenset[str] = frozenset({
    # 蓝筹 / 恒指成分
    "1", "2", "3", "5", "6", "11", "12", "16", "17", "27", "66", "83",
    "101", "175", "267", "288", "291", "316", "322", "386", "388", "489",
    "522", "688", "700", "762", "823", "857", "868", "881", "883", "939",
    "941", "960", "968", "981", "992", "1038", "1044", "1088", "1093",
    "1099", "1109", "1113", "1157", "1177", "1211", "1288", "1299", "1339",
    "1398", "1772", "1810", "1876", "1919", "1928", "2007", "2015", "2020",
    "2269", "2313", "2318", "2331", "2333", "2359", "2382", "2388", "2600",
    "2628", "2688", "2883", "2899", "3328", "3690", "3958", "3988", "6030",
    "6098", "6618", "6690", "6862", "9618", "9633", "9666", "9866", "9868",
    "9888", "9987", "9988", "9999", "1024",
})

# 美股 SSR 触发时的价格限制提示
SSR_NOTE = "处于 Reg SHO 短线卖出规则：卖出价必须高于当前最高买价（不可主动砸盘）"


@dataclass(frozen=True)
class ShortCheck:
    symbol: str
    market: str
    allowed: bool
    reason: str
    source: str            # "list" | "default" | "regulatory"
    borrow_fee_bps: float | None = None   # 年化借券费参考（bps）
    margin_pct: float | None = None       # 保证金要求（占空头市值 %）
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "market": self.market, "allowed": self.allowed,
            "reason": self.reason, "source": self.source,
            "borrow_fee_bps": self.borrow_fee_bps, "margin_pct": self.margin_pct,
            "notes": list(self.notes),
        }


def is_shortable(symbol: str | SymbolRef) -> ShortCheck:
    ref = parse(symbol) if isinstance(symbol, str) else symbol

    if ref.is_index:
        return ShortCheck(
            ref.symbol, ref.market, False,
            "指数不可直接做空，请使用期货/期权等衍生品", "regulatory",
        )

    if ref.market == "HK":
        if ref.ib_symbol in HK_SHORTABLE:
            return ShortCheck(
                ref.symbol, "HK", True,
                "在港交所可卖空指定证券名单内", "list",
                borrow_fee_bps=None, margin_pct=None,
                notes=(
                    "港股做空前必须先借到券；借券费按年化计，冷门标的可达 10%+",
                    "港交所名单每季度更新，实盘前请以券商的可借券查询结果为准",
                    "港股不允许无券裸空（naked short）",
                ),
            )
        return ShortCheck(
            ref.symbol, "HK", False,
            "不在已收录的可卖空名单内（港股仅允许做空指定证券）", "default",
            notes=(
                "本表为快照，可能与港交所最新名单不一致",
                "请到港交所官网核对《可进行卖空的指定证券名单》后再决定",
            ),
        )

    # 美股
    return ShortCheck(
        ref.symbol, "US", True,
        "美股原则上可做空，但需券商确认券源（locate）", "regulatory",
        margin_pct=150.0,
        notes=(
            SSR_NOTE,
            "做空保证金通常为 150%（Reg T）；维持保证金不足会被强平",
            "借券费由券商按实时券源供需报价，冷门标的可能无券可借",
            "做空持仓会产生借券利息，持有成本需计入策略回测",
        ),
    )


def shortable_list(market: str = "HK") -> list[str]:
    if str(market).upper() != "HK":
        return []
    return sorted(HK_SHORTABLE, key=lambda x: (len(x), x))


def summary() -> dict:
    return {
        "as_of": SHORTLIST_AS_OF,
        "hk_count": len(HK_SHORTABLE),
        "hk_sample": shortable_list("HK")[:20],
        "us_rule": SSR_NOTE,
        "disclaimer": (
            "本名单为快照，仅用于下单前粗筛，不构成可借券保证。"
            "实盘请以券商的实时可借券查询为准。"
        ),
    }


__all__ = ["ShortCheck", "is_shortable", "shortable_list", "summary", "HK_SHORTABLE", "SHORTLIST_AS_OF"]
