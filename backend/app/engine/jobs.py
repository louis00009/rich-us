"""后台长任务注册表
==================

评估报告（P1-14/功能不完善·高）指出：回测 / 网格寻优是不可取消的同步 HTTP 请求 ——
网格 200 组要跑几分钟，占死一个 anyio 工作线程，前端无法取消也无法显示进度。

设计：
  * 任务在**受限线程池**中运行（不再占用 run_in_threadpool 的稀缺工作线程）；
  * `fn(progress_cb, cancel_event) -> result`：任务体用 progress_cb 上报进度，
    在合适的检查点轮询 cancel_event（协作式取消，不做粗暴的线程终止）；
  * 完成任务在内存保留 30 分钟供查询，**由独立 GC 循环**定期清理；
  * 仅本地单机使用，注册表即内存 dict —— 重启后任务消失（前端按 404 优雅降级）。

P1-7 修复（v2 审查）：
  * 旧实现每次 start() 裸起一个 daemon 线程，**无并发上限** —— 反复提交寻优会线程膨胀；
  * `_gc_locked()` 只在 start() 内被调用，不再提交新任务时**过期结果永不回收**；
  * `progress()` 无锁写、`get()` 持锁读，存在撕裂。
  现改为：ThreadPoolExecutor(max_workers) + 独立 GC 线程 + 全部状态变更进锁。
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

ProgressCb = Callable[[int, int], None]

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_TTL_SEC = 1800.0
_MAX_WORKERS = 4            # 并发上限：本地单机，UI 一次只提交一个任务，4 足够
_GC_INTERVAL_SEC = 300.0    # 独立 GC 周期

_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="qd-job")
_gc_started = False


def _gc_locked() -> None:
    """清理过期任务结果（调用方必须已持有 _lock）。"""
    now = time.time()
    stale = [
        k for k, v in _jobs.items()
        if v.get("finished") is not None and now - float(v["finished"]) > _TTL_SEC
    ]
    for k in stale:
        _jobs.pop(k, None)


def _gc_loop() -> None:
    """P1-7：独立 GC 循环 —— 旧实现只在 start() 里 GC，不再提交任务就永不回收。"""
    while True:
        time.sleep(_GC_INTERVAL_SEC)
        try:
            with _lock:
                _gc_locked()
        except Exception:  # noqa: BLE001 —— GC 线程绝不能死
            pass


def _ensure_gc() -> None:
    global _gc_started
    with _lock:
        if _gc_started:
            return
        _gc_started = True
    threading.Thread(target=_gc_loop, daemon=True, name="qd-job-gc").start()


def start(kind: str, fn: Callable[[ProgressCb, threading.Event], Any]) -> str:
    """启动后台任务，返回 job_id。

    fn 签名：(progress(done, total), cancel_event) -> result。
    任务体抛出的异常会被捕获并转为 status="error"（取消时不视为错误）。
    """
    _ensure_gc()
    job_id = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "id": job_id, "kind": kind, "status": "running",
        "progress": 0, "total": 0, "started": time.time(),
        "finished": None, "result": None, "error": "",
        "cancel": threading.Event(),
    }
    with _lock:
        _gc_locked()
        _jobs[job_id] = job

    def progress(done: int, total: int) -> None:
        # P1-7：与 get() 同锁，避免读写撕裂
        with _lock:
            job["progress"] = int(done)
            job["total"] = int(total)

    def runner() -> None:
        try:
            result = fn(progress, job["cancel"])
            with _lock:
                job["result"] = result
                job["status"] = "cancelled" if job["cancel"].is_set() else "done"
        except Exception as exc:  # noqa: BLE001 —— 任务失败必须可见而不是静默挂死
            with _lock:
                if job["cancel"].is_set():
                    job["status"] = "cancelled"
                else:
                    job["status"] = "error"
                    job["error"] = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            with _lock:
                job["finished"] = time.time()

    # P1-7：走受限线程池，而不是每次裸起一个无上限的 daemon 线程
    try:
        _executor.submit(runner)
    except Exception as exc:  # noqa: BLE001 —— 提交失败也要让前端看到明确原因
        with _lock:
            job["status"] = "error"
            job["error"] = f"任务提交失败: {type(exc).__name__}: {exc}"[:300]
            job["finished"] = time.time()
    return job_id


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {
            "id": job["id"], "kind": job["kind"], "status": job["status"],
            "progress": job["progress"], "total": job["total"],
            "elapsed_sec": round((job["finished"] or time.time()) - job["started"], 1),
            "result": job["result"], "error": job["error"],
        }


def cancel(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
    if job is None or job["status"] != "running":
        return False
    job["cancel"].set()
    return True


def active_count() -> int:
    with _lock:
        return sum(1 for v in _jobs.values() if v["status"] == "running")
