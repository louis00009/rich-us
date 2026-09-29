"""
文件规模上限检查 —— **铁律 9 的可执行版本**
==========================================
`TODO.md` 的铁律 9 早就定了上限，也写了「当前已超硬上限的冻结清单」，但**没有任何东西在执行它**。
后果实测：清单写 `backend/app/intel.py` 1192 行，实际已涨到 **1916**；`Backtest.tsx` 写 1086，
实际 **1641**；而清单里还留着早已拆完的 `Intel.tsx` 1269（现已 329）。**规则靠人记 = 规则不存在。**

这里把规则变成可执行的**棘轮（ratchet）**：允许现状存在，但**不许变差**。

上限（与 TODO.md 铁律 9 一致）
------------------------------
| 类别 | 软上限（超了不许再加功能） | 硬上限（冻结，只允许修 bug） |
|---|---|---|
| 后端模块 `backend/app/**/*.py`      | 600 | 900 |
| 前端页面 `frontend/src/pages/**`    | 600 | 900 |
| 前端组件 `frontend/src/components/**` | 400 | 600 |
| 前端工具 `frontend/src/lib/**`      | 400 | 600 |

判定规则
--------
1. 超过软上限、且**不在基线里** → FAIL（新产生的债，一律不许）。
2. 在基线里但**比基线更长** → FAIL（棘轮：存量债不许再长）。
3. 在基线里且未增长 → 通过，但在报告里列出（存量债，可见即可治理）。
4. 基线里的文件已降到软上限以内 → 提示可从基线摘掉（不算失败）。

基线文件：`tests/size_baseline.json`（`{"<相对仓库根的路径>": 行数}`）。
重算基线：`python tools/gen_size_baseline.py`（**只在真正拆分完成后**跑，否则等于把债锁死）。
"""
from __future__ import annotations

import json
from pathlib import Path

# (相对仓库根的目录, 纳入的后缀, 软上限, 硬上限)
#
# ⚠️ 不要用 `Path.glob("backend/app/**/*.py")` —— `**` 在本机 Python 上**不匹配顶层文件**，
#    实测会漏掉 `backend/app/intel.py`（1916 行，最该管的那个！）而只匹配到子目录里的文件。
#    所以这里用「目录 + 后缀 + rglob」的写法，语义明确且不会漏。
RULES: list[tuple[str, tuple[str, ...], int, int]] = [
    ("backend/app", (".py",), 600, 900),
    ("frontend/src/pages", (".tsx",), 600, 900),
    ("frontend/src/components", (".tsx", ".ts"), 400, 600),
    ("frontend/src/lib", (".ts",), 400, 600),
]

# 明确豁免的文件（生成物 / 数据表 / 第三方拷贝）。**留空是有意的** ——
# 一旦往里加东西，就等于承认「这个文件的规模不用管」，请先确认真的无解。
EXEMPT: set[str] = set()

BASELINE_PATH = Path(__file__).resolve().parent / "size_baseline.json"


def limits_for(rel: str) -> tuple[int, int] | None:
    """按类别给出 (软上限, 硬上限)；不属于任何类别返回 None。"""
    for base, suffixes, soft, hard in RULES:
        if rel.startswith(base + "/") and rel.endswith(suffixes):
            return soft, hard
    return None


def collect(root: Path) -> dict[str, int]:
    """扫出所有受管文件的行数：{相对仓库根的 posix 路径: 行数}。"""
    out: dict[str, int] = {}
    for base, suffixes, _soft, _hard in RULES:
        d = root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or not p.name.endswith(suffixes):
                continue
            rel = p.relative_to(root).as_posix()
            if rel in EXEMPT:
                continue
            try:
                out[rel] = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                continue
    return out


def load_baseline(path: Path | None = None) -> dict[str, int]:
    p = path or BASELINE_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}


def audit(root: Path, baseline: dict[str, int] | None = None) -> dict:
    """执行棘轮判定，返回结构化结果（不打印、不退出，便于被 run_checks 或工具复用）。"""
    base = load_baseline() if baseline is None else baseline
    sizes = collect(root)

    fails: list[str] = []          # 必须修的
    debt: list[tuple[str, int, int, int]] = []   # 存量债 (rel, lines, soft, hard)
    stale: list[str] = []          # 基线里已不再超软上限的
    new_over: list[tuple[str, int, int]] = []    # 新增超软（rel, lines, soft）

    for rel, lines in sorted(sizes.items()):
        lim = limits_for(rel)
        if lim is None:
            continue
        soft, hard = lim
        if lines <= soft:
            if rel in base:
                stale.append(rel)
            continue
        debt.append((rel, lines, soft, hard))
        if rel in base:
            if lines > base[rel]:
                tag = "硬上限" if lines > hard else "软上限"
                fails.append(
                    f"{rel}: {base[rel]} → {lines} 行（超出{tag}且比基线更长；"
                    f"铁律 9：超过{'硬' if lines > hard else '软'}上限不得再加功能，请拆模块）"
                )
        else:
            new_over.append((rel, lines, soft))
            fails.append(f"{rel}: {lines} 行 > 软上限 {soft}（**新产生的债**，请先拆再提交）")

    return {"sizes": sizes, "fails": fails, "debt": debt, "stale": stale,
            "new_over": new_over, "baseline": base}
