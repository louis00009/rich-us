"""MarketDataHub 的后台轮询 mixin（FILE_SIZE_DEBT Batch E-3 从 stream.py 拆出）。

`qd-mdhub` 线程每 `poll_interval` 秒跑一次 `_cycle`：
  · 为还没建立流式的标的申请推送订阅
  · 为流式失联的标的做快照兜底
  · 为纯快照标的定期刷新

⚠️ mixin 只提供方法：`_symbols` / `stats` / `stale_after` / `poll_interval` /
   `max_snapshot_batch` 等属性一律由 `MarketDataHub.__init__` 创建。
"""
from __future__ import annotations

import time

from . import latency as _lat
from .stream_types import (
    MODE_OFFLINE,
    MODE_SNAPSHOT,
    MODE_STREAM,
    _DOWNGRADE_AFTER_STALE,
)


class _PollMixin:
    """后台轮询：订阅申请 → 快照兜底 → 分批刷新。"""

    # ================================================================
    # 后台轮询线程
    # ================================================================
    def _poller(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                self._cycle()
            except Exception as exc:  # noqa: BLE001
                self.stats.cycles_failed += 1
                self.stats.last_error = f"轮询异常：{type(exc).__name__}: {exc}"
            self.stats.cycles += 1
            self.stats.poll_ms.append((time.perf_counter() - t0) * 1000)
            _lat.get_latency().record(_lat.HUB_POLL, (time.perf_counter() - t0) * 1000)
            self._wake.wait(self.poll_interval)
            self._wake.clear()

    def _cycle(self) -> None:
        syms = self.tracked_symbols()
        if not syms:
            return

        # 1) 为还没建立流式的标的申请推送订阅
        want = [s for s in syms if self._symbols[s].mode != MODE_STREAM]
        if want:
            got = self._try_stream(want)
            for sym in got:
                st = self._symbols.get(sym)
                if st is not None and st.mode != MODE_STREAM:
                    st.mode = MODE_STREAM
                    st.error = ""

        # 2) 收集需要快照刷新/兜底的标的
        stale_ms = self.stale_after * 1000
        need = []
        for sym in syms:
            st = self._symbols.get(sym)
            if st is None:
                continue
            if st.mode == MODE_STREAM and st.age_ms() <= stale_ms:
                continue
            if st.tick is not None and st.mode != MODE_OFFLINE and st.age_ms() <= self.poll_interval * 1000 * 0.4:
                continue      # 刚取过，别浪费 IB 配额
            need.append(sym)
        if not need:
            return

        # 3) 分批取快照（避免一次几十个标的把 IB 打满）
        for i in range(0, len(need), self.max_snapshot_batch):
            chunk = need[i:i + self.max_snapshot_batch]
            for t in self._fetch_now(chunk):
                st = self._symbols.get(t.symbol)
                if st is None:
                    continue
                if st.mode == MODE_STREAM:
                    st.snapshot_fallbacks += 1
                    if st.snapshot_fallbacks >= _DOWNGRADE_AFTER_STALE:
                        st.mode = MODE_SNAPSHOT
                        st.error = "流式行情长时间无推送，已降级为快照轮询"
                self.push(t)

    def _try_stream(self, symbols: list[str]) -> set[str]:
        """向券商申请流式订阅，返回真正建立成功的标的集合。"""
        broker, _prov = self._resolve_broker()
        if broker is None:
            return set()
        if not getattr(broker, "supports_streaming", False):
            return set()
        if not getattr(broker, "connected", False):
            return set()
        self.stats.subscribe_calls += 1
        try:
            ok = bool(broker.subscribe(list(symbols)))
        except Exception as exc:  # noqa: BLE001
            self.stats.broker_errors += 1
            self.stats.last_error = f"流式订阅失败：{type(exc).__name__}: {exc}"
            return set()
        if not ok:
            return set()
        self.stats.subscribe_ok += 1
        try:
            got = {str(s).upper() for s in (broker.streamed_symbols() or [])}
        except Exception:  # noqa: BLE001
            got = set()
        return got & {str(s).upper() for s in symbols}
