"""榜单缓存的磁盘读写公共层：原子写 / 损坏容错 / 出厂快照兜底。

为什么必须抽出来（三个模块各写一份必然漂移）
--------------------------------------------
2026-09-28 实测事故：`sp500_quotes.json` 变成 **0 字节** —— `_save_disk` 用
`Path.write_text`（先截断再写），进程在写入途中被杀（重启/断电/任务终止）就留下
一个截断文件。后果是磁盘恢复链整个失效：每次重启行情缓存都是空的，用户打开
榜单页要等 yfinance 全量抓完（30~40s）才见数据 ——「每次开启都太慢」的直接根因。

三条铁律：
  1. **原子写**：先写 `.tmp` 再 `os.replace()` —— 任何时刻磁盘上都只有
     完整的旧文件或完整的新文件，不存在中间态。
  2. **读容错**：文件缺失 / 0 字节 / JSON 损坏一律返回 None（调用方走
     stale-while-revalidate 后台补），绝不抛异常阻塞请求。
  3. **seed 兜底**：缓存文件不存在（全新安装 / 换机器 / 手动清缓存）时，
     从仓库内置的出厂快照复制一份 —— 首次打开也有完整数据（旧但可看），
     后台刷新立刻接管。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

# 出厂快照目录：backend/app/markets/seed/（随代码分发，内容是发布时的完整榜单缓存）
SEED_DIR = Path(__file__).resolve().parent / "markets" / "seed"


def atomic_write_json(path: Path, data: Any) -> None:
    """原子写 JSON：任何中断都不会留下截断/0 字节文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)          # Windows / POSIX 上都是原子操作
    except BaseException:  # noqa: BLE001 —— 落盘失败（含 safe-delete 护栏的 SystemExit）不影响内存缓存
        try:
            if tmp.exists():
                tmp.unlink()
        except BaseException:  # noqa: BLE001
            pass


def load_json_snapshot(path: Path) -> dict[str, Any] | None:
    """安全读快照。缺失/0 字节/损坏 → None（绝不抛异常）。"""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 —— 损坏文件等价于不存在
        return None


def ensure_seed(path: Path) -> None:
    """缓存文件缺失/为空时，从出厂快照复制一份（只复制，不改写）。

    调用时机：各缓存模块 `_load_disk()` 发现没有可用数据时先调这个再重读。
    """
    try:
        if path.exists() and path.stat().st_size > 0:
            return
        seed = SEED_DIR / path.name
        if seed.exists() and seed.stat().st_size > 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(seed, path)
    except Exception:  # noqa: BLE001 —— seed 只是兜底，失败就当没有
        pass


def seed_fresh(path: Path, max_age_sec: float) -> bool:
    """出厂快照是否存在且足够新（决定「首次 ever」是否值得走 seed 路径）。"""
    seed = SEED_DIR / path.name
    try:
        return seed.exists() and seed.stat().st_size > 0 and \
            (time.time() - seed.stat().st_mtime) < max_age_sec
    except Exception:  # noqa: BLE001
        return False
