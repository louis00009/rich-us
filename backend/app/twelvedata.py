"""TwelveData 多 Key 轮询池
=========================
TwelveData 免费档（basic）的硬约束（**实测** `/api_usage` 返回）：

    {"current_usage":3,"plan_limit":8,"daily_usage":3,"plan_daily_limit":800}

即 **8 credits / 分钟**、**800 credits / 天**。单账号根本喂不饱全量标的的补数需求，
所以这里支持配置**多个 Key 并轮询（round-robin）**，把每分钟额度按账号数叠加。

设计要点
--------
1. **密钥只以密文落库**：整个列表 JSON 交给 `state.set_secret`（Fernet）加密后
   存进 `AppSetting`，与 AI api_key / 券商口令同一套机制。明文不进日志、不进 API 响应。
2. **轮询**：游标 `_cursor` 每取一次前进一格，保证多 Key 均匀分摊，不会把某个账号打爆。
3. **双重限流**：每个 Key 各自维护「60 秒滑动窗口」与「当日计数」，
   任一超限即跳过该 Key 去试下一个 —— 限流器本身就是安全阀：
   额度耗尽时 `acquire()` 返回 None，调用方（降级链）自然落到下一个数据源，
   而不是阻塞或 429 雪崩。
4. **限流/失效要能自愈**：TwelveData 触发限流时**可能返回 HTTP 200 + body
   `{"code":429,...}`**（不只是 HTTP 429），所以必须同时检查 body。
   命中后该 Key 冷却 `_COOLDOWN_SEC` 秒，其余 Key 继续服务。
5. **.env 播种**：`TWELVEDATA_API_KEY` 若存在，首次加载时自动并入列表（只播一次，
   之后以界面里的增删为准），方便直接改 .env 就能用。

运行时计数（每分钟窗口、当日用量、最近错误）只在内存里，**不落库** ——
否则每次请求都要写一次 SQLite，会放大写锁压力。重启后计数归零，属可接受取舍。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from typing import Any

import httpx

from .config import settings as _app_settings
from .state import get_secret, set_secret

BASE = "https://api.twelvedata.com"

# 免费档实测额度；用户升级套餐后可在此调整（或后续做成可配置）。
PER_MIN_LIMIT = 8
PER_DAY_LIMIT = 800
_WINDOW_SEC = 60.0
_COOLDOWN_SEC = 62.0          # 限流后的冷却，略大于一个窗口，避免边界上反复撞墙
_COOLDOWN_AUTH_SEC = 900.0    # 密钥无效/无权限：冷却久一点，别拿坏 Key 空转
_MAX_KEYS = 50                # 上限：防止误粘贴一坨文本把列表撑爆

_SETTING_KEY = "twelvedata_keys"


def mask_key(key: str) -> str:
    """掩码：只留前 4 后 4，中间固定 ****。短 Key 只留前 2。"""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return k[:2] + "****"
    return f"{k[:4]}****{k[-4:]}"


def key_id(key: str) -> str:
    """由密钥本身派生稳定短 id（不暴露密钥内容），用于前端增删改定位。"""
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------
# 行情区间裁剪（纯函数，便于自检）
# ------------------------------------------------------------------
def clip_range(df: Any, start: str | None, end: str | None, interval: str) -> Any:
    """把 TwelveData 返回的行情裁剪到请求区间 [start, end]（按**纽约墙钟**）。

    为什么必须裁：日线/周线分支用 `outputsize=5000` 拉长历史且**不传 end**，
    返回的是「直到今天的全量」。若直接交给回测，指定 `end` 时会读到 end 之后的
    K 线 —— 未来函数（本项目铁律）。`start` 同理：不裁会让「请求 2025 起」
    拿到 2006 起的数据，与 yfinance / stooq 的行为不一致。

    约定：`end` 是**闭区间、含当日**（日线/周线取到 end 当日 23:59:59；
    日内取到 end 当日结束），与 stooq 的 d2 语义一致。
    索引须为 aware(纽约)（`_from_twelvedata` 已保证）；区间解析失败就原样返回，
    不因裁剪异常把整个数据源打挂。
    """
    import pandas as pd

    try:
        if start:
            df = df[df.index >= pd.Timestamp(start).tz_localize("America/New_York")]
        if end:
            hi = pd.Timestamp(end).tz_localize("America/New_York")
            hi = hi + (pd.Timedelta(hours=23, minutes=59, seconds=59)
                       if interval in ("1d", "1wk") else pd.Timedelta(days=1))
            df = df[df.index <= hi]
    except (TypeError, ValueError):
        return df
    return df


class _KeyState:
    """单个 Key 的静态配置 + 运行时计数。"""

    __slots__ = (
        "id", "label", "key", "enabled",
        "_window", "_day", "_day_count",
        "cooldown_until", "last_used", "last_error",
        "total_ok", "total_fail", "last_usage",
    )

    def __init__(self, kid: str, label: str, key: str, enabled: bool = True) -> None:
        self.id = kid
        self.label = label
        self.key = key
        self.enabled = enabled
        self._window: deque[float] = deque()
        self._day = time.strftime("%Y-%m-%d")
        self._day_count = 0
        self.cooldown_until = 0.0
        self.last_used = 0.0
        self.last_error = ""
        self.total_ok = 0
        self.total_fail = 0
        self.last_usage: dict[str, Any] = {}

    # ---- 额度 ----
    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self._day_count = 0

    def _roll_window(self) -> None:
        cut = time.time() - _WINDOW_SEC
        w = self._window
        while w and w[0] < cut:
            w.popleft()

    def available(self) -> tuple[bool, str]:
        """能否现在用这个 Key。返回 (可用, 不可用原因)。"""
        if not self.enabled:
            return False, "已停用"
        if time.time() < self.cooldown_until:
            return False, f"冷却中（{int(self.cooldown_until - time.time())}s）"
        self._roll_day()
        self._roll_window()
        if len(self._window) >= PER_MIN_LIMIT:
            return False, f"本分钟额度用尽（{PER_MIN_LIMIT}/min）"
        if self._day_count >= PER_DAY_LIMIT:
            return False, f"当日额度用尽（{PER_DAY_LIMIT}/day）"
        return True, ""

    def take(self) -> None:
        """占用一个额度。"""
        self._roll_day()
        self._roll_window()
        self._window.append(time.time())
        self._day_count += 1
        self.last_used = time.time()

    # ---- 状态上报 ----
    def snapshot(self) -> dict[str, Any]:
        self._roll_day()
        self._roll_window()
        now = time.time()
        return {
            "id": self.id,
            "label": self.label,
            "masked": mask_key(self.key),
            "enabled": self.enabled,
            "used_this_min": len(self._window),
            "per_min_limit": PER_MIN_LIMIT,
            "used_today": self._day_count,
            "per_day_limit": PER_DAY_LIMIT,
            "cooldown_sec": max(0, int(self.cooldown_until - now)),
            "last_used_sec": int(now - self.last_used) if self.last_used else None,
            "last_error": self.last_error,
            "total_ok": self.total_ok,
            "total_fail": self.total_fail,
            "last_usage": self.last_usage,
        }


class KeyPool:
    """多 Key 轮询池。线程安全（会被行情线程池并发调用）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._keys: list[_KeyState] = []
        self._cursor = 0
        self._loaded = False
        self._seeded_env = False

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load_blob(self) -> dict[str, Any]:
        raw = get_secret(_SETTING_KEY, "")
        if not raw:
            return {"seeded_env": False, "keys": []}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("not a dict")
            return {
                "seeded_env": bool(data.get("seeded_env")),
                "keys": [k for k in (data.get("keys") or []) if isinstance(k, dict)],
            }
        except (json.JSONDecodeError, ValueError):
            return {"seeded_env": False, "keys": []}

    def _save(self) -> None:
        blob = {
            "seeded_env": self._seeded_env,
            "keys": [
                {"id": k.id, "label": k.label, "key": k.key, "enabled": k.enabled}
                for k in self._keys
            ],
        }
        set_secret(_SETTING_KEY, json.dumps(blob, ensure_ascii=False))

    def load(self) -> None:
        """首次加载：读库 + 用 .env 里的 Key 播种一次。"""
        with self._lock:
            if self._loaded:
                return
            blob = self._load_blob()
            self._seeded_env = blob["seeded_env"]
            self._keys = [
                _KeyState(str(x.get("id") or key_id(str(x.get("key", "")))),
                          str(x.get("label") or "未命名"), str(x.get("key") or ""),
                          bool(x.get("enabled", True)))
                for x in blob["keys"] if x.get("key")
            ]
            self._loaded = True
            # .env 播种：只播一次，之后完全以界面增删为准
            env_key = (_app_settings.twelvedata_api_key or "").strip()
            if env_key and not self._seeded_env:
                self._seeded_env = True
                if not any(k.key == env_key for k in self._keys):
                    self._keys.append(_KeyState(key_id(env_key), "来自 .env", env_key, True))
                self._save()

    def reload(self) -> None:
        """外部（增删改）改动后重新读库，丢弃内存列表但保留计数由 id 续接。"""
        with self._lock:
            keep = {k.id: k for k in self._keys}
            self._loaded = False
            self.load()
            # 计数续接：同 id 的 Key 沿用旧计数，避免编辑一次就把额度重置（会超发）
            for k in self._keys:
                old = keep.get(k.id)
                if old is not None:
                    k._window = old._window
                    k._day, k._day_count = old._day, old._day_count
                    k.cooldown_until = old.cooldown_until
                    k.total_ok, k.total_fail = old.total_ok, old.total_fail

    # ------------------------------------------------------------------
    # 取 Key（轮询）
    # ------------------------------------------------------------------
    def acquire(self) -> _KeyState | None:
        """按轮询顺序取一个当前可用的 Key 并占用额度；全不可用返回 None。"""
        self.load()
        with self._lock:
            n = len(self._keys)
            if n == 0:
                return None
            for i in range(n):
                idx = (self._cursor + i) % n
                st = self._keys[idx]
                ok, _why = st.available()
                if ok:
                    st.take()
                    self._cursor = (idx + 1) % n     # 轮询：下一个请求从下一个 Key 开始
                    return st
            return None

    def report(self, st: _KeyState, ok: bool, *, status_code: int | None = None,
               payload: Any = None) -> None:
        """回填一次调用结果，处理限流/鉴权失败与自愈。

        TwelveData 限流时**可能 HTTP 200 + body code=429**，所以 body 也要看。
        """
        with self._lock:
            body_code = None
            body_msg = ""
            if isinstance(payload, dict):
                body_code = payload.get("code")
                body_msg = str(payload.get("message") or "")
            limited = status_code == 429 or body_code == 429
            auth_bad = status_code in (401, 403) or body_code in (401, 403)
            if ok:
                st.total_ok += 1
                st.last_error = ""
            else:
                st.total_fail += 1
                st.last_error = (body_msg or f"HTTP {status_code or '?'}")[:160]
                if limited:
                    st.cooldown_until = time.time() + _COOLDOWN_SEC
                    st.last_error = f"限流，冷却 {int(_COOLDOWN_SEC)}s"
                elif auth_bad:
                    st.cooldown_until = time.time() + _COOLDOWN_AUTH_SEC
                    st.last_error = f"密钥无效或无权限：{st.last_error}"

    def note_usage(self, st: _KeyState, usage: dict[str, Any]) -> None:
        """记录一次 /api_usage 的结果（用于界面显示真实剩余额度）。"""
        with self._lock:
            st.last_usage = usage

    # ------------------------------------------------------------------
    # 增删改
    # ------------------------------------------------------------------
    def add(self, key: str, label: str = "") -> dict[str, Any]:
        k = (key or "").strip()
        if not k:
            raise ValueError("密钥不能为空")
        if len(k) < 16:
            raise ValueError("密钥长度异常（TwelveData 密钥通常为 32 位）")
        self.load()
        with self._lock:
            if any(x.key == k for x in self._keys):
                raise ValueError("该密钥已存在")
            if len(self._keys) >= _MAX_KEYS:
                raise ValueError(f"最多 {_MAX_KEYS} 个密钥")
            kid = key_id(k)
            st = _KeyState(kid, (label or "").strip() or f"Key {len(self._keys) + 1}", k, True)
            self._keys.append(st)
            self._save()
            return st.snapshot()

    def remove(self, kid: str) -> bool:
        self.load()
        with self._lock:
            before = len(self._keys)
            self._keys = [x for x in self._keys if x.id != kid]
            if len(self._keys) == before:
                return False
            self._cursor = 0
            self._save()
            return True

    def update(self, kid: str, *, label: str | None = None,
               enabled: bool | None = None) -> dict[str, Any] | None:
        self.load()
        with self._lock:
            for x in self._keys:
                if x.id == kid:
                    if label is not None:
                        x.label = label.strip() or x.label
                    if enabled is not None:
                        x.enabled = bool(enabled)
                        if enabled:
                            x.cooldown_until = 0.0     # 手动启用 = 解除冷却，给它一次机会
                    self._save()
                    return x.snapshot()
            return None

    def clear_cooldowns(self) -> int:
        """手动清除全部冷却（用户确认额度已恢复时用）。"""
        self.load()
        with self._lock:
            n = 0
            for x in self._keys:
                if x.cooldown_until > time.time():
                    x.cooldown_until = 0.0
                    n += 1
            return n

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        self.load()
        with self._lock:
            snaps = [k.snapshot() for k in self._keys]
            enabled = [k for k in self._keys if k.enabled]
            avail = sum(1 for k in enabled if k.available()[0])
            return {
                "keys": snaps,
                "count": len(snaps),
                "enabled": len(enabled),
                "available_now": avail,
                # 多 Key 的额度是**线性叠加**的，这是本功能的核心收益
                "effective_per_min": len(enabled) * PER_MIN_LIMIT,
                "effective_per_day": len(enabled) * PER_DAY_LIMIT,
                "per_min_limit": PER_MIN_LIMIT,
                "per_day_limit": PER_DAY_LIMIT,
                "env_key_configured": bool((_app_settings.twelvedata_api_key or "").strip()),
                "next_index": self._cursor,
            }

    def has_key(self) -> bool:
        self.load()
        with self._lock:
            return any(k.enabled for k in self._keys)


