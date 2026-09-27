"""B0 前置验证：令牌桶限流器 + 熔断器。"""
from __future__ import annotations

import sys
import threading
import time

sys.path.insert(0, ".")

from app.brokers.pacing import DEFAULT_BURST, DEFAULT_RATE, CircuitBreaker, Pacer

PASS = 0
FAIL = 0


def check(ok: bool, label: str, extra: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {label}" + (f" | {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" | {extra}" if extra else ""))


print("=" * 78)
print("B0 令牌桶限流器 / 熔断器 验证")
print("=" * 78)

# ---------------------------------------------------------------- 1 突发容量
print("\n[1] 突发容量：初始应可瞬时拿走 burst 个令牌")
p = Pacer(rate=42.0, burst=24, max_wait=2.0)
t0 = time.perf_counter()
ok = all(p.try_acquire() for _ in range(24))
dt = (time.perf_counter() - t0) * 1000
check(ok, "24 次 try_acquire 全部成功（= burst）", f"耗时 {dt:.2f} ms")
check(p.try_acquire() is False, "第 25 次 try_acquire 应失败（令牌耗尽）")
check(p.stats.allowed == 24, "allowed 计数 = 24", f"实际 {p.stats.allowed}")
check(p.stats.rejected == 1, "rejected 计数 = 1", f"实际 {p.stats.rejected}")

# ---------------------------------------------------------------- 2 稳态速率
print("\n[2] 稳态速率：令牌耗尽后以 rate 补充，N 次 acquire 应耗时约 (N-burst)/rate")
p2 = Pacer(rate=20.0, burst=5, max_wait=10.0)
# 先耗尽
for _ in range(5):
    p2.try_acquire()
N = 45
t0 = time.perf_counter()
got = sum(1 for _ in range(N) if p2.acquire(n=1, max_wait=10.0))
el = time.perf_counter() - t0
expect = N / 20.0
check(got == N, f"{N} 次 acquire 全部拿到令牌", f"got={got}")
check(abs(el - expect) < expect * 0.35 + 0.05,
      f"耗时 {el:.3f}s 接近理论 {expect:.3f}s（±35%）")
check(p2.stats.waited > 0, "等待计数 > 0（说明确实等待过）", f"waited={p2.stats.waited}")

# 反推实际速率
p3 = Pacer(rate=50.0, burst=10, max_wait=10.0)
for _ in range(10):
    p3.try_acquire()
t0 = time.perf_counter()
for _ in range(60):
    p3.acquire(n=1, max_wait=10.0)
el3 = time.perf_counter() - t0
eff = 60 / el3
check(30.0 <= eff <= 70.0, "反推有效速率落在 [30,70] msg/s", f"实际 {eff:.1f} msg/s")

# ---------------------------------------------------------------- 3 max_wait 边界
print("\n[3] max_wait 边界：判定无法满足时快速失败；能满足时如实等待")
p4 = Pacer(rate=1.0, burst=1, max_wait=0.2)
p4.try_acquire()          # 耗尽
t0 = time.perf_counter()
r = p4.acquire(n=1, max_wait=0.2)
el4 = time.perf_counter() - t0
check(r is False, "rate=1/s + 已耗尽 + max_wait=0.2s → 返回 False")
check(el4 < 0.08, "快速失败（不等满 max_wait 才放弃）", f"实测 {el4*1000:.1f} ms")

p4b = Pacer(rate=1.0, burst=1, max_wait=3.0)
p4b.try_acquire()
t0 = time.perf_counter()
r2 = p4b.acquire(n=1, max_wait=3.0)
el4b = time.perf_counter() - t0
check(r2 is True, "同样的桶，max_wait 放宽到 3s → 成功")
check(0.7 <= el4b <= 1.8, "实际等待约 1/rate = 1.0s", f"实测 {el4b:.3f}s")

# ---------------------------------------------------------------- 4 批量取令牌
print("\n[4] 批量取令牌：n>1 时行为正确")
p5 = Pacer(rate=100.0, burst=10, max_wait=0.5)
check(p5.try_acquire(n=10) is True, "一次性取 10 个令牌成功")
check(p5.try_acquire(n=1) is False, "令牌已空，再取 1 个失败")
t0 = time.perf_counter()
r5 = p5.acquire(n=10, max_wait=0.5)
el5 = time.perf_counter() - t0
check(r5 is True, "100/s 补 10 个令牌约需 0.1s < max_wait=0.5s → 成功")
check(0.05 <= el5 <= 0.4, "等待时长接近 10/rate = 0.1s", f"实测 {el5*1000:.0f} ms")
check(p5.acquire(n=10, max_wait=0.02) is False, "max_wait=0.02s 补不满 10 个 → 快速失败 False")

# ---------------------------------------------------------------- 5 并发安全
print("\n[5] 并发安全：20 线程 × 20 次，总放行数不得超过 burst + rate*时长")
p6 = Pacer(rate=100.0, burst=20, max_wait=5.0)
allowed = []
lock = threading.Lock()


