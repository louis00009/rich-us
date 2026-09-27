"""轻量 API 限流（进程内固定窗口计数）
=====================================

背景（审查 P3-13）
------------------
平台默认只监听 127.0.0.1，但**设计上就是要接外部 AI Agent**（持 token 调 REST）。
部分端点很重：`alerts/scan` 全量扫描、`backtest/run` 回测、`market/rankings`
全市场刷新。没有节流时，一个循环调用的 Agent 就能把工作线程与数据库连接池打满，
拖垮全站 —— 这与 TODO 里记录过的「连接池耗尽 → 全站 500」是同一类事故。

设计取舍
--------
* **进程内固定窗口计数**：本地单机单进程，无需 Redis / 多实例一致性，零依赖。
* **分级限流**：只对「写 / 重」端点设严格上限，普通读端点给宽松上限，
  避免误伤正常的前端轮询。
* **超限返回 429 + Retry-After**，而不是静默丢弃或排队 —— 让调用方（尤其 AI Agent）
  能明确知道自己被限流了，而不是拿到一个含义不明的错误。
* 字典**有界**（`_MAX_KEYS`），防止被大量不同 IP / 键撑爆内存。
* 可用环境变量 `QD_RATE_LIMIT=0` 整体关闭（自检 / 压测时用）。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

_lock = threading.Lock()
_buckets: dict[tuple[str, str], list[float]] = {}
_MAX_KEYS = 4096


@dataclass(frozen=True)
class Rule:
    """limit 次 / window 秒。"""

    limit: int
    window: float


# 端点前缀 → 规则（按顺序匹配，先命中先用）
RULES: tuple[tuple[str, Rule], ...] = (
    ("/api/backtest/optimize", Rule(10, 60)),        # 网格寻优：最重
    ("/api/backtest/compare", Rule(20, 60)),         # 多策略并行回测
    ("/api/backtest/run", Rule(30, 60)),
    ("/api/optimize/run", Rule(30, 60)),
    ("/api/alerts/scan", Rule(20, 60)),              # 全量扫描
    ("/api/market/rankings", Rule(60, 60)),          # 全市场刷新
    ("/api/ai/analyze", Rule(60, 60)),
    ("/api/ai/chat", Rule(60, 60)),
    ("/api/trading/order", Rule(120, 60)),           # 下单：防脚本刷单
)
DEFAULT = Rule(900, 60)


def enabled() -> bool:
    return os.environ.get("QD_RATE_LIMIT", "1").strip().lower() not in {"0", "false", "no", "off"}


def rule_for(path: str) -> Rule:
    for prefix, r in RULES:
        if path.startswith(prefix):
            return r
    return DEFAULT


def _max_window() -> float:
    return max([r.window for _, r in RULES] + [DEFAULT.window])


def hit(key: str, path: str) -> tuple[bool, int]:
    """记录一次请求。

    返回 `(是否放行, 超限时建议等待的秒数)`；放行时第二个值为 0。
    """
    rule = rule_for(path)
    now = time.time()
    bucket_key = (key, f"{rule.limit}/{rule.window:g}")
    with _lock:
        if len(_buckets) >= _MAX_KEYS:
            # 有界化：先清过期窗口；仍超限则整体重置（本地单机，代价可接受）
            horizon = _max_window()
            for k in [k for k, v in _buckets.items() if not v or now - v[-1] > horizon]:
                _buckets.pop(k, None)
            if len(_buckets) >= _MAX_KEYS:
                _buckets.clear()
        hits = [t for t in _buckets.get(bucket_key, []) if now - t < rule.window]
        if len(hits) >= rule.limit:
            wait = int(rule.window - (now - hits[0])) + 1
            _buckets[bucket_key] = hits
            return False, max(wait, 1)
        hits.append(now)
        _buckets[bucket_key] = hits
        return True, 0


def reset() -> None:
    """清空计数（自检 / 测试用）。"""
    with _lock:
        _buckets.clear()
