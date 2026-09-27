# -*- coding: utf-8 -*-
"""第八轮验证：并发治理 + 均线通用周期 + 诊断可见化"""
import sys, threading, time

sys.path.insert(0, ".")

from app.data_provider import (  # noqa: E402
    _quote_cache,
    fetch_history,
    get_quote,
    recent_source_errors,
)

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond: ok += 1; print(f"[PASS] {name}")
    else: fail += 1; print(f"[FAIL] {name} {detail}")

# 1) 通用周期均线（后端 API 层 regex）——直接调 indicators 的依赖函数确认
from app.strategies import indicators as ind  # noqa: E402
import pandas as pd, numpy as np  # noqa: E402
s = pd.Series(np.linspace(10, 20, 120))
check("ind.sma(s, 5) 通用周期", len(ind.sma(s, 5)) == 120)
check("ind.ema(s, 7) 通用周期", len(ind.ema(s, 7)) == 120)

# 2) single-flight：并发 6 路同一 symbol+interval，全部应成功且结果一致
results, errs = [], []
def worker():
    try:
        df, src = fetch_history("SPY", start="2026-06-01", interval="1d")
        results.append((len(df), src))
    except Exception as e:
        errs.append(str(e))
threads = [threading.Thread(target=worker) for _ in range(6)]
[t.start() for t in threads]; [t.join() for t in threads]
check("并发 6 路无异常", not errs, str(errs[:2]))
check("并发结果一致", len({r[0] for r in results}) == 1, str(results))

# 3) 报价短缓存：第二次调用应命中缓存（时间戳相同）
q1 = get_quote("AAPL")
t1 = q1.get("ts")
q2 = get_quote("AAPL")
check("get_quote 命中 20s 缓存", q2 is q1 or (q2.get("ts") == t1 and "AAPL" in _quote_cache))

# 4) recent_source_errors 可调用
check("recent_source_errors()", isinstance(recent_source_errors(), dict))

# 5) 实网：GOOGL / DELL（用户报告失败的标的）——链路加固后应稳定返回非合成数据
for sym in ("GOOGL", "DELL"):
    try:
        df, src = fetch_history(sym, start="2026-06-01", interval="1d")
        check(f"{sym} 日线 src={src} rows={len(df)}", len(df) > 20 and src != "synthetic")
    except Exception as e:
        check(f"{sym} 日线", False, repr(e))
    try:
        q = get_quote(sym)
        check(f"{sym} 报价 price={q.get('price')}", q.get("price", 0) > 0)
    except Exception as e:
        check(f"{sym} 报价", False, repr(e))

print(f"\n== 第八轮验证：{ok} 通过 / {fail} 失败 ==")
sys.exit(1 if fail else 0)
