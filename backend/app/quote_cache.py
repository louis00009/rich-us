"""movers / rankings 共用的「全池行情缓存」机制。

两模块原本各有一份几乎逐字相同的实现（_load_disk / _save_disk /
_fetch_all_quotes / _accept_refresh / _bg_refresh / quote_cache_meta），
属于复制粘贴出来的重复代码（铁律 9 / FILE_SIZE_DEBT Batch D）。
本模块把它们收敛为一个可参数化的 `QuoteCache`：

- stale-while-revalidate：缓存过期也**立即返回旧数据**，后台线程去刷新，
  HTTP 请求永不等待网络；
- 覆盖率闸门：新数据 < 旧缓存 80% 时丢弃本次刷新（铁律 12 ——
  任何「抓全量→覆盖落盘」都必须有闸门，否则一次半残抓取会把好数据覆盖成垃圾）；
- 磁盘快照一律 `cacheio.atomic_write_json` 原子写（0 字节事故教训），
  读取先 `ensure_seed` 兜底（无对应种子文件时等价于直读）。

差异点由构造参数 / 调用参数注入：
- `parse_chunk`：rankings 基础字段；movers 额外带 bar_date 与量比 —— 各自实现；
- `period`：rankings 拉 5d，movers 拉 10d（量比需要前 9 根全天量）；
- `include_updated`：movers 的 meta 带 `updated`（前端「行情更新于」）。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

ParseChunkFn = Callable[[list[str], Any], dict[str, dict[str, Any]]]
FetchFn = Callable[[], dict[str, dict[str, Any]]]


# 刷新结果的最低覆盖率：新抓到的标的数不足旧缓存的这个比例时，视为「部分失败」，
# 保留旧缓存不覆盖。80% 是留出正常波动的余量（个别标的偶尔抓不到很正常），
# 又能挡住真正的塌方（实测 yfinance 超时那次只抓到 228/503 = 45%）。
MIN_REFRESH_RATIO = 0.8


def accept_refresh(fresh_count: int, old_count: int) -> bool:
    """本次刷新结果是否可接受（能不能覆盖旧缓存）。

    ⚠️⚠️ 覆盖率闸门（铁律 12）：判定逻辑一个字符都不能改。
    旧实现是 `if fresh: 落盘` —— 无条件覆盖：yfinance 部分超时
    （只抓到 228/503）时，会把好的 503 只快照**直接覆盖掉**，
    榜单从「共 503 只」静默变成「共 228 只」，不报任何错误。
    """
    if fresh_count <= 0:
        return False
    if old_count <= 0:
        return True
    return fresh_count >= old_count * MIN_REFRESH_RATIO


class QuoteCache:
    """全池行情：内存缓存 + 磁盘快照 + 后台单飞刷新（stale-while-revalidate）。"""

    def __init__(
        self,
        *,
        snapshot_path: Path,
        ttl: int,
        chunk: int = 100,
        workers: int = 4,
        thread_name: str = "quote-refresh",
        include_updated: bool = False,
    ) -> None:
        self.snapshot_path = Path(snapshot_path)
        self.ttl = ttl
        self.chunk = chunk
        self.workers = workers
        self.thread_name = thread_name
        self.include_updated = include_updated
        self._lock = threading.Lock()
        self._cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
        self._refreshing = False
        self._state: dict[str, Any] = {"last": 0.0, "ok": None}

    # ---------------- 磁盘快照 ----------------
    def load_disk(self) -> tuple[float, dict[str, dict[str, Any]]]:
        """磁盘快照恢复。缺失/损坏时先尝试出厂 seed —— 2026-09-28 的 0 字节事故
        （write_text 非原子写被重启打断）曾让每次重启都返回空 → 用户每次
        开页面都等 30s+ 全量抓取。"""
        from .cacheio import ensure_seed, load_json_snapshot

        ensure_seed(self.snapshot_path)
        data = load_json_snapshot(self.snapshot_path)
        if data and data.get("quotes"):
            try:
                return float(data.get("ts", 0.0)), dict(data["quotes"])
            except Exception:  # noqa: BLE001
                return 0.0, {}
        return 0.0, {}

    def save_disk(self, quotes_map: dict[str, dict[str, Any]]) -> None:
        from .cacheio import atomic_write_json

        atomic_write_json(self.snapshot_path, {"ts": time.time(), "quotes": quotes_map})

    # ---------------- 抓取 ----------------
    def fetch_all(
        self,
        syms: list[str],
        parse_chunk: ParseChunkFn,
        period: str = "5d",
    ) -> dict[str, dict[str, Any]]:
        """并发抓全部成分股行情（分块 yf.download + 线程池）。"""
        chunks = [syms[i: i + self.chunk] for i in range(0, len(syms), self.chunk)]

        def work(chunk: list[str]) -> dict[str, dict[str, Any]]:
            try:
                import yfinance as yf

                df = yf.download(
                    tickers=" ".join(chunk), period=period, interval="1d",
                    group_by="ticker", threads=False, progress=False, auto_adjust=False,
                )
                return parse_chunk(chunk, df)
            except Exception:  # noqa: BLE001
                return {}

        out: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = [ex.submit(work, c) for c in chunks]
            for f in as_completed(futs):
                out.update(f.result() or {})
        return out

    # ---------------- 刷新 ----------------
    def bg_refresh(self, fetch_fn: FetchFn) -> None:
        """后台刷新行情并落盘。同一时刻仅一路（_refreshing 旗标保证）。"""
        try:
            fresh = fetch_fn()
            _, old = self._cache
            if accept_refresh(len(fresh), len(old)):
                with self._lock:
                    self._cache = (time.time(), fresh)
                self.save_disk(fresh)
                self._state["ok"] = True
            else:
                self._state["ok"] = False
                self._state["error"] = (
                    f"本次只抓到 {len(fresh)} 只（旧缓存 {len(old)} 只），覆盖率过低，保留旧缓存"
                )[:160]
        except Exception as exc:  # noqa: BLE001
            self._state["ok"] = False
            self._state["error"] = f"{type(exc).__name__}: {exc}"[:160]
        finally:
            with self._lock:
                self._refreshing = False
            self._state["last"] = time.time()

    # ---------------- 对外入口 ----------------
    def meta(self) -> dict[str, Any]:
        ts, data = self._cache
        out: dict[str, Any] = {
            "count": len(data),
            "age_sec": int(time.time() - ts) if ts else None,
            "stale": (not data) or (time.time() - ts >= self.ttl),
            "refreshing": self._refreshing,
            "last_refresh_ok": self._state.get("ok"),
        }
        if self.include_updated:
            # 行情真正抓取完成的时刻（≠ 响应生成时间）—— 前端「上次更新」显示用它
            out["updated"] = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else None
            )
        return out

    def get(self, fetch_fn: FetchFn, force: bool = False) -> dict[str, dict[str, Any]]:
        """全部成分股的最新行情（stale-while-revalidate）。

        force=True：跳过新鲜度判定直接起后台刷新（手动刷新按钮用）——
        立即返回当前缓存，刷完后由下一轮轮询取到新数据，绝不在请求线程里联网。
        """
        ts, data = self._cache
        if not data:                       # 冷启动：先读磁盘快照
            ts, data = self.load_disk()
            if data:
                with self._lock:
                    if not self._cache[1]:
                        self._cache = (ts, data)

        fresh_enough = bool(data) and not force and time.time() - ts < self.ttl
        if fresh_enough:
            return data

        with self._lock:
            busy = self._refreshing
            if not busy:
                self._refreshing = True
        if not busy:
            threading.Thread(
                target=self.bg_refresh, args=(fetch_fn,), daemon=True,
                name=self.thread_name,
            ).start()
        return dict(data)
