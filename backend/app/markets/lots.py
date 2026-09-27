"""手数（board lot）与最小价格变动（tick size）规则。

为什么必须单独一层
------------------
港股按「每手」交易，每手股数因标的而异（腾讯 100 股、汇丰 400 股、联通 2000 股）。
下单 150 股腾讯不是"买 1.5 手"，而是**无效订单**，会被港交所直接拒绝。
美股虽然 1 股起，但在价格 < $1 时受 sub-penny 规则约束，报价精度也不同。

诚实原则
--------
每手股数会随上市公司拆股/合股而变，本表是**已知快照**而非权威来源。
`lot_of()` 会返回 `source`，`"table"` 表示查到了，`"default"` 表示用了兜底值。
上层（订单预检、前端）必须把 `"default"` 情形显示给用户确认 ——
宁可让用户看到"每手股数按默认 100 计算，请核对"，也不要静默用错值下单。
"""
from __future__ import annotations

from dataclasses import dataclass

from .registry import HK
from .symbols import SymbolRef, parse

# ======================================================================
# 港股每手股数（键为去掉前导零的代码，与 IB symbol 一致）
# ======================================================================
HK_BOARD_LOT: dict[str, int] = {
    # --- 蓝筹 / 恒指成分 ---
    "1": 500, "2": 500, "3": 1000, "5": 400, "6": 500, "11": 100, "12": 1000,
    "16": 1000, "17": 1000, "27": 1000, "66": 500, "83": 200, "101": 1000,
    "175": 1000, "267": 1000, "288": 500, "291": 2000, "316": 100,
    "322": 2000, "386": 2000, "388": 100, "489": 2000, "522": 100,
    "688": 500, "700": 100, "762": 2000, "823": 100, "857": 2000,
    "868": 1000, "881": 500, "883": 1000, "939": 1000, "941": 500,
    "960": 500, "968": 2000, "981": 500, "992": 2000, "1038": 500,
    "1044": 1000, "1088": 500, "1093": 2000, "1099": 400, "1109": 500,
    "1113": 1000, "1157": 1000, "1177": 2000, "1211": 500, "1288": 1000,
    "1299": 200, "1339": 1000, "1398": 1000, "1772": 200, "1810": 200,
    "1876": 100, "1919": 500, "1928": 400, "2007": 1000, "2015": 100,
    "2020": 200, "2269": 500, "2313": 100, "2318": 500, "2331": 500,
    "2333": 500, "2359": 100, "2382": 1000, "2388": 500, "2600": 2000,
    "2628": 1000, "2688": 100, "2883": 1000, "2899": 2000, "3328": 1000,
    "3690": 100, "3958": 400, "3988": 1000, "6030": 500, "6098": 500,
    "6618": 100, "6690": 200, "6862": 1000, "9618": 50, "9633": 200,
    "9666": 100, "9866": 100, "9868": 100, "9888": 50, "9987": 50,
    "9988": 100, "9999": 100, "1024": 100,
}


# ======================================================================
@dataclass(frozen=True)
class LotRule:
    market: str
    lot: int
    source: str          # "table" | "default" | "integral"
    note: str = ""

    @property
    def is_guess(self) -> bool:
        return self.source == "default"


def lot_of(symbol: str | SymbolRef) -> LotRule:
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    if ref.market == "US":
        return LotRule("US", 1, "integral", "美股按 1 股下单；碎股需券商支持且仅限特定订单类型")
    key = ref.ib_symbol
    if key in HK_BOARD_LOT:
        return LotRule("HK", HK_BOARD_LOT[key], "table", "")
    return LotRule(
        "HK", HK.default_lot, "default",
        f"未收录 {ref.symbol} 的每手股数，按港股默认值 {HK.default_lot} 股计算，下单前请核对",
    )


