"""
QuantDesk for IBKR —— 应用入口
================================
安全基线（默认即生效）：
  · 仅绑定 127.0.0.1，不对局域网/公网暴露
  · CORS 白名单，仅允许本地前端源
  · 全部接口（除认证与健康检查）需 Bearer Token
  · 统一安全响应头（CSP / X-Frame-Options / nosniff / Referrer-Policy）
  · 请求体大小限制，防止内存放大攻击
  · 实盘三重锁：环境变量 → 运行时解锁 → 逐笔护栏
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .config import FRONTEND_DIST, RUNTIME_DIR, settings
from .database import init_db
from .state import log as audit_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("quantdesk")

MAX_BODY_BYTES = 4 * 1024 * 1024


def _backup_db() -> None:
    """SQLite 在线备份（VACUUM INTO）到 runtime/backups/，保留最近 7 份。"""
    import sqlite3
    import time as _time
    from pathlib import Path

    from .config import DB_PATH, RUNTIME_DIR

    bdir = RUNTIME_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    dest = bdir / f"quantdesk-{stamp}.db"
    if not DB_PATH.exists():
        return
    con = sqlite3.connect(str(DB_PATH))
    try:
        con.execute("VACUUM INTO ?", (str(dest),))
    finally:
        con.close()
    backups = sorted(bdir.glob("quantdesk-*.db"))
    for old in backups[:-7]:
        try:
            old.unlink()
        except OSError:
            pass
    log.info("数据库已备份 → %s", Path(dest).name)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    init_db()
    log.info("=" * 68)
    log.info("  %s v%s 已启动", settings.app_name, settings.version)
    log.info("  监听地址      : http://%s:%s", settings.host, settings.port)
    log.info("  运行目录      : %s", RUNTIME_DIR)
    log.info("  实盘环境开关  : %s", "已开启 ⚠️" if settings.allow_live_trading else "已关闭（安全默认）")
    log.info("  前端构建产物  : %s", "已挂载" if (FRONTEND_DIST / "index.html").exists() else "未构建")
    log.info("=" * 68)
    audit_log("app_start", "INFO", f"服务启动 v{settings.version}")
    # T-139：启动时备份数据库（VACUUM INTO，保留最近 7 份）
    try:
        _backup_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("启动备份失败（不影响运行）: %s", exc)
    # 后台预热 S&P 500 榜单行情（避免用户首次打开榜单页等待全量抓取）
    try:
        import threading as _th

        from . import rankings as _rank

        _th.Thread(target=_rank.quotes, daemon=True, name="rankings-warmup").start()
    except Exception:  # noqa: BLE001
        pass

    # 后台预热首页常用数据（T-135 性能）：日线缓存 + 大盘概览 + 关注列表报价
    def _warm_dashboard() -> None:
        import time as _time

        _time.sleep(1.5)
        try:
            from .api.market import _broker_quotes
            from .data_provider import fetch_history, get_quotes

            for sym in ("SPY", "QQQ", "NVDA", "0700.HK"):
                try:
                    fetch_history(sym, start="2025-01-01", interval="1d")
                except Exception:  # noqa: BLE001
                    pass
            try:
                get_quotes(["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "0700.HK"])
            except Exception:  # noqa: BLE001
                pass
            try:
                _broker_quotes(["SPY", "QQQ", "IWM", "DIA", "SMH", "TLT", "GLD", "USO", "^VIX", "FXI", "EEM", "IBIT"])
            except Exception:  # noqa: BLE001
                pass
            # 关注列表标的的日线全部预热：行情页切任何关注标的都是缓存命中（0.04s）
            try:
                from .database import SessionLocal
                from .models import WatchlistItem

                with SessionLocal() as s:
                    wl = [r.symbol for r in s.query(WatchlistItem).all()]
                for sym in wl[:15]:
                    try:
                        fetch_history(sym, start="2025-01-01", interval="1d")
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                pass
            log.info("首页预热完成")
        except Exception:  # noqa: BLE001
            pass

    try:
        import threading as _th2

        _th2.Thread(target=_warm_dashboard, daemon=True, name="dashboard-warmup").start()
    except Exception:  # noqa: BLE001
        pass

    # AI 情报中心：初始化默认观察标的 + 按持久化开关恢复监控（幂等、绝不阻塞启动）
    try:
        from . import intel as _intel

        _intel.resume_on_startup()
    except Exception:  # noqa: BLE001
        log.exception("Intel 初始化失败（不影响其他功能）")
    yield
    # 关闭时停止所有实时引擎
    try:
        from .engine import ACTIVE_ENGINES

        for task in list(ACTIVE_ENGINES.values()):
            await task.stop()
    except Exception:  # noqa: BLE001
        pass
    # 关闭 AI 情报调度线程（不关 run 状态，下次启动按 monitor_enabled 自恢复）
    try:
        from . import intel as _intel

        if _intel.SCHEDULER.alive:
            _intel.SCHEDULER._stop.set()
            if _intel.SCHEDULER._thread and _intel.SCHEDULER._thread.is_alive():
                _intel.SCHEDULER._thread.join(timeout=3)
    except Exception:  # noqa: BLE001
        pass
    audit_log("app_stop", "INFO", "服务停止")
    log.info("服务已停止")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="面向 IBKR 的 AI 量化交易平台：策略研究 · 回测 · 风控 · 模拟盘 · 实盘（三重锁）",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# 慢请求监控（T-137）：>2s 的 API 请求进内存环形队列（存于 appstate），/api/system/latency 可查
import time as _perf_time
from collections import deque as _deque


@app.middleware("http")
async def _slow_request_monitor_mw(request, call_next):  # noqa: ANN001
    t0 = _perf_time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        ms = (_perf_time.perf_counter() - t0) * 1000
        if ms > 2000 and request.url.path.startswith("/api"):
            from . import state as _st

            _st.record_slow_request(
                path=str(request.url.path), ms=round(ms),
                at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            )
            log.warning("慢请求 %.0fms %s %s", ms, request.method, request.url.path)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,          # 使用 Bearer Token，无需 Cookie
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # 请求体大小限制
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "请求体过大"}, status_code=413)

    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path.startswith(settings.api_prefix):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    # P2：统一 500 附带 request-id —— 旧实现响应只有异常类名，日志与响应无法关联。
    rid = uuid.uuid4().hex[:12]
    log.exception("[req %s] 未处理异常 %s %s: %s",
                  rid, request.method, request.url.path, exc)
    return JSONResponse(
        {"detail": f"服务内部错误：{type(exc).__name__}（request-id: {rid}，可凭此在服务日志中定位完整堆栈）"},
        status_code=500,
        headers={"X-Request-Id": rid},
    )


app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/api/health", tags=["系统"])
def health() -> dict:
    return {"ok": True, "app": settings.app_name, "version": settings.version}


# ------------------------------------------------------------------
# 前端静态资源（构建后单端口即可访问）
# ------------------------------------------------------------------
if (FRONTEND_DIST / "index.html").exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    # index.html 必须 no-cache：代码分割后 chunk 带 hash，浏览器缓存旧 html 会引用
    # 已被归档删除的旧 chunk → 404 → 页面白屏（用户端反复「页面有问题」的根因）。
    _NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """SPA 回退：非 API 路径一律返回 index.html（同样 no-cache）。"""
        target = (FRONTEND_DIST / full_path).resolve()
        try:
            target.relative_to(FRONTEND_DIST.resolve())
        except ValueError:
            return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)
        if full_path and target.is_file():
            return FileResponse(target, headers=_NO_CACHE if full_path.endswith(".html") else None)
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)
else:

    @app.get("/", include_in_schema=False)
    def index_placeholder() -> JSONResponse:
        return JSONResponse({
            "app": settings.app_name,
            "message": "后端已运行，前端尚未构建。请在 frontend 目录执行 npm install && npm run build",
            "api_docs": "/api/docs",
        })
