"""EngineTask 的运行时 mixin（FILE_SIZE_DEBT Batch F-4 从 live.py 拆出）。

主循环 / 启停 / 运行统计 / run 行状态回写。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from .. import state as appstate
from .live_types import EngineTick


class _LiveRuntimeMixin:
    """运行时：双层节奏主循环与生命周期管理。"""

    async def run_once(self, dry_run: bool = False) -> EngineTick:
        """完整跑一轮（重算信号 + 执行）。用于「立即执行一次」与试运行。"""
        await self._refresh_signals()
        return await self._execute(dry_run=dry_run)

    async def _loop(self) -> None:
        """执行主循环。

        与旧实现的三个关键差别：
          1. **绝对截止点**：用 `loop.time()` 记录下次信号/下次执行的绝对时刻，
             而不是「执行完再 sleep(interval)」。后者会把每轮执行耗时累加进周期，
             1s 配置实际跑成 1.5s+；前者不会累积漂移。
          2. **事件驱动**：`exec_mode=event` 时等待「新行情推送」或「兜底定时器」，
             先到者先唤醒。有新 tick 就立刻评估，没有就按 exec_interval 兜底重评
             （用于止损检查、护栏倒计时、账户变化等非行情触发的情形）。
          3. **信号层与执行层分开计时**：重活（拉历史+跑策略）只在信号周期内跑一次。
        """
        self.running = True
        self._attach_hub()
        loop = asyncio.get_running_loop()
        self._wake_loop = loop
        if self._wake_event is None:
            self._wake_event = asyncio.Event()
        self._next_signal_at = loop.time()          # 启动即先算一次信号
        appstate.log(
            "engine_start", "INFO",
            f"引擎启动 #{self.engine_run_id} 策略={self.strategy_name} 模式={self.mode}"
            f" · 执行={self.exec_mode} 执行周期={self.exec_interval_sec:g}s"
            f" 信号周期={self.interval_sec:g}s",
        )
        try:
            while self.running:
                try:
                    now = loop.time()
                    # ---- 信号层 ----
                    if now >= self._next_signal_at:
                        await self._refresh_signals()
                        # 截止点基于「本轮信号完成时刻」推进，避免信号耗时把节奏拖长
                        self._next_signal_at = loop.time() + self.interval_sec

                    # ---- 执行层 ----
                    tick = await self._execute()
                    self._update_run_row("RUNNING", msg="")
                    if tick.errors and "熔断" in tick.errors[0]:
                        continue

                except asyncio.CancelledError:
                    break
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self._update_run_row("ERROR", msg=self.last_error)
                    appstate.log("engine_error", "CRITICAL", f"引擎异常: {self.last_error}")

                # ---- 等待：新行情 or 下次信号 or 执行兜底 ----
                now = loop.time()
                deadline = min(self._next_signal_at, now + self.exec_interval_sec)
                timeout = max(0.0, deadline - loop.time())
                if self.exec_mode != "event":
                    await asyncio.sleep(timeout)
                    self.timer_wakeups += 1
                    continue
                ev = self._wake_event
                if ev is None:
                    await asyncio.sleep(timeout)
                    continue
                ev.clear()
                # 清掉订阅积压，避免「有推送但事件已被消费」造成的空转
                try:
                    if self._sub is not None:
                        self._sub.discard()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await asyncio.wait_for(ev.wait(), timeout=timeout)
                    self.tick_wakeups += 1
                except asyncio.TimeoutError:
                    self.timer_wakeups += 1
        finally:
            self._detach_hub()
            self.running = False
            # P1-4：停止前撤销交易所侧保护性委托，避免残留单在无持仓时反向开仓。
            # shield 保证撤单不被取消信号打断；失败绝不影响停止流程。
            try:
                from starlette.concurrency import run_in_threadpool

                await asyncio.shield(run_in_threadpool(self._cancel_all_protective))
            except BaseException:  # noqa: BLE001 —— 含 CancelledError：停止流程不得被阻断
                pass
            self._update_run_row("STOPPED", msg="已停止")
            appstate.log("engine_stop", "INFO", f"引擎停止 #{self.engine_run_id}")

    def runtime_stats(self) -> dict[str, Any]:
        """运行时可观测性（前端状态面板 / 延迟面板用）。"""
        xs = sorted(self.exec_loop_ms)
        p50 = xs[len(xs) // 2] if xs else 0.0
        p95 = xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else 0.0
        hub_mode = "off"
        if self._hub is not None and self.symbols:
            modes = {self._hub.mode_of(s) for s in self.symbols}
            hub_mode = "stream" if modes == {"stream"} else ("snapshot" if "snapshot" in modes else "mixed")
        return {
            "run_id": self.engine_run_id,
            "strategy": self.strategy_name,
            "mode": self.mode,
            "symbols": list(self.symbols),
            "exec_mode": self.exec_mode,
            "exec_interval_sec": self.exec_interval_sec,
            "signal_interval_sec": self.interval_sec,
            "signal_age_sec": None if self._signal_age_sec() == float("inf")
                              else round(self._signal_age_sec(), 1),
            "signal_duration_ms": round(self._signal_duration_ms, 1),
            "signal_error": self.last_signal_error,
            "exec_count": self.exec_count,
            "tick_wakeups": self.tick_wakeups,
            "timer_wakeups": self.timer_wakeups,
            "exec_ms": {"p50": round(p50, 2), "p95": round(p95, 2),
                        "max": round(max(xs), 2) if xs else 0.0},
            "quote_source": self.last_quotes_source,
            "market_data": hub_mode,
            "targets": dict(self.last_targets),
        }

    def _update_run_row(self, status: str, msg: str = "") -> None:
        from ..database import session_scope
        from ..models import EngineRun

        try:
            with session_scope() as s:
                row = s.get(EngineRun, self.engine_run_id)
                if row:
                    row.status = status
                    row.tick_count = self.tick_count
                    row.last_tick = dt.datetime.now(dt.timezone.utc)
                    if msg:
                        row.message = msg
                    if status in ("STOPPED", "ERROR"):
                        row.stopped_at = dt.datetime.now(dt.timezone.utc)
        except Exception:  # noqa: BLE001
            pass

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        # P1-4：**先**撤保护性委托（此刻任务尚未取消，await 可正常完成），再停循环。
        # 顺序很关键：若先 cancel，_loop 的 finally 里再 await 会立刻抛 CancelledError，
        # 撤单就做不成了 —— 而残留的 GTC 止损单在无持仓时会反向开仓。
        try:
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(self._cancel_all_protective)
        except Exception:  # noqa: BLE001
            pass
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