_pool: KeyPool | None = None
_pool_lock = threading.Lock()


def pool() -> KeyPool:
    """全局单例。"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                p = KeyPool()
                p.load()
                _pool = p
    return _pool


# ------------------------------------------------------------------
# 真实调用
# ------------------------------------------------------------------
def _extract_error(payload: Any) -> str:
    if isinstance(payload, dict):
        if payload.get("status") == "error" or payload.get("code"):
            return str(payload.get("message") or payload.get("code") or "")[:160]
    return ""


def api_get(path: str, params: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
    """带轮询 Key 的 GET。返回 {"ok":bool, "data":..., "error":str, "key_id":str}。

    限流/失效的 Key 会被自动冷却并**换下一个 Key 重试一次**，
    这样单个账号打满不会让整条请求失败。
    """
    p = pool()
    tried: set[str] = set()
    last_err = "无可用 Key"
    for _ in range(max(1, len(p._keys) or 1) + 1):
        st = p.acquire()
        if st is None:
            break
        if st.id in tried:
            break
        tried.add(st.id)
        try:
            with httpx.Client(timeout=timeout or _app_settings.data_timeout_sec) as c:
                r = c.get(f"{BASE}{path}", params={**params, "apikey": st.key})
            payload: Any = None
            try:
                payload = r.json()
            except Exception:  # noqa: BLE001
                payload = None
            err = _extract_error(payload)
            if r.status_code == 200 and not err:
                p.report(st, True, status_code=200, payload=payload)
                return {"ok": True, "data": payload, "error": "", "key_id": st.id}
            p.report(st, False, status_code=r.status_code, payload=payload)
            last_err = err or f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            p.report(st, False, status_code=None, payload=None)
            last_err = f"{type(exc).__name__}: {exc}"[:160]
    return {"ok": False, "data": None, "error": last_err, "key_id": ""}


def probe_usage(st: _KeyState | None = None) -> dict[str, Any]:
    """调用 /api_usage 拿真实额度；不给 st 就用池里第一个可用 Key。"""
    p = pool()
    target = st
    if target is None:
        target = p.acquire()
    if target is None:
        return {"ok": False, "error": "无可用 Key"}
    try:
        with httpx.Client(timeout=_app_settings.data_timeout_sec) as c:
            r = c.get(f"{BASE}/api_usage", params={"apikey": target.key})
        payload = r.json() if r.status_code == 200 else None
        err = _extract_error(payload)
        if r.status_code == 200 and not err and isinstance(payload, dict):
            p.report(target, True, status_code=200, payload=payload)
            p.note_usage(target, payload)
            return {"ok": True, "usage": payload, "key_id": target.id, "masked": mask_key(target.key)}
        p.report(target, False, status_code=r.status_code, payload=payload)
        return {"ok": False, "error": err or f"HTTP {r.status_code}", "key_id": target.id}
    except Exception as exc:  # noqa: BLE001
        p.report(target, False, status_code=None, payload=None)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160], "key_id": target.id}
