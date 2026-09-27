"""
止损 / 止盈策略库
==================
共 9 种止损机制，可组合使用（移动止损 + 保本 + 时间止损 + R 倍止盈）。

设计要点：
  · 以「每笔交易」为单位跟踪状态（入场价、方向、最高/最低浮动价、持有 bar 数）。
  · ATR 口径统一使用「上一根 bar 的 ATR」，避免用当根信息作弊。
  · 回测与实盘共用同一套 StopTracker，保证「回测即实盘」的一致性。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# 支持的止损类型
STOP_TYPES = [
    "none",
    "fixed_pct",      # 固定百分比止损
    "pct_trailing",   # 百分比移动止损
    "atr_fixed",      # 固定 ATR 倍数止损
    "atr_trailing",   # ATR 移动止损（吊灯）
    "chandelier",     # 吊灯止损（最高价 - N*ATR，取更宽者）
    "breakeven",      # 保本止损（浮盈达 R 后移至成本）
    "time_stop",      # 时间止损
    "volatility",     # 波动率自适应（ATR 变化放大止损）
]


@dataclass
class StopConfig:
    stop_type: str = "none"
    stop_value: float = 3.0          # ATR 倍数 / 百分比数值
    atr_period: int = 14
    take_profit_r: float = 0.0       # R 倍止盈，0 = 关闭
    time_stop_bars: int = 0          # 0 = 关闭
    breakeven_at_r: float = 0.0      # 浮盈达到 N 倍 R 后把止损移到成本价，0 = 关闭
    trail_start_r: float = 0.0       # 浮盈达到 N 倍 R 后才启动移动，0 = 立即
    min_stop_pct: float = 0.0        # 止损距离下限（防止 ATR 过小时止损过紧）
    max_stop_pct: float = 0.25       # 止损距离上限（防止止损过宽）

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict | None) -> "StopConfig":
        if not d:
            return cls()
        allowed = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**allowed)


@dataclass
class StopState:
    """单笔持仓的止损跟踪状态。"""
    active: bool = False
    side: int = 0                    # +1 多 / -1 空
    entry_price: float = 0.0
    entry_bar: int = 0
    initial_stop: float = 0.0
    r_distance: float = 0.0          # 1R 的价格距离
    extreme: float = 0.0             # 持仓期间最高价（多）/ 最低价（空）
    stop_price: float = 0.0
    breakeven_done: bool = False
    trailing_started: bool = False

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


class StopTracker:
    """逐 bar 更新的止损/止盈状态机。"""

    def __init__(self, cfg: StopConfig, symbol: str = "") -> None:
        self.cfg = cfg
        self.symbol = symbol
        self.s = StopState()

    # ------------------------------------------------------------------
    def open(self, side: int, entry_price: float, bar_index: int, atr_value: float | None) -> None:
        cfg = self.cfg
        self.s = StopState(
            active=True,
            side=int(np.sign(side)) or 1,
            entry_price=float(entry_price),
            entry_bar=int(bar_index),
            extreme=float(entry_price),
        )
        d = self._initial_distance(atr_value)
        self.s.r_distance = d
        if cfg.stop_type in ("none", "time_stop"):
            # P0-3：`none` 的语义是「仅靠策略信号离场」（与 API meta 文案一致），
            # `time_stop` 只按持有时间离场 —— 两者都不应携带隐藏的价格止损。
            # 旧实现给 none 悄悄塞了 25%（max_stop_pct）、time_stop 塞了 3% 的初始止损，
            # 策略研发期所有"无止损"曲线都含隐藏止损，网格寻优结果整体失真。
            # r_distance 仍保留作为 R 倍止盈 / 保本触发的参照距离。
            self.s.initial_stop = 0.0
            self.s.stop_price = 0.0
        else:
            self.s.initial_stop = entry_price - self.s.side * d
            self.s.stop_price = self.s.initial_stop

    def _initial_distance(self, atr_value: float | None) -> float:
        cfg = self.cfg
        ep = max(abs(self.s.entry_price), 1e-9)
        if cfg.stop_type in ("atr_fixed", "atr_trailing", "chandelier", "volatility") and atr_value:
            d = float(atr_value) * float(cfg.stop_value)
        elif cfg.stop_type == "none":
            d = ep * float(cfg.max_stop_pct or 0.25)
        else:
            d = ep * float(cfg.stop_value or 5.0) / 100.0
        lo = ep * float(cfg.min_stop_pct)
        hi = ep * float(cfg.max_stop_pct)
        return float(np.clip(d, max(lo, ep * 0.002), max(hi, ep * 0.002)))

    # ------------------------------------------------------------------
    def update(
        self,
        high: float,
        low: float,
        close: float,
        atr_value: float | None,
        bar_index: int,
    ) -> tuple[bool, str, float]:
        """
        返回 (是否触发离场, 原因, 触发价格)。
        判定顺序：先看固定/初始止损，再看保本、移动止损、R 倍止盈、时间止损。
        """
        s = self.s
        if not s.active:
            return False, "", 0.0
        cfg = self.cfg
        side = s.side

        # 更新极值
        s.extreme = max(s.extreme, high) if side > 0 else min(s.extreme, low)
        float_r = (s.extreme - s.entry_price) * side / (s.r_distance + 1e-12)

        # --- 1. 初始止损（当根即可能触及，用 low/high 判定更贴近实盘）---
        # stop_price == 0 表示该 stop_type 不设价格止损（none / time_stop），绝不触发
        if s.stop_price > 0 and side > 0 and low <= s.stop_price:
            return True, self._stop_reason(), min(s.stop_price, high)
        if s.stop_price > 0 and side < 0 and high >= s.stop_price:
            return True, self._stop_reason(), max(s.stop_price, low)

        # --- 2. 保本止损 ---
        if not s.breakeven_done and cfg.breakeven_at_r > 0 and float_r >= cfg.breakeven_at_r:
            offset = s.entry_price * float(cfg.min_stop_pct)
            s.stop_price = s.entry_price + side * offset      # 略高于成本，覆盖手续费
            s.breakeven_done = True

        # --- 3. 移动止损 ---
        if cfg.stop_type in ("pct_trailing", "atr_trailing", "chandelier", "volatility"):
            if cfg.trail_start_r <= 0 or float_r >= cfg.trail_start_r:
                s.trailing_started = True
                pct = float(cfg.stop_value) / 100.0
                if cfg.stop_type == "pct_trailing":
                    new_stop = s.extreme * (1 - pct) if side > 0 else s.extreme * (1 + pct)
                else:
                    # P1-3：ATR 不可用时绝不能以 0 参与计算。
                    # 旧实现 av=0 → new_stop = extreme（多单即持仓期最高价），
                    # 下一根 bar 的 low 必然 ≤ 该价 → 立即误触发「ATR移动止损」。
                    # 实盘 live.py:_check_stops 在 _atr_for 返回 0 时正是传 None，
                    # 而 None 在此被转成 0.0 —— 两个文件合起来构成该缺陷。
                    raw = float(atr_value) if atr_value else 0.0
                    av = raw if np.isfinite(raw) else 0.0
                    base_mult = max(float(cfg.stop_value), 1e-6)
                    if cfg.stop_type == "chandelier":
                        # 吊灯：ATR 缺失时用 1R 距离兜底（原有语义，不受本次修复影响）
                        av = max(av, s.r_distance / base_mult)
                    if av <= 0:
                        # 拿不到有效 ATR → 保持现有止损不动，等下一根有效 ATR，
                        # 而不是把止损推到极值价上立即平仓。
                        new_stop = None
                    else:
                        mult = base_mult
                        if cfg.stop_type == "volatility":
                            # 波动率自适应：ATR 放大 → 止损同步放宽；ATR 收缩 → 收紧。
                            # P2：旧实现用 abs(log(ratio))，ATR 收缩时同样放宽 —— 与注释
                            # 语义相反（收缩本应更快收紧保护利润）。改用有符号的 √ratio。
                            ratio = (av + 1e-9) / (s.r_distance / base_mult + 1e-9)
                            mult = base_mult * float(np.sqrt(float(np.clip(ratio, 0.5, 2.0))))
                        new_stop = s.extreme - side * av * mult
                # 移动止损只朝有利方向推进
                if new_stop is not None:
                    s.stop_price = max(s.stop_price, new_stop) if side > 0 else min(s.stop_price, new_stop)

        # --- 4. R 倍止盈 ---
        if cfg.take_profit_r > 0:
            target = s.entry_price + side * s.r_distance * cfg.take_profit_r
            if (side > 0 and high >= target) or (side < 0 and low <= target):
                return True, f"止盈 {cfg.take_profit_r:.2f}R", target

        # --- 5. 时间止损 ---
        if cfg.time_stop_bars > 0 and (bar_index - s.entry_bar) >= cfg.time_stop_bars:
            return True, f"时间止损 {cfg.time_stop_bars}bar", close

        return False, "", 0.0

    def _stop_reason(self) -> str:
        return {
            "fixed_pct": "固定止损",
            "pct_trailing": "移动止损",
            "atr_fixed": "ATR止损",
            "atr_trailing": "ATR移动止损",
            "chandelier": "吊灯止损",
            "volatility": "波动率止损",
            "breakeven": "保本止损",
            "time_stop": "时间止损",
        }.get(self.cfg.stop_type, "止损")

    # ------------------------------------------------------------------
    def current_stop(self) -> float:
        return float(self.s.stop_price) if self.s.active else 0.0

    def unrealized_r(self, close: float) -> float:
        if not self.s.active:
            return 0.0
        return (close - self.s.entry_price) * self.s.side / (self.s.r_distance + 1e-12)


def stop_distance_pct(cfg: StopConfig, price: float, atr_value: float | None) -> float:
    """预估止损距离（占价格百分比），用于仓位计算。"""
    if cfg.stop_type in ("atr_fixed", "atr_trailing", "chandelier", "volatility") and atr_value:
        d = float(atr_value) * float(cfg.stop_value)
    elif cfg.stop_type == "none":
        d = price * 0.10
    else:
        d = price * float(cfg.stop_value or 5.0) / 100.0
    d = float(np.clip(d, max(price * cfg.min_stop_pct, price * 0.002), price * cfg.max_stop_pct))
    return d / max(price, 1e-9)
