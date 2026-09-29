"""一次性工具：从 Wikipedia 抓 NASDAQ 100 成分 → `app/markets/nasdaq100.json`。

解析逻辑与自动刷新**只此一份**（`app.universe.parse_ndx_components`），
本脚本只负责强制执行一次刷新并落盘 —— 运行时的 7 天自动刷新走
`universe.refresh_ndx100()`，不要在这里另写解析。

用法：
    cd backend && .venv/Scripts/python.exe ../tools/gen_nasdaq100.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.universe import refresh_ndx100  # noqa: E402


def main() -> int:
    res = refresh_ndx100(force=True)
    if res.get("refreshed"):
        print(f"OK: {res['count']} 只已写入 app/markets/nasdaq100.json")
        return 0
    print(f"FAIL: {res}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
