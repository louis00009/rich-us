"""
IBKR 历史数据灌库器（加固版）
================================
解决 `_probe_ibkr_history.py` 实测暴露的问题：503 只只跑到第 38 只就断连，
后续 465 只**静默返回空**（`error=""`），无法判断失败原因、无法续跑。

四个加固点
----------
1. **断点续传**：每只标的一拉完就追加写 JSONL，重跑自动跳过已完成的标的。
2. **自动重连**：每只标的前检查 `broker.connected`，断开则重连（带退避重试）。
3. **失败重试**：单只失败重试 N 次，间隔递增；仍失败则如实记录。
4. **真实错误**：不走 `history()` 的静默空返回，失败时记录错误类型与消息。

用法
----
cd backend
# 灌全量 SP500（可中断，重跑自动续）
.venv/Scripts/python.exe ../tools/ibkr_ingest.py --years 2

# 只灌前 20 只（快速验证）
.venv/Scripts/python.exe ../tools/ibkr_ingest.py --n 20 --years 2

# 后续增量更新（只补最近 30 天）
.venv/Scripts/python.exe ../tools/ibkr_ingest.py --years 0.08

# 查看当前进度
.venv/Scripts/python.exe ../tools/ibkr_ingest.py --status

产物
----
runtime/ibkr_bars.jsonl   每行 {symbol, start, fetched_at, rows, error}
runtime/ibkr_bars/        每个标的的 parquet（或 csv 回落）
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
OUT_DIR = ROOT / "backend" / "runtime" / "ibkr_bars"
STATE = ROOT / "backend" / "runtime" / "ibkr_bars.jsonl"


def log(msg: str) -> None:
    print(msg, flush=True)          # 关键：flush=True 让后台日志实时可见


def load_symbols(n: int | None) -> list[str]:
    d = json.loads(SP500.read_text(encoding="utf-8"))
    syms = [c["symbol"] for c in d["constituents"]]
    return syms[:n] if n else syms


def load_done() -> dict[str, dict]:
    """读已完成的标的（只认成功、且行数 > 0 的）。"""
    done: dict[str, dict] = {}
    if not STATE.exists():
        return done
    for line in STATE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("rows", 0) > 0:
            done[rec["symbol"]] = rec
    return done


def append_state(rec: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def save_bars(symbol: str, df) -> str:
    """落盘单个标的。优先 parquet，缺依赖时回落 csv。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("/", "_").replace("-", "_")
    try:
        p = OUT_DIR / f"{safe}.parquet"
        df.to_parquet(p)
        return str(p.name)
    except Exception:  # noqa: BLE001 —— pyarrow 缺失等情况回落 csv
        p = OUT_DIR / f"{safe}.csv"
        df.to_csv(p)
        return str(p.name)


def _farm_healthy(broker, *, settle: float = 2.0) -> bool:
    """探测数据农场是否可用（用一次轻量历史请求探活）。

    ⚠️ 实测教训：`broker.connected == True` **不代表数据农场是通的**。
    TWS 会持续报 2103/2105（farm connection broken）而 TCP 连接依然活着，
    此时历史请求会静默返回空。必须用真实请求探活。
    """
    try:
        df = broker.history("MMM", start=_probe_start(), interval="1d")
        return df is not None and len(df) > 0
    except Exception:  # noqa: BLE001
        return False


def _probe_start() -> str:
    """探活用的短区间起始日（约 1 个月，够快又不至于空）。"""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - 35 * 86400))


def ensure_connected(broker, *, attempts: int = 6, base_wait: float = 6.0) -> bool:
    """确保「连接 + 数据农场」都可用。

    实测：农场断连的恢复周期可达十几秒，因此重试间隔要足够长，
    且必须用**真实请求探活**而不是只看 TCP 连接。
    """
    for i in range(attempts):
        # TCP 连接活着不代表农场通 —— 两者都要查
        try:
            if broker.connected and _farm_healthy(broker):
                return True
        except Exception:  # noqa: BLE001
            pass

        wait = base_wait * (i + 1)
        if i:
            log(f"    · 数据农场不可用，等待 {wait:.0f}s 后重试（{i + 1}/{attempts}）…")
        time.sleep(1.0 if not i else wait)

        try:
            if not broker.connected:
                try:
                    broker.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                ok, msg = broker.connect()
                if ok:
                    log(f"    · 已重连：{msg}")
        except Exception as exc:  # noqa: BLE001
            log(f"    · 重连异常：{type(exc).__name__}: {exc}")
    return False


