"""
启动脚本
=========
    python run.py                     # 默认 127.0.0.1:8787
    QD_ALLOW_LIVE_TRADING=true python run.py   # 开启实盘第一道锁（危险）

通过环境变量覆盖：QD_HOST / QD_PORT / QD_HOME ...
"""
from __future__ import annotations

import os
import sys
import webbrowser
from threading import Timer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    import uvicorn

    from app.config import FRONTEND_DIST, RUNTIME_DIR, settings

    autopen = os.environ.get("QD_OPEN_BROWSER", "1") != "0"
    url = f"http://{'127.0.0.1' if settings.host in ('0.0.0.0', '127.0.0.1') else settings.host}:{settings.port}/"

    print("=" * 70)
    print(f"  {settings.app_name} v{settings.version}")
    print(f"  访问地址    : {url}")
    print(f"  接口文档    : {url}api/docs")
    print(f"  运行目录    : {RUNTIME_DIR}")
    print(f"  实盘开关    : {'已开启 ⚠️' if settings.allow_live_trading else '已关闭（安全默认）'}")
    print(f"  前端产物    : {'已构建' if (FRONTEND_DIST / 'index.html').exists() else '未构建（仅 API 可用）'}")
    print("=" * 70)

    if autopen:
        Timer(1.6, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