def round_qty(symbol: str | SymbolRef, qty: float, *, side: str = "BUY",
              allow_odd_lot_sell: bool = True) -> tuple[float, int, str]:
    """把数量对齐到合法手数。

    返回 (对齐后数量, 每手股数, 说明)。
    - 买单 / 开仓：向下取整到整手（买多了会超预算，向下取整更安全）
    - 卖单：若持有碎股且 `allow_odd_lot_sell`，允许把碎股一次卖掉（港股碎股只能卖不能买）
      P2：旧实现该参数声明后从未使用 —— 卖 50 股腾讯（每手 100）会被取整成 0，
      小额持仓永远卖不掉。
    """
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    rule = lot_of(ref)
    lot = rule.lot
    q = float(qty)
    if q <= 0:
        return 0.0, lot, "数量必须为正"

    if ref.market == "US":
        whole = float(int(q))                      # 美股整股
        note = f"美股取整为 {whole:.0f} 股" if whole != q else ""
        return whole, 1, note

    if side.upper() == "SELL" and allow_odd_lot_sell:
        # 港交所允许卖出碎股（碎股只能卖不能买）→ 卖单保留不足一手的部分
        return q, lot, "卖出允许碎股" if q % lot else ""

    lots = int(q // lot)
    aligned = float(lots * lot)
    if aligned <= 0:
        return 0.0, lot, f"数量 {q:g} 不足 1 手（每手 {lot} 股）"
    note = f"按每手 {lot} 股取整：{q:g} → {aligned:g}"
    if rule.is_guess:
        note += "（每手股数为默认值，请核对）"
    return aligned, lot, note


def max_affordable_lots(symbol: str | SymbolRef, cash: float, price: float) -> tuple[int, str]:
    """给定现金能买多少手。返回 (手数, 说明)。"""
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    rule = lot_of(ref)
    if price <= 0:
        return 0, "价格无效"
    per_lot_cost = rule.lot * price
    n = int(cash // per_lot_cost)
    return max(0, n), f"每手 {rule.lot} 股 × {price:g} = {per_lot_cost:,.2f}"


# ======================================================================
# 最小价格变动
# ======================================================================
HK_SPREAD_TABLE: list[tuple[float, float]] = [
    (0.01, 0.001), (0.25, 0.005), (0.50, 0.010), (10.00, 0.020),
    (20.00, 0.050), (100.00, 0.100), (200.00, 0.200), (500.00, 0.500),
    (1000.00, 1.000), (2000.00, 2.000), (5000.00, 5.000),
]


def tick_size(symbol: str | SymbolRef, price: float) -> float:
    """最小价格变动。港交所按价格档位分档；美股 ≥$1 为 $0.01，<$1 为 $0.0001。"""
    ref = parse(symbol) if isinstance(symbol, str) else symbol
    if ref.market == "US":
        return 0.0001 if 0 < price < 1.0 else 0.01
    spread = HK_SPREAD_TABLE[-1][1]
    for lower, sp in HK_SPREAD_TABLE:
        if price < lower:
            break
        spread = sp
    return spread


def round_price(symbol: str | SymbolRef, price: float, *, side: str = "BUY") -> float:
    """把价格对齐到合法跳动。买单向下取整（不超价），卖单向上取整。"""
    t = tick_size(symbol, price)
    if t <= 0:
        return price
    n = price / t
    if side.upper() == "BUY":
        return round(int(n) * t, 10)
    import math

    return round(math.ceil(n - 1e-9) * t, 10)


def lot_table(symbols) -> list[dict]:
    """批量查询，供前端展示/自检使用。"""
    out = []
    for s in symbols:
        try:
            ref = parse(s)
        except Exception:  # noqa: BLE001
            continue
        rule = lot_of(ref)
        out.append({
            "symbol": ref.symbol, "market": ref.market,
            "lot": rule.lot, "source": rule.source, "note": rule.note,
        })
    return out


__all__ = [
    "LotRule", "lot_of", "round_qty", "max_affordable_lots",
    "tick_size", "round_price", "lot_table",
    "HK_BOARD_LOT", "HK_SPREAD_TABLE",
]
