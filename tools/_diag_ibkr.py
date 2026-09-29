"""
IBKR 连接与历史数据诊断（最小化，显示 IB 原始错误码）

用途：当 history() 静默返回空时，用它看 IB 到底报了什么错。
       IB 的错误码是判断根因的唯一可靠依据。

用法：
  cd backend
  .venv/Scripts/python.exe ../tools/_diag_ibkr.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

ERRORS: list[str] = []

CODE_MEANING = {
    1100: "与交易所连接断开（IB 侧网络问题）",
    1101: "与交易所连接恢复",
    1102: "与交易所连接恢复（数据丢失）",
    2103: "行情农场断开",
    2104: "行情农场恢复",
    2105: "HMDS 数据农场断开",
    2106: "HMDS 数据农场恢复",
    2107: "HMDS 数据农场不活跃",
    2108: "HMDS 数据农场连接正常",
    162: "历史数据请求被 pacing 限制（每秒/每分钟请求过多）",
    165: "历史数据请求被 pacing 限制（重复请求相同数据）",
    200: "无该合约的交易权限 / 合约定义不完整",
    354: "无该市场数据的订阅权限",
    10167: "请求的历史数据需要额外订阅（延迟数据不可用）",
    10197: "无实时数据权限，已返回延迟数据",
    2157: "证券定义验证警告",
    2158: "证券定义验证警告（合约可能不完整）",
}


def on_error(reqId, errorCode, errorString, *a, **kw):
    meaning = CODE_MEANING.get(errorCode, "")
    line = f"  [ERR] reqId={reqId} code={errorCode} {errorString}" + (f"  ← {meaning}" if meaning else "")
    print(line, flush=True)
    ERRORS.append(line)


def main() -> int:
    try:
        import ib_async
    except ImportError:
        print("❌ 未安装 ib_async")
        return 2

    port = 7496
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    ib = ib_async.IB()
    ib.errorEvent += on_error

    print(f"=== IBKR 诊断 @ 127.0.0.1:{port} ===\n")
    print("[1] 连接…")
    try:
        ib.connect("127.0.0.1", port, clientId=93, timeout=15, readonly=True)
    except Exception as exc:
        print(f"❌ 连接失败：{type(exc).__name__}: {exc}")
        return 2

    print(f"    isConnected = {ib.isConnected()}")
    print(f"    managedAccounts = {ib.managedAccounts()}")
    try:
        print(f"    serverVersion = {ib.client.serverVersion()}")
    except Exception:  # noqa: BLE001
        pass

    print("\n[2] 设定延迟行情（免费档）…")
    try:
        ib.reqMarketDataType(3)
        print("    reqMarketDataType(3) OK")
    except Exception as exc:  # noqa: BLE001
        print(f"    失败：{exc}")

    print("\n[3] 合约解析 MMM …")
    from ib_async import Stock
    c = Stock("MMM", "SMART", "USD")
    try:
        q = ib.qualifyContracts(c)
        print(f"    conId = {c.conId}  primaryExchange = {c.primaryExchange}")
        if not c.conId:
            print("    ⚠️ conId=0 —— 合约未解析成功")
    except Exception as exc:  # noqa: BLE001
        print(f"    失败：{type(exc).__name__}: {exc}")

    print("\n[4] 请求历史数据（MMM, 1 个月日线）…")
    t0 = time.perf_counter()
    try:
        bars = ib.reqHistoricalData(
            c, endDateTime="", durationStr="1 M", barSizeSetting="1 day",
            whatToShow="TRADES", useRTH=True, formatDate=1,
        )
        dt = time.perf_counter() - t0
        n = len(bars) if bars else 0
        print(f"    返回 {n} 根，耗时 {dt:.2f}s")
        if bars:
            print(f"    最早 {bars[0].date}  最新 {bars[-1].date}  收盘 {bars[-1].close}")
    except Exception as exc:  # noqa: BLE001
        print(f"    异常：{type(exc).__name__}: {exc}")

    print("\n[5] 对比请求 2 年日线（更长的请求更易触发 pacing）…")
    t0 = time.perf_counter()
    try:
        bars2 = ib.reqHistoricalData(
            c, endDateTime="", durationStr="2 Y", barSizeSetting="1 day",
            whatToShow="TRADES", useRTH=True, formatDate=1,
        )
        dt = time.perf_counter() - t0
        n2 = len(bars2) if bars2 else 0
        print(f"    返回 {n2} 根，耗时 {dt:.2f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"    异常：{type(exc).__name__}: {exc}")

    print("\n=== 捕获到的 IB 错误 ===")
    if ERRORS:
        for e in ERRORS:
            print(e)
    else:
        print("  （无错误 —— 但可能请求本身已被静默处理）")

    ib.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
