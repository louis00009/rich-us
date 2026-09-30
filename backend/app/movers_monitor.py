"""常驻监控任务（movers 模块的「开关 + 持续运行」部分）。

从 movers.py 按铁律 9（FILE_SIZE_DEBT Batch D-3）拆出：
- 配置持久化（state.set_setting 存储，重启后自动恢复，main.py lifespan 调 resume_monitor）；
- 后台线程按所选间隔扫描 movers() 并写当日审计日志；
- 状态查询带 AI 配置标记。

⚠️ 与 movers.py 是双向依赖：本模块在**函数体内**延迟 import movers()
（避免环形 import）；movers.py 顶部 re-export 本模块的公开名字，
外部 `from app.movers import set_monitor_cfg` 等旧路径不变。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

_CFG_KEY = "movers_monitor"

_mon_lock = threading.Lock()
_mon_thread: threading.Thread | None = None
_stop_event = threading.Event()
_mon_state: dict[str, Any] = {"running": False, "last_scan": "", "scans": 0, "last_error": ""}


def _monitor_cfg() -> dict[str, Any]:
    """读取持久化配置（state.set_setting 存储，重启后自动恢复）。"""
    cfg: dict[str, Any] = {}
    try:
        from .state import get_setting

        raw = get_setting(_CFG_KEY, "")
        if raw:
            cfg = json.loads(raw)
    except Exception:  # noqa: BLE001 —— 配置损坏按默认处理
        cfg = {}
    try:
        threshold = max(0.5, min(20.0, float(cfg.get("threshold") or 3.0)))
    except (TypeError, ValueError):
        threshold = 3.0
    try:
        interval = max(30, min(600, int(cfg.get("interval") or 60)))
    except (TypeError, ValueError):
        interval = 60
    return {
        "enabled": bool(cfg.get("enabled")),
        "threshold": threshold,
        "interval": interval,
        "model": str(cfg.get("model") or ""),
    }


def set_monitor_cfg(enabled: bool | None = None, threshold: float | None = None,
                    interval: int | None = None, model: str | None = None) -> dict[str, Any]:
    """更新监控配置（持久化）并立即生效（起线程 / 停线程）。"""
    cfg = _monitor_cfg()
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if threshold is not None:
        try:
            cfg["threshold"] = max(0.5, min(20.0, float(threshold)))
        except (TypeError, ValueError):
            pass
    if interval is not None:
        try:
            cfg["interval"] = max(30, min(600, int(interval)))
        except (TypeError, ValueError):
            pass
    if model is not None:
        cfg["model"] = str(model or "")
    from .state import set_setting

    set_setting(_CFG_KEY, json.dumps(cfg, ensure_ascii=False))
    if cfg["enabled"]:
        _ensure_thread()
    else:
        _stop_event.set()
    return monitor_status()


def monitor_status() -> dict[str, Any]:
    with _mon_lock:
        live = dict(_mon_state)
    try:
        from .ai_analyst import ai_configured
    except Exception:  # noqa: BLE001 —— AI 模块不可用不拖垮状态查询
        def ai_configured() -> bool:
            return False

    return {
        **live,
        "cfg": _monitor_cfg(),
        "llm_configured": ai_configured(),
    }


def _monitor_loop() -> None:
    """常驻扫描循环：每 interval 秒跑一轮 movers()（内部写审计日志）。"""
    from .movers import movers          # 延迟 import：movers.py 顶部 re-export 本模块

    while not _stop_event.is_set():
        cfg = _monitor_cfg()
        if not cfg["enabled"]:
            break
        try:
            movers(threshold=cfg["threshold"], limit=15)
            with _mon_lock:
                _mon_state["running"] = True
                _mon_state["last_scan"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _mon_state["scans"] = int(_mon_state["scans"]) + 1
                _mon_state["last_error"] = ""
        except Exception as exc:  # noqa: BLE001 —— 单轮失败不能停监控
            with _mon_lock:
                _mon_state["last_error"] = f"{type(exc).__name__}: {exc}"[:160]
        _stop_event.wait(cfg["interval"])
    with _mon_lock:
        _mon_state["running"] = False


def _ensure_thread() -> None:
    global _mon_thread
    with _mon_lock:
        if _mon_thread is not None and _mon_thread.is_alive():
            return
        _stop_event.clear()
        _mon_state["running"] = True
        _mon_thread = threading.Thread(target=_monitor_loop, daemon=True, name="movers-monitor")
        _mon_thread.start()      # ⚠️ 创建≠启动 —— 漏掉 start() 时 running 旗标为 True 但扫描永不发生


def resume_monitor() -> None:
    """服务启动时恢复常驻监控（cfg.enabled=true 才起线程）。由 main.py lifespan 调。"""
    try:
        if _monitor_cfg()["enabled"]:
            _ensure_thread()
    except Exception:  # noqa: BLE001
        pass
