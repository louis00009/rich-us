"""实时引擎的纯数据类型（FILE_SIZE_DEBT Batch F-4 从 live.py 拆出）。

EngineTick（单 tick 执行结果）与 BacktestSpecLite（build_strategy 轻量载体）
与 EngineTask 无行为耦合，独立成文件供 live.py 与各 mixin 引用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EngineTick:
    ts: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    target_weights: dict[str, float] = field(default_factory=dict)
    account_equity: float = 0.0
    # 执行元数据（延迟面板 / 前端状态展示用）
    signal_age_sec: float = 0.0        # 这份目标权重距今多久
    signal_recomputed: bool = False    # 本 tick 是否重算了信号
    exec_ms: float = 0.0                # 本轮执行耗时
    quote_source: str = ""             # hub-stream | hub-snapshot | broker | fallback
    phase: str = "exec"                # signal | exec


@dataclass
class BacktestSpecLite:
    """仅用于复用 build_strategy 的轻量载体。"""
    strategy_key: str
    symbols: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    rule: dict[str, Any] | None = None
    code: str = ""