def worker():
    local = 0
    for _ in range(20):
        if p6.try_acquire():
            local += 1
    with lock:
        allowed.append(local)


t0 = time.perf_counter()
ths = [threading.Thread(target=worker) for _ in range(20)]
for t in ths:
    t.start()
for t in ths:
    t.join()
el6 = time.perf_counter() - t0
total = sum(allowed)
ceiling = 20 + 100.0 * (el6 + 0.05)
check(total <= ceiling, "并发放行总量未突破桶容量+补充量",
      f"放行 {total} <= 上限 {ceiling:.0f}（耗时 {el6*1000:.0f} ms）")
check(p6.stats.allowed == total, "stats.allowed 与各线程计数之和一致",
      f"{p6.stats.allowed} vs {total}")

# ---------------------------------------------------------------- 6 统计字段
print("\n[6] 统计字段完整性与 utilisation 计算")
snap = p6.snapshot()
need = {"allowed", "waited", "rejected", "avg_wait_ms", "peak_per_sec",
        "configured_rate_per_sec", "burst", "ib_hard_limit_per_sec",
        "utilisation_pct", "tokens_free"}
check(need <= set(snap), "快照包含全部约定字段", f"缺 {need - set(snap)}")
check(snap["ib_hard_limit_per_sec"] == 50, "硬限声明为 50 msg/s")
check(snap["utilisation_pct"] <= 100.0, "utilisation_pct 不超过 100",
      f"{snap['utilisation_pct']}%")

p7 = Pacer(rate=42.0, burst=24, max_wait=0.0)
for _ in range(24):
    p7.try_acquire()
snap7 = p7.snapshot()
check(snap7["tokens_free"] < 1.0, "耗尽后 tokens_free 接近 0", f"{snap7['tokens_free']}")

# ---------------------------------------------------------------- 7 熔断器状态机
print("\n[7] 熔断器：CLOSED → OPEN → HALF_OPEN → CLOSED")
cb = CircuitBreaker(fail_threshold=5, cooldown=0.5, half_open_trials=2)
check(cb.state == CircuitBreaker.CLOSED, "初始 CLOSED")
check(cb.allow() is True, "CLOSED 时放行")
for i in range(4):
    cb.record_failure(f"err{i}")
check(cb.state == CircuitBreaker.CLOSED, "4 次失败（< 阈值 5）仍 CLOSED", f"fails={cb._fails}")
cb.record_failure("err4")
check(cb.state == CircuitBreaker.OPEN, "第 5 次失败 → OPEN")
check(cb.allow() is False, "OPEN 时快速失败（不放行）")
check(cb.trip_count == 1, "熔断计数 = 1")

time.sleep(0.55)
check(cb.state == CircuitBreaker.HALF_OPEN, "冷却 0.5s 后 → HALF_OPEN")
check(cb.allow() is True, "HALF_OPEN 第 1 次试探放行")
check(cb.allow() is True, "HALF_OPEN 第 2 次试探放行")
check(cb.allow() is False, "HALF_OPEN 试探配额用尽 → 不放行")

cb.record_success()
check(cb.state == CircuitBreaker.CLOSED, "试探成功 → 回到 CLOSED")
check(cb._fails == 0, "失败计数已归零")

# HALF_OPEN 中失败应立刻重新 OPEN
cb2 = CircuitBreaker(fail_threshold=2, cooldown=0.3, half_open_trials=2)
cb2.record_failure("a")
cb2.record_failure("b")
check(cb2.state == CircuitBreaker.OPEN, "连续 2 次失败 → OPEN")
time.sleep(0.35)
check(cb2.state == CircuitBreaker.HALF_OPEN, "冷却后 HALF_OPEN")
cb2.record_failure("probe failed")
check(cb2.state == CircuitBreaker.OPEN, "HALF_OPEN 中失败 → 立即回 OPEN")
check(cb2.trip_count == 2, "熔断次数累加为 2", f"{cb2.trip_count}")

snap_cb = cb2.snapshot()
check({"state", "consecutive_failures", "trip_count", "cooldown_sec",
       "last_error", "recent_trips"} <= set(snap_cb), "熔断快照字段完整")
check(len(snap_cb["recent_trips"]) >= 1, "记录最近熔断事件", f"{len(snap_cb['recent_trips'])} 条")

cb2.reset()
check(cb2.state == CircuitBreaker.CLOSED and cb2._fails == 0, "reset() 复位")

# ---------------------------------------------------------------- 8 默认值
print("\n[8] 默认参数：留出 IB 50 msg/s 硬限的余量")
check(DEFAULT_RATE < 50, f"默认速率 {DEFAULT_RATE} < 50")
check(DEFAULT_RATE >= 30, f"默认速率 {DEFAULT_RATE} 不至于过低")
check(DEFAULT_BURST >= 10, f"默认突发 {DEFAULT_BURST}")
pd = Pacer()
check(pd.rate == DEFAULT_RATE and pd.burst == float(DEFAULT_BURST), "Pacer() 使用默认参数")

print("\n" + "=" * 78)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
