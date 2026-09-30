"""OHLCV 磁盘缓存（从 `data_provider.py` 拆出，铁律 9，2026-09-30）。

两个历史缺陷在这里被修复，拆分时**语义原样保留**：
  · **覆盖度校验**：旧实现只按 TTL 判新鲜度、不看请求区间 —— 先用短区间填充过缓存，
    之后请求更早的数据会命中短缓存并返回，回测/优化器静默地在错误区间上计算。
  · **原子写**：旧实现直接 `to_csv(path)`（先截断再写），并发读者可能解析出半截文件，
    若截断落在行边界，`read_csv` 还会「成功」返回缺尾部的短数据并被长期复用。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd

from .config import CACHE_DIR


# 缓存覆盖度容差（天）：缓存起始日必须不晚于「请求起始日 + 容差」，否则视为未命中
_COVER_TOL = {"1d": 7, "1wk": 14, "1h": 3, "30m": 2, "15m": 1, "5m": 1, "1m": 1}
# 单标的缓存上限行数（防止长期运行后 CSV 无限膨胀）
_CACHE_MAX_ROWS = {"1d": 6000, "1wk": 1500, "1h": 8000, "30m": 8000, "15m": 8000, "5m": 8000, "1m": 2000}
# ------------------------------------------------------------------
# 缓存
# ------------------------------------------------------------------
def _cache_path(symbol: str, interval: str) -> Path:
    safe = symbol.replace("^", "IDX_").replace("/", "_").replace("\\", "_")
    d = CACHE_DIR / interval
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.csv"


# P1-5：按缓存文件路径分锁 —— 并发写同一 CSV 时避免半截文件与「读-合并-写」丢更新。
_cache_locks: dict[str, threading.Lock] = {}
# 保护 _cache_locks 自身的创建。
# ⚠️ 拆分前这里用的是 data_provider 的 `_locks_guard`（那把锁同时护着单飞 _inflight）；
#    拆出后缓存与单飞已无共享状态，各自用独立的锁更清晰，也避免跨模块耦合。
_cache_locks_guard = threading.Lock()


def _cache_lock(path: Any) -> threading.Lock:
    key = str(path)
    with _cache_locks_guard:
        lk = _cache_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _cache_locks[key] = lk
        return lk


def _read_cache(
    symbol: str, interval: str, ttl: int,
    start: str | None = None, end: str | None = None,
    ignore_ttl: bool = False,
) -> pd.DataFrame | None:
    """读缓存。**必须校验覆盖度**。

    历史缺陷：缓存只按 TTL 判断新鲜度，不看请求区间。一旦先用短区间（如 2024 起）
    填充过缓存，之后请求 2019 起的数据会直接命中这份短缓存并返回 ——
    回测和优化器于是静默地在错误的时间区间上计算。
    ignore_ttl=True 时跳过新鲜度检查（增量更新分支用：过期缓存仍可作合并基底）。
    """
    p = _cache_path(symbol, interval)
    if not p.exists():
        return None
    if not ignore_ttl and time.time() - p.stat().st_mtime > ttl:
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    try:
        df.index = pd.to_datetime(df.index)
    except Exception:
        return None

    tol = _COVER_TOL.get(interval, 7)
    if start:
        try:
            want = pd.to_datetime(start)
            if df.index.min() > want + pd.Timedelta(days=tol):
                return None                      # 缓存起点晚于请求区间 → 未命中
        except Exception:
            pass
    if end:
        try:
            want_end = pd.to_datetime(end)
            if df.index.max() < want_end - pd.Timedelta(days=tol):
                return None
        except Exception:
            pass
    return df


def _write_cache(symbol: str, interval: str, df: pd.DataFrame) -> None:
    """写缓存；与已有内容合并，使覆盖区间随时间增长而不是被短区间覆盖掉。

    P1-5：**原子写**。旧实现直接 `merged.to_csv(path)`（先截断再写），并发场景下
    读者可能解析出半截文件；若截断恰好落在行边界，`read_csv` 还会「成功」返回
    缺尾部的短数据，被当成有效缓存长期复用。改为：同路径加锁 + 写临时文件后
    `Path.replace` 原子替换 —— 读方要么看到完整旧文件、要么看到完整新文件。
    """
    try:
        path = _cache_path(symbol, interval)
        with _cache_lock(path):
            merged = df
            if path.exists():
                try:
                    old = pd.read_csv(path, index_col=0, parse_dates=True)
                    if old is not None and not old.empty:
                        old.index = pd.to_datetime(old.index)
                        merged = pd.concat([old, df])
                        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                except Exception:
                    merged = df
            cap = _CACHE_MAX_ROWS.get(interval, 6000)
            if len(merged) > cap:
                merged = merged.iloc[-cap:]
            tmp = path.with_name(f"{path.name}.tmp{threading.get_ident()}")
            try:
                merged.to_csv(tmp)
                tmp.replace(path)          # 同盘 rename → 原子替换
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                    except BaseException:  # noqa: BLE001 —— safe-delete 护栏抛 SystemExit，清理失败不外溢
                        pass
    except Exception:
        pass
