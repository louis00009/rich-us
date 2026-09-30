"""EngineTask 的行情中枢接入 mixin（FILE_SIZE_DEBT Batch F-4 从 live.py 拆出）。

只提供方法；实例属性（_hub/_sub/_wake_event/_wake_loop 等）由组装类
engine/live.py 的 `EngineTask.__init__` 初始化。
"""
from __future__ import annotations

import asyncio
from typing import Any

from .. import state as appstate


class _LiveHubMixin:
    """行情中枢接入：订阅 / 退订 / 推送唤醒。"""

    def _attach_hub(self) -> None:
        try:
            from .stream import get_hub

            hub = get_hub()
            self._hub = hub
            self._wake_loop = asyncio.get_running_loop()
            self._wake_event = asyncio.Event()
            # 拉取模式 + on_tick 回调：回调在发布线程执行，只做一个线程安全的唤醒，
            # 真正的行情读取仍在事件循环里从内存取。
            #
            # 注意：`subscribe_events` 内部已经会 `ensure()`（引用计数 +1），
            # 这里**不能**再单独调一次 `hub.ensure()` —— 那会让计数变成 2，
            # 而退订时只减 1，订阅就永久泄漏在进程里。
            self._sub = hub.subscribe_events(
                self.symbols, loop=None, on_tick=self._on_hub_tick, sid=f"engine-{self.engine_run_id}",
            )
            appstate.log(
                "engine_hub", "INFO",
                f"引擎 #{self.engine_run_id} 已接入行情中枢（{', '.join(self.symbols)}）· "
                f"执行模式={self.exec_mode} 执行周期={self.exec_interval_sec:g}s "
                f"信号周期={self.interval_sec:g}s",
            )
        except Exception as exc:  # noqa: BLE001
            self._hub = None
            self.last_error = f"接入行情中枢失败（将退回逐次请求行情）：{exc}"

    def _detach_hub(self) -> None:
        try:
            if self._hub is not None and self._sub is not None:
                self._hub.unsubscribe_events(self._sub.id, release=True)
        except Exception:  # noqa: BLE001
            pass
        self._sub = None
        self._hub = None
        self._wake_event = None
        self._wake_loop = None

    def _on_hub_tick(self, tick: Any) -> None:
        """中枢推送回调（运行在发布线程）。只做唤醒，绝不做业务逻辑。"""
        loop = self._wake_loop
        ev = self._wake_event
        if loop is None or ev is None:
            return
        try:
            loop.call_soon_threadsafe(ev.set)
        except RuntimeError:
            pass
