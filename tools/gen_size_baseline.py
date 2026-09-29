"""
重算文件规模基线（`tests/size_baseline.json`）
==============================================
基线是**棘轮**：允许现状存在，但任何文件都不许比基线更长，也不许出现新的超限文件。

⚠️ **只在真正拆分完成之后跑这个脚本。** 在没拆分时重算 = 把当前债务写进基线 = 棘轮失效。

用法（仓库根）：
    python tools/gen_size_baseline.py            # 重算并写入
    python tools/gen_size_baseline.py --dry-run  # 只打印差异，不写
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import size_check  # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv
    old = size_check.load_baseline()
    sizes = size_check.collect(ROOT)

    # 基线 = 所有「超过软上限」的文件及其当前行数（含已超硬上限的存量冻结项）
    new: dict[str, int] = {}
    for rel, lines in sorted(sizes.items()):
        lim = size_check.limits_for(rel)
        if lim is None:
            continue
        soft, _hard = lim
        if lines > soft:
            new[rel] = lines

    grew = {k: (old.get(k), v) for k, v in new.items() if k in old and v > old[k]}
    shrank = {k: (old[k], new.get(k)) for k in old if k not in new or new[k] < old[k]}
    added = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]

    print(f"受管文件 {len(sizes)} 个；超软上限 {len(new)} 个（旧基线 {len(old)} 个）")
    if added:
        print("\n新增进基线（本来不该有）：")
        for k in added:
            print(f"  + {k}  {new[k]} 行")
    if grew:
        print("\n比旧基线更长（棘轮被突破 —— 确认是真拆分导致的话才继续）：")
        for k, (a, b) in grew.items():
            print(f"  ↑ {k}  {a} → {b} 行")
    if removed:
        print("\n已降到软上限以内，从基线摘掉（好事）：")
        for k in removed:
            print(f"  - {k}  原 {old[k]} 行")
    if shrank and not removed:
        print("\n变短但仍在软上限以上：")
        for k, (a, b) in shrank.items():
            print(f"  ↓ {k}  {a} → {b} 行")

    if dry:
        print("\n--dry-run：未写入。")
        return 0

    out = size_check.BASELINE_PATH
    out.write_text(json.dumps(new, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n已写入 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