def cmd_status() -> int:
    done = load_done()
    total = len(load_symbols(None))
    failed = {}
    if STATE.exists():
        for line in STATE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("rows", 0) == 0:
                failed[rec["symbol"]] = rec.get("error", "")
    log(f"已完成（成功且有数据）: {len(done)}/{total}")
    log(f"最近一次失败记录数: {len(failed)}")
    if done:
        syms = sorted(done)
        log(f"样例: {', '.join(syms[:10])}{' …' if len(syms) > 10 else ''}")
    if failed:
        log("\n失败明细（前 15 条）:")
        for s, e in list(failed.items())[:15]:
            log(f"  {s}: {e or '(空错误)'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="只处理前 N 只")
    ap.add_argument("--years", type=float, default=2.0, help="回溯年数")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7496)
    ap.add_argument("--client-id", type=int, default=92)
    ap.add_argument("--retries", type=int, default=3, help="单只失败重试次数")
    ap.add_argument("--status", action="store_true", help="只看进度")
    args = ap.parse_args()

    if args.status:
        return cmd_status()

    from app.brokers.ibkr import IBKRBroker  # noqa: PLC0415

    symbols = load_symbols(args.n)
    done = load_done()
    pending = [s for s in symbols if s not in done]

    log("=== IBKR 历史数据灌库（加固版）===")
    log(f"目标 {len(symbols)} 只，已完成 {len(done)} 只，待拉取 {len(pending)} 只")

    if not pending:
        log("✅ 全部已完成，无需拉取。")
        return 0

    start_day = time.strftime(
        "%Y-%m-%d",
        time.localtime(time.time() - max(1, args.years) * 365.25 * 86400),
    )
    log(f"起始日期 {start_day}  @ {args.host}:{args.port}\n")

    broker = IBKRBroker(host=args.host, port=args.port, client_id=args.client_id)
    ok, msg = broker.connect()
    log(f"连接: {ok}  {msg}")
    if not ok:
        log("❌ 连接失败 —— 请确认 TWS 已启动且 API 端口已启用")
        return 2

    stats = {"ok": 0, "fail": 0, "reconnect": 0}
    t0 = time.perf_counter()

    for i, sym in enumerate(pending, 1):
        # ---- 1. 连接健康检查 + 自动重连 ----
        if not ensure_connected(broker):
            log(f"[{i}/{len(pending)}] ❌ {sym}  连接无法恢复，中止（已完成的会保留）")
            append_state({"symbol": sym, "rows": 0, "error": "连接无法恢复",
                          "fetched_at": _now()})
            break

        # ---- 2. 单只拉取（带重试 + 农场探活） ----
        df = None
        last_err = ""
        for attempt in range(1, args.retries + 1):
            try:
                df = broker.history(sym, start=start_day, interval="1d")
                if df is not None and len(df) > 0:
                    break
                last_err = f"返回空数据（第 {attempt} 次尝试）"
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
            if attempt < args.retries:
                # 空返回多半是农场断了 —— 先等农场恢复再重试，别急着打请求
                time.sleep(4.0 * attempt)
                if not _farm_healthy(broker):
                    if ensure_connected(broker):
                        stats["reconnect"] += 1
                        last_err += "（已重连后重试）"

        rows = 0 if df is None else len(df)

        # ---- 3. 落盘 + 记录 ----
        if rows > 0:
            saved = save_bars(sym, df)
            stats["ok"] += 1
            log(f"[{i}/{len(pending)}] ✅ {sym:<6} {rows:>5} 根 → {saved}")
            append_state({"symbol": sym, "rows": rows, "error": "",
                          "start": start_day, "fetched_at": _now()})
        else:
            stats["fail"] += 1
            log(f"[{i}/{len(pending)}] ❌ {sym:<6} 失败：{last_err}")
            append_state({"symbol": sym, "rows": 0, "error": last_err,
                          "start": start_day, "fetched_at": _now()})

    total = time.perf_counter() - t0
    log("\n=== 汇总 ===")
    log(f"成功 {stats['ok']}  失败 {stats['fail']}  重连 {stats['reconnect']} 次")
    log(f"本次耗时 {total / 60:.1f} 分钟")
    log(f"累计完成 {len(done) + stats['ok']}/{len(symbols)}")
    if stats["fail"]:
        log("\n提示：失败的标的未写入完成记录，直接重跑本脚本会自动续传。")

    try:
        broker.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return 0


def _now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat()


if __name__ == "__main__":
    sys.exit(main())
