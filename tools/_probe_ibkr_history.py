"""
IBKR 历史数据灌库可行性实测（人工跑，勿接入生产）

目的
----
回答一个问题：**用 IBKR 拉 SP500 全量 2 年日线，到底要多久？会不会撞 pacing？**

做法
----
复用项目自己的 `brokers.ibkr.IBKRBroker.history()`（已含分页 / 时区 / 限流），
只拉前 N 只标的，统计：
  - 每只耗时、成功率
  - 总耗时、外推到 503 只的预计时间
  - pacing / BOM 类错误出现次数
  - 顺带与 yfinance 逐日对比 close（可选，--cross）

用法
----
cd backend
.venv/Scripts/python.exe ../tools/_probe_ibkr_history.py --n 20 --years 2
.venv/Scripts/python.exe ../tools/_probe_ibkr_history.py --n 20 --years 2 --cross

⚠️ 需要 TWS / Gateway 已启动且 API 端口已开（实盘 TWS 默认 7496）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SP500 = ROOT / "backend" / "app" / "markets" / "sp500.json"


def load_symbols(n: int) -> list[str]:
    d = json.loads(SP500.read_text(encoding="utf-8"))
    syms = [c["symbol"] for c in d["constituents"]]
    return syms[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="测试标的数量")
    ap.add_argument("--years", type=float, default=2.0, help="回溯年数")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7496, help="TWS 实盘 7496 / 纸面 7497")
    ap.add_argument("--client-id", type=int, default=91)
    ap.add_argument("--cross", action="store_true", help="与 yfinance 逐日对比 close")
    args = ap.parse_args()

    from app.brokers.ibkr import IBKRBroker  # noqa: PLC0415

    symbols = load_symbols(args.n)
    print(f"=== IBKR 历史数据实测 ===")
    print(f"目标: {len(symbols)} 只 × {args.years} 年日线  @ {args.host}:{args.port}")
    print(f"标的: {', '.join(symbols)}\n")

    broker = IBKRBroker(host=args.host, port=args.port, client_id=args.client_id)
    ok, msg = broker.connect()
    print(f"连接: {ok}  {msg}")
    if not ok:
        print("❌ 连接失败 —— 请确认 TWS 已启动、API 端口已启用、"
              "且 TWS 的「信任的 IP」含 127.0.0.1")
        return 2

    start_day = (time.strftime("%Y-%m-%d")
                 if args.years <= 0
                 else time.strftime("%Y-%m-%d",
                                    time.localtime(time.time() - args.years * 365.25 * 86400)))

    per_symbol: list[dict] = []
    t_total0 = time.perf_counter()

    for i, sym in enumerate(symbols, 1):
        t0 = time.perf_counter()
        err = ""
        rows = 0
        try:
            df = broker.history(sym, start=start_day, interval="1d")
            rows = 0 if df is None else len(df)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        dt = time.perf_counter() - t0
        per_symbol.append({"symbol": sym, "sec": dt, "rows": rows, "error": err})
        flag = "✅" if rows > 0 else "❌"
        print(f"[{i:>3}/{len(symbols)}] {flag} {sym:<6} {dt:>6.2f}s  {rows:>5} 根"
              + (f"  ERR {err[:70]}" if err else ""))
        if args.cross and rows > 0:
            _cross_check(sym, df, start_day)

    total = time.perf_counter() - t_total0
    good = [r for r in per_symbol if r["rows"] > 0]
    bad = [r for r in per_symbol if r["rows"] == 0]

    print("\n=== 汇总 ===")
    print(f"成功 {len(good)}/{len(symbols)}，失败 {len(bad)}")
    if good:
        secs = sorted(r["sec"] for r in good)
        avg = sum(secs) / len(secs)
        p50 = secs[len(secs) // 2]
        print(f"单只耗时: 平均 {avg:.2f}s  中位 {p50:.2f}s  最快 {secs[0]:.2f}s  最慢 {secs[-1]:.2f}s")
        print(f"总耗时: {total:.1f}s")
        print(f"\n外推到 503 只: 约 {total / len(symbols) * 503 / 60:.1f} 分钟"
              f"（线性外推，实际因 pacing 可能更长）")

    print("\n--- pacing / 熔断状态 ---")
    try:
        print(json.dumps(broker._pacer.snapshot(), ensure_ascii=False, indent=2))
    except Exception:  # noqa: BLE001
        pass

    if bad:
        print("\n--- 失败明细 ---")
        for r in bad:
            print(f"  {r['symbol']}: {r['error'][:120]}")

    broker.disconnect()
    return 0


def _cross_check(sym: str, df, start_day: str) -> None:
    """与 yfinance 逐日比 close（除权日之后应分毫不差）。"""
    try:
        import yfinance as yf  # noqa: PLC0415
        y = yf.download(sym, start=start_day, progress=False, auto_adjust=True)
        if y is None or y.empty:
            return
        yc = y["Close"]
        if hasattr(yc, "columns"):
            yc = yc.iloc[:, 0]
        ib_close = df["close"]
        ib_idx = ib_close.index.tz_localize(None).normalize() if ib_close.index.tz is not None else ib_close.index
        j = yc.copy()
        j.index = j.index.tz_localize(None).normalize() if j.index.tz is not None else j.index
        both = ib_close.copy()
        both.index = ib_idx
        merged = both.to_frame("ib").join(j.to_frame("yf"), how="inner").dropna()
        if merged.empty:
            print(f"        交叉验证 {sym}: 无重叠日期")
            return
        diff = (merged["ib"] - merged["yf"]).abs()
        exact = (diff < 0.005).sum()
        print(f"        交叉验证 {sym}: 重叠 {len(merged)} 天，"
              f"完全一致 {exact} 天，最大偏差 {diff.max():.4f}")
    except Exception as exc:  # noqa: BLE001
        print(f"        交叉验证 {sym} 失败: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
