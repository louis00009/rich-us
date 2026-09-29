"""美股基本面字段（腾讯批量行情扩展字段）的分层缓存。

为什么单独一个模块、而且**不落数据库**
--------------------------------------
榜单页需要的估值字段（PE / PB / 股息率…）里，PE 会随**价格**每时每刻漂移。
如果把 PE 存进 `CompanyProfile` 这类长缓存，几周后用户看到的 PE 就是错的
（而且不会有任何报错）。真正低频的只有 EPS / 股本 —— 一个季度才变一次。

所以这里缓存的是**原始字段**，PE 由调用方用「榜单现价 ÷ 缓存 EPS」实时合成
（见 `rankings.py::_attach_fundamentals`）。这样：
  · 显示的 PE 永远与显示的现价、EPS 算术自洽（用户拿计算器一算就对得上）；
  · PE 不需要单独设 TTL，也不会陈旧。

缓存策略与 `rankings.quotes()` 完全一致（stale-while-revalidate）：
  1) 内存 TTL 600s；过期也**立即返回旧数据**，后台线程去刷新 —— 请求永不等待网络；
  2) 磁盘快照 `runtime/cache/us_fundamentals.json`，重启后秒级可用；
  3) 单飞（`_refreshing` 旗标）保证同一时刻只有一路刷新。

字段口径与实测证据见 `company._F` 与 `tools/_probe_tencent_fields.py`。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from .company import batch_fields
from .config import CACHE_DIR

_TTL = 1800      # 30 分钟。全量刷新实测约 34s（11 次批量请求 / 503 只），
                 # 而缓存里的 EPS/股息率一个季度才变、PB 漂移很慢，
                 # 唯一对价格敏感的是 PE —— 它是用实时价现算的，不靠这个缓存。
_SNAPSHOT = CACHE_DIR / "us_fundamentals.json"

_lock = threading.Lock()
_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_refreshing = False
_universe: list[str] = []
_state: dict[str, Any] = {"last": 0.0, "ok": None}


def _load_disk() -> tuple[float, dict[str, dict[str, Any]]]:
    """磁盘快照恢复（原子读 + seed 兜底，见 cacheio 模块说明）。"""
    from .cacheio import ensure_seed, load_json_snapshot

    ensure_seed(_SNAPSHOT)
    data = load_json_snapshot(_SNAPSHOT)
    if data and data.get("fields"):
        try:
            return float(data.get("ts", 0.0)), dict(data["fields"])
        except Exception:  # noqa: BLE001
            return 0.0, {}
    return 0.0, {}


def _save_disk(fields: dict[str, dict[str, Any]]) -> None:
    from .cacheio import atomic_write_json

    atomic_write_json(_SNAPSHOT, {"ts": time.time(), "fields": fields})


def _bg_refresh() -> None:
    """后台拉取并落盘。合并而非覆盖 —— 腾讯偶尔漏掉个别标的，不能把已有数据冲掉。"""
    global _cache, _refreshing
    try:
        fresh = batch_fields(list(_universe))
        if fresh:
            with _lock:
                merged = {**_cache[1], **fresh}
                _cache = (time.time(), merged)
            _save_disk(merged)
            _state["ok"] = True
        else:
            _state["ok"] = False
    except Exception as exc:  # noqa: BLE001
        _state["ok"] = False
        _state["error"] = f"{type(exc).__name__}: {exc}"[:160]
    finally:
        with _lock:
            _refreshing = False
        _state["last"] = time.time()


def _refresh_async(syms: list[str]) -> None:
    """登记标的池（只增不减）并在需要时启动后台刷新线程。"""
    global _refreshing
    with _lock:
        if len(syms) > len(_universe):
            _universe[:] = syms
        if _refreshing or not _universe:
            return
        _refreshing = True
    threading.Thread(target=_bg_refresh, daemon=True, name="fundamentals-refresh").start()


def snapshot(symbols: list[str], force: bool = False) -> dict[str, dict[str, Any]]:
    """返回 {symbol: 字段}。**永不阻塞网络** —— 冷启动/过期时先回旧值再后台补。"""
    global _cache
    syms = [s.strip().upper() for s in symbols if s.strip()]
    ts, data = _cache
    if not data:                       # 冷启动：尝试磁盘快照
        ts, data = _load_disk()
        if data:
            with _lock:
                if not _cache[1]:
                    _cache = (ts, data)

    if data and not force and time.time() - ts < _TTL:
        return data
    _refresh_async(syms)
    return dict(data)


def meta() -> dict[str, Any]:
    ts, data = _cache
    return {
        "count": len(data),
        "age_sec": int(time.time() - ts) if ts else None,
        "stale": (not data) or (time.time() - ts >= _TTL),
        "refreshing": _refreshing,
        "last_refresh_ok": _state.get("ok"),
    }
