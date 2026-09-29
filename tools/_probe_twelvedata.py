"""TwelveData 数据路径探针（人工诊断用，会消耗 1~2 个 credit）。

验证三件事：
  1. **日期口径**：aware(纽约) -> 恰好一次归一化 -> NY naive 00:00（不得退到前一天 20:00）；
  2. **区间裁剪**：日线分支 outputsize=5000 不认 end，必须本地裁到 [start, end]；
  3. **跨源交叉验证**：与 yfinance 逐日比 close —— 除权日之后应分毫不差，
     除权日之前差一个股息额（yfinance auto_adjust 复权所致，属预期）。

用法：`cd backend && ./.venv/Scripts/python.exe ../tools/_probe_twelvedata.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import data_provider as dp  # noqa: E402
from app import twelvedata as td  # noqa: E402
from app.brokers import register_data_providers  # noqa: E402

register_data_providers()  # 注册 twelvedata 等历史数据源
print("registered providers:", sorted(dp._history_providers.keys()))

p = td.pool()
print("pool has_key:", p.has_key(), "| keys:", len(p.status().get("keys", [])))

df, src = dp.fetch_history("MSFT", "2026-08-01", "2026-09-10", "1d", use_cache=False, prefer="twelvedata")
print("source:", src, "| bars:", len(df), "| 请求区间 2026-08-01 .. 2026-09-10")
if len(df):
    print("index dtype:", df.index.dtype, "| tz:", getattr(df.index, "tz", None))
    print("first 3:", [str(x) for x in df.index[:3]])
    print("last 3 :", [str(x) for x in df.index[-3:]])
    times = sorted({str(x).split(" ")[1] for x in df.index})
    print("distinct times-of-day:", times)
    ok = times == ["00:00:00"]
    print("RESULT:", "OK 全部为 00:00:00" if ok else "FAIL 存在非 00:00 的时刻")
    print("closes:", [round(float(c), 2) for c in df["close"].tail(5)])

# 交叉验证：同区间用 yfinance 拉一遍，逐日比 close（不同源应当一致）
try:
    yf_df, yf_src = dp.fetch_history("MSFT", "2026-08-01", "2026-09-10", "1d",
                                     use_cache=False, prefer="yfinance")
    common = df.index.intersection(yf_df.index)
    diffs = (df.loc[common, "close"] - yf_df.loc[common, "close"]).abs()
    print(f"\n交叉验证 vs {yf_src}: 重叠 {len(common)} 日, 最大 close 偏差 {diffs.max():.4f}")
    rel = (diffs / yf_df.loc[common, "close"]).max() * 100
    print(f"最大相对偏差 {rel:.4f}%  （yfinance 用 auto_adjust=True 复权，TwelveData 是原始价）")
    for d in list(common)[:2] + list(common)[-3:]:
        print(f"  {str(d)[:10]}  td={df.loc[d,'close']:.2f}  yf={yf_df.loc[d,'close']:.2f}"
              f"  diff={df.loc[d,'close']-yf_df.loc[d,'close']:+.2f}")
    # 对齐判据：**除权日之后的 bar 必须逐日分毫不差**（偏差 0 才说明日期没错位）；
    # 除权日之前的 bar 会差一个股息额 —— 那是 yfinance auto_adjust 复权所致，属预期。
    tail = diffs.iloc[-5:]
    print("最近 5 日逐日偏差:", [f"{v:.4f}" for v in tail])
    print("RESULT:", "OK 日期对齐（除权日之后分毫不差）"
          if float(tail.max()) < 0.01 else "FAIL 尾部偏差过大，疑似日期错位")
except Exception as exc:  # noqa: BLE001
    print("交叉验证跳过：", type(exc).__name__, exc)
