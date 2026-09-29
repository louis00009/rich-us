"""
把已灌库的 CSV 批量转成 parquet（一次性迁移）

背景：首轮灌库时 pyarrow 未安装 → 回落 CSV（503 个文件）。
装上 pyarrow 后，用本脚本原地转换，避免重跑 20 分钟。

用法：
  cd backend
  .venv/Scripts/python.exe ../tools/migrate_csv_to_parquet.py            # 转换
  .venv/Scripts/python.exe ../tools/migrate_csv_to_parquet.py --keep-csv # 保留 CSV
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BARS = ROOT / "backend" / "runtime" / "ibkr_bars"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-csv", action="store_true", help="转换后保留 CSV")
    ap.add_argument("--dir", default=str(BARS))
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.exists():
        print(f"❌ 目录不存在：{d}")
        return 2

    try:
        import pandas as pd
    except ImportError:
        print("❌ 未安装 pandas")
        return 2

    csvs = sorted(d.glob("*.csv"))
    print(f"发现 {len(csvs)} 个 CSV → 转换中…")

    ok = skip = fail = 0
    for i, c in enumerate(csvs, 1):
        pq = c.with_suffix(".parquet")
        if pq.exists():
            skip += 1
            continue
        try:
            df = pd.read_csv(c, index_col=0, parse_dates=True)
            if df.empty:
                fail += 1
                print(f"  ⚠️ {c.name} 为空，跳过")
                continue
            df.to_parquet(pq)
            if not args.keep_csv:
                c.unlink()
            ok += 1
            if i % 50 == 0:
                print(f"  … 已处理 {i}/{len(csvs)}")
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  ❌ {c.name}: {type(exc).__name__}: {exc}")

    print(f"\n转换完成：成功 {ok}  跳过(已存在) {skip}  失败 {fail}")
    print(f"目录：{d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
