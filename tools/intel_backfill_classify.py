"""一次性回填：给历史情报事件补 category / stage
=================================================

**为什么需要**：`intel_classify` 的归一化是在**入库口**生效的，只对**新事件**起作用。
但库里已有 3300+ 条历史事件 —— 其中 `stage` 覆盖率只有 2%、`category` 有 47% 落在 `other`。
不回头补，页面的「阶段」筛选与「类别」筛选对历史数据就永远是废的。

用法（默认 **dry-run，不写库**）：

    cd backend
    QD_HOME="$PWD/runtime" .venv/Scripts/python.exe ../tools/intel_backfill_classify.py
    QD_HOME="$PWD/runtime" .venv/Scripts/python.exe ../tools/intel_backfill_classify.py --apply

安全约束
--------
· **只补空**：`category != other` 的不动，`stage` 非空的不动 —— 尊重提交方。
· **dedupe_key 必须同步重算**：`make_dedupe_key(symbol, category, title)` 含 category，
  改了 category 却不改 key，会让「同一事件再次提交」漏判成新条目（产生重复）。
· `dedupe_key` 上有唯一约束：若重算后的 key 已被别的行占用，**跳过该行**并计入报告，
  绝不删数据、绝不覆盖别人的 key。
· 幂等：跑第二遍应报告 0 改动。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.database import init_db, session_scope  # noqa: E402
from app.intel import EVENT_CATEGORIES, EVENT_STAGES, make_dedupe_key  # noqa: E402
from app.intel_classify import infer_category, infer_stage, is_commentary  # noqa: E402
from app.models import IntelEvent  # noqa: E402


def main() -> int:
    apply_changes = "--apply" in sys.argv
    init_db()

    cat_moves: Counter[tuple[str, str]] = Counter()
    stage_moves: Counter[tuple[str, str]] = Counter()
    skipped_collision = 0
    commentary = 0
    total = 0

    with session_scope() as db:
        rows = db.query(IntelEvent).order_by(IntelEvent.id).all()
        total = len(rows)
        # 先收集现有 key，避免同一批里互相撞车
        taken = {e.dedupe_key for e in rows}

        for e in rows:
            title = e.title or ""
            if is_commentary(title):
                commentary += 1

            new_cat = e.category
            if not e.category or e.category == "other":
                got = infer_category(title)
                if got:
                    new_cat = got

            new_stage = e.stage or ""
            if not new_stage:
                got = infer_stage(title)
                if got:
                    new_stage = got

            cat_changed = new_cat != e.category
            stage_changed = new_stage != (e.stage or "")
            if not cat_changed and not stage_changed:
                continue

            new_key = e.dedupe_key
            if cat_changed:
                new_key = make_dedupe_key(e.symbol, new_cat, title)
                # key 被别的行占用 → 说明归一化后两行是同一事件，跳过不合并（不删数据）
                if new_key != e.dedupe_key and new_key in taken:
                    skipped_collision += 1
                    continue
                taken.discard(e.dedupe_key)
                taken.add(new_key)

            if cat_changed:
                cat_moves[(e.category, new_cat)] += 1
            if stage_changed:
                stage_moves[(e.stage or "(空)", new_stage)] += 1

            if apply_changes:
                e.category = new_cat
                e.stage = new_stage
                e.dedupe_key = new_key

    mode = "已写入" if apply_changes else "DRY-RUN（未写库，加 --apply 生效）"
    print("=" * 66)
    print(f"  历史事件归类回填  [{mode}]")
    print("=" * 66)
    print(f"扫描事件总数：{total}")
    print(f"评论/行情播报类（保留 other，不归类）：{commentary}")
    print()
    print(f"category 变更：{sum(cat_moves.values())} 条")
    for (src, dst), n in cat_moves.most_common():
        print(f"    {EVENT_CATEGORIES.get(src, src):<10} → {EVENT_CATEGORIES.get(dst, dst):<10} {n:>5}")
    print()
    print(f"stage 变更：{sum(stage_moves.values())} 条")
    for (src, dst), n in stage_moves.most_common():
        label = EVENT_STAGES.get(dst, dst) if dst else dst
        print(f"    {src:<12} → {label:<10} {n:>5}")
    print()
    if skipped_collision:
        print(f"⚠️ 因 dedupe_key 冲突而跳过：{skipped_collision} 条（归一化后与既有条目同键，未合并）")
    if not apply_changes:
        print("提示：这是 dry-run，数据库没有改动。确认无误后加 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
