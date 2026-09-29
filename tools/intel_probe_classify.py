"""抽样检视事件归类规则的产出（人工核对用，不写库）
=====================================================

**为什么需要**：`intel_classify` 的规则一旦放宽就会给噪音贴错标签，而错标签会经
`STAGE_WEIGHT` / `CATEGORY_WEIGHT` 影响重要度排序 —— **错标签比缺标签危害大得多**。
单测只钉住了已知反例；真实语料里还有大量没想到的措辞。所以调完规则必须**对着全量标题
人工抽样看一遍**，这个工具就是干这个的（当初正是靠它抓出 5 处误判：
「How to Play X Stock Now」荐股稿、「【美股盘前】」综述、内部人交易、表态稿、分析稿）。

用法：

    cd backend
    QD_HOME="$PWD/runtime" .venv/Scripts/python.exe ../tools/intel_probe_classify.py [每类条数]

输出：每个将要新归入的 category / stage 各列 N 条真实标题。**只读，不改库。**

配套：`tools/intel_backfill_classify.py`（正式回填，默认 dry-run）。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.database import init_db, session_scope  # noqa: E402
from app.intel_classify import infer_category, infer_stage, is_commentary  # noqa: E402
from app.models import IntelEvent  # noqa: E402


def main() -> int:
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    init_db()

    cat_counts: dict[str, int] = defaultdict(int)
    stage_counts: dict[str, int] = defaultdict(int)
    cat_samples: dict[str, list[str]] = defaultdict(list)
    stage_samples: dict[str, list[str]] = defaultdict(list)
    commentary = 0
    total = 0

    with session_scope() as db:
        rows = db.query(IntelEvent).order_by(IntelEvent.id).all()
        total = len(rows)
        for e in rows:
            title = e.title or ""
            if is_commentary(title):
                commentary += 1
            if not e.category or e.category == "other":
                got = infer_category(title)
                if got:
                    cat_counts[got] += 1
                    if len(cat_samples[got]) < samples:
                        cat_samples[got].append(title)
            if not (e.stage or ""):
                got = infer_stage(title)
                if got:
                    stage_counts[got] += 1
                    if len(stage_samples[got]) < samples:
                        stage_samples[got].append(title)

    print(f"事件总数 {total}；判为评论/播报（保留 other）{commentary} 条")
    print("\n=== category：将要新归类的条目（抽样）===")
    for k in sorted(cat_counts, key=lambda x: -cat_counts[x]):
        print(f"\n-- {k}  ({cat_counts[k]} 条)")
        for t in cat_samples[k]:
            print(f"     {t[:110]}")
    print("\n=== stage：将要新归类的条目（抽样）===")
    for k in sorted(stage_counts, key=lambda x: -stage_counts[x]):
        print(f"\n-- {k}  ({stage_counts[k]} 条)")
        for t in stage_samples[k]:
            print(f"     {t[:110]}")
    print("\n⚠️ 人工逐条核对：有任何一条不该命中，就去改 app/intel_classify.py 的规则，"
          "并把它加进 tests/run_checks.py 的反例清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
