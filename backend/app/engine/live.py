"""
实时交易引擎
=============
把「策略信号」变成「真实订单」的最后一公里，全程受风控护栏约束。

一个 tick 的流程：
    1. 拉取持仓与账户（含当日开盘权益、历史峰值权益，用于日亏/回撤熔断）
    2. 拉取行情，构造 SignalContext，跑策略得到最新目标权重
    3. 与当前持仓做差分，得到需要调仓的标的与目标名义金额
    4. 逐单通过 risk.guardrails.check_order —— 任一不通过则跳过并审计
    5. 通过则下单，记录 Order 与 Fill，并写入审计日志
    6. 为新建仓位登记 StopTracker（价格触及由 tick 内的止损检查负责平仓）

FILE_SIZE_DEBT Batch F-4：本文件只保留 EngineTask 的组装（__init__ + _broker）
与模块门面；方法体按执行阶段拆进 5 个 mixin（live_signal / live_risk /
live_exec / live_hub / live_runtime）。**实例属性初始化全部留在本文件
__init__** —— mixin 方法依赖这些属性，但绝不自行创建。
"""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from .. import state as appstate
from ..brokers import get_broker
from ..brokers.base import Broker
from ..markets import symbols as mksym
from ..risk.guardrails import RiskLimits
from ..risk.stops import StopConfig, StopTracker
from .live_exec import _LiveExecMixin
from .live_hub import _LiveHubMixin
from .live_risk import _LiveRiskMixin
from .live_runtime import _LiveRuntimeMixin
from .live_signal import _LiveSignalMixin
from .live_types import BacktestSpecLite, EngineTick  # noqa: F401  re-export 保持旧 import 路径

ACTIVE_ENGINES: dict[int, "EngineTask"] = {}


class EngineTask(_LiveSignalMixin, _LiveRiskMixin, _LiveExecMixin, _LiveHubMixin, _LiveRuntimeMixin):
    """单个策略的实时运行任务。"""

    def __init__(
        self,
        engine_run_id: int,
        strategy_id: int,
        strategy_name: str,
        spec_key: str,
        params: dict,
        rule: dict | None,
        code: str,
        symbols: list[str],
        mode: str,
        interval_sec: float,
        stop_cfg: StopConfig,
        limits: RiskLimits,
        sizing_method: str = "weight",
        risk_per_trade_pct: float = 1.0,
        max_position_pct: float = 20.0,
        gross_pct: float = 100.0,
        warmup_days: int = 400,
        place_protective: bool = True,
        exec_interval_sec: float = 1.0,
        exec_mode: str = "event",
        rebalance_deadband_pct: float = 0.5,
    ) -> None:
        self.engine_run_id = engine_run_id
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.spec_key = spec_key
        self.params = params
        self.rule = rule
        self.code = code
        # 符号规范化：`0700` / `700` / `0700.HK` 在引擎内部统一成 `0700.HK`，
        # 否则行情缓存、持仓匹配、手数规则、费用模型会各按各的写法去找，永远对不上。
        self.symbols = [mksym.normalize(s) for s in (symbols or []) if str(s or "").strip()]
        self.mode = mode
        # ---------- 双层节奏 ----------
        # 信号层：重算目标权重（拉历史 + 跑策略，重）。旧实现把它和执行绑死，
        # 于是「想快点下单」只能连历史数据一起重拉，根本快不了。
        self.interval_sec = max(0.05, float(interval_sec))
        # 执行层：读内存行情 + 风控 + 下单（轻，可亚秒级）
        self.exec_interval_sec = max(0.02, float(exec_interval_sec))
        # event：有推送就立刻执行；poll：固定节奏
        self.exec_mode = str(exec_mode or "event").lower()
        # 调仓死区（占权益百分比）：差额低于它就完全不动仓
        self.rebalance_deadband_pct = max(0.0, float(rebalance_deadband_pct))
        self.stop_cfg = stop_cfg
        self.limits = limits
        self.sizing_method = sizing_method
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        self.gross_pct = gross_pct
        self.warmup_days = warmup_days
        # 实盘时为每笔持仓挂交易所侧的保护性止损/止盈单（防止引擎掉线后无保护）
        self.place_protective = bool(place_protective)
        self.protective_orders: dict[str, dict[str, str]] = {}

        self.task: asyncio.Task | None = None
        self.running = False
        self.tick_count = 0
        self.last_tick: str | None = None
        self.last_error = ""
        self.trackers: dict[str, StopTracker] = {}
        self.last_targets: dict[str, float] = {}
        self.last_tick_detail: EngineTick | None = None
        self._peak_equity = 0.0
        self._atr_map: dict[str, float] = {}
        # 券商名称用于订单落库后的状态回写匹配（ibkr | simulated），
        # 不能用 mode 判断：IBKR 的纸面账户同样是 mode="paper"。
        self._broker_name = "simulated"

        # ---------- 事件驱动相关 ----------
        self._hub = None                      # 行情中枢
        self._sub = None                      # 中枢订阅者（拉取模式）
        self._wake_event: asyncio.Event | None = None
        self._wake_loop: asyncio.AbstractEventLoop | None = None
        self._next_signal_at = 0.0            # loop.time() 截止点，消除累积漂移
        self._signal_duration_ms = 0.0
        self._signal_symbols: list[str] = []
        self.last_signal_at: str | None = None
        self.last_signal_error = ""
        self.exec_count = 0
        self.tick_wakeups = 0                 # 因行情推送被唤醒的次数
        self.timer_wakeups = 0                # 因定时器被唤醒的次数
        self.exec_loop_ms: deque[float] = deque(maxlen=256)
        self.last_quotes_source = ""
        # P1-7：止损离场冷却（symbol -> epoch 秒）。
        # 旧实现平仓后立刻 reset tracker，若券商尚未回填新持仓，下一 tick 接管逻辑
        # 会重建同参数止损并可能再次触发 —— 隔 tick 重复下市价卖单。
        self._stop_exit_at: dict[str, float] = {}
        # P1-1：策略 bar 序号 —— 时间止损必须按 **bar** 计，不能按执行 tick 计。
        # 旧实现把 tick_count（每个执行周期 +1，exec_interval_sec 可低至 0.02s）
        # 当 bar_index 传给 StopTracker，于是「5 bar 时间止损」在实盘 = 0.1~5 秒平仓，
        # 而回测里同样的 5 = 5 个交易日 —— 回测结论完全无法外推。
        # 这里改为：只有出现新的策略 bar（末根时间戳变化）才 +1。
        self._bar_seq = 0
        self._last_bar_key: str | None = None

    # ------------------------------------------------------------------
    def _broker(self) -> Broker:
        broker, _ = get_broker(appstate.get_broker_settings())
        # 记录真实券商名：订单状态回写依赖它匹配（IBKR 纸面账户也是 mode=paper）
        self._broker_name = getattr(broker, "name", "simulated") or "simulated"
        return broker
