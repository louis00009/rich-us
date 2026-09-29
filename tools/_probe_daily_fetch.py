"""实测：全量 S&P 500 拉 1 年日线的耗时与覆盖率。

用户已选「跟着行情一起每次刷新」，但这个选择的代价必须先量化 ——
如果 1 年日线要 3 分钟，就不能塞进 10 分钟 TTL 的行情刷新里（会一直有线程在跑）。
本脚本给出真实数字，架构据此决定。

用法：
    cd backend
    .venv/Scripts/python.exe ../tools/_probe_daily_fetch.py [样本数]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("QD_HOME", str(BACKEND / "runtime"))


def main() -> None:
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 503
    from app.rankings import constituents

    syms = [c["symbol"] for c in constituents()["constituents"]]
    syms = syms[:sample]
    print(f"标的数：{len(syms)}")

    import yfinance as yf

    # 与 rankings._fetch_all_quotes 同样的分块策略，只是 period 换成 1y
    chunk = 100
    chunks = [syms[i: i + chunk] for i in range(0, len(syms), chunk)]
    t0 = time.time()
    got = 0
    rows_total = 0
    for i, c in enumerate(chunks):
        tc = time.time()
        try:
            df = yf.download(
                tickers=" ".join(c), period="1y", interval="1d",
                group_by="ticker", threads=False, progress=False, auto_adjust=False,
            )
            n = 0
            for s in c:
                try:
                    sub = df if len(c) == 1 else df[s]
                    sub = sub.dropna(subset=["Close"])
                    if sub.empty:
                        continue
                    n += 1
                    rows_total += len(sub)
                except Exception:  # noqa: BLE001
                    continue
            got += n
            print(f"  块 {i + 1}/{len(chunks)}: {n}/{len(c)} 只, {time.time() - tc:.1f}s")
        except Exception as exc:  # noqa: BLE001
            print(f"  块 {i + 1}/{len(chunks)}: 失败 {type(exc).__name__}: {exc}")

    dt = time.time() - t0
    print(f"\n总计 {got}/{len(syms)} 只，耗时 {dt:.1f}s，平均每只 {dt / max(1, len(syms)) * 1000:.0f}ms")
    if got:
        print(f"平均每只 {rows_total / got:.0f} 个交易日")

    # 序列化体积估算（决定快照文件大不大）
    payload = json.dumps({"x": [[1.0] * 8] * rows_total})
    print(f"若只存算好的指标（非原始日线），快照约 {len(payload) / 1024:.0f} KB 量级")


if __name__ == "__main__":
    main()
