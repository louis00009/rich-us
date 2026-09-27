"""实时推送中枢（秒级）
=====================
主题订阅协议（对应 TODO T-106）：
  客户端 → {"action": "sub"|"unsub", "topics": ["quotes:AAPL,SPY", "intraday:AAPL", "alerts"]}
  服务端 → {"topic": "quotes", "ts": ..., "data": [quote...]}
         {"topic": "alerts", "ts": ..., "data": [event...]}

秒级来源优先级：
  1) IBKR broker.quotes —— 流式缓存（reqMktData 已订阅标的 5s 内内存直读，0 请求）
  2) 港股：腾讯实时快照直连（绕过 20s 报价缓存）
  3) 免费源 get_quotes（美股无 IBKR 时 ~20s 级，消息带 rt_delayed 标注）
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime as _dt, timezone as _tz
from typing import Any

_lock = threading.Lock()
_conns: dict[int, "Conn"] = {}
_next_id = 0
_started = False


class Conn:
    """一条 WebSocket 连接：订阅主题集合 + 发送队列（线程安全投递到事件循环）。

    P1-6：`topics` 会被**两个线程**同时访问 —— 事件循环线程在 subscribe/unsubscribe
    时增删，后台 `_tick_loop` 线程在广播时迭代。旧实现无任何保护，
    迭代中改集合会抛 `RuntimeError: Set changed size during iteration`，
    又被 `_tick_loop` 的宽 except 吞掉 → 推送随机丢一拍且日志只有一行「tick 异常」。
    这里用**每连接一把锁**（不能用模块级 `_lock`：`_all_symbols` 已持有它，
    再获取会造成自死锁，threading.Lock 不可重入）。
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self._tlock = threading.Lock()
        self.topics: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=500)

    # ---- 订阅集合的线程安全访问 ----
    def add_topics(self, topics: list[str]) -> None:
        with self._tlock:
            for t in topics:
                t = str(t).strip()
                if t:
                    self.topics.add(t)

    def remove_topics(self, topics: list[str]) -> None:
        with self._tlock:
            for t in topics:
                self.topics.discard(str(t).strip())

    def snapshot(self) -> set[str]:
        with self._tlock:
            return set(self.topics)

    def has_alert(self) -> bool:
        with self._tlock:
            return "alerts" in self.topics

    def push(self, msg: dict[str, Any]) -> None:
        def _put() -> None:
            if not self.queue.full():
                self.queue.put_nowait(msg)

        try:
            self.loop.call_soon_threadsafe(_put)
        except RuntimeError:
            pass  # 事件循环已关闭（连接死亡中）

    def symbols(self) -> set[str]:
        """该连接关心的标的（quotes: 与 intraday: 主题并集）。"""
        out: set[str] = set()
        for t in self.snapshot():
            prefix = t.split(":", 1)[0]
            if prefix in ("quotes", "intraday") and ":" in t:
                for s in t.split(":", 1)[1].split(","):
                    s = s.strip().upper()
                    if s:
                        out.add(s)
        return out


def register(loop: asyncio.AbstractEventLoop) -> Conn:
    global _next_id
    with _lock:
        conn = Conn(loop)
        _conns[_next_id] = conn
        _next_id += 1
        n = len(_conns)
    _ensure_started()
    print(f"[realtime] 连接接入（当前 {n} 条）", flush=True)
    return conn


def unregister(conn: Conn) -> None:
    with _lock:
        for k, v in list(_conns.items()):
            if v is conn:
                _conns.pop(k, None)
                break


def subscribe(conn: Conn, topics: list[str]) -> None:
    conn.add_topics(topics)


def unsubscribe(conn: Conn, topics: list[str]) -> None:
    conn.remove_topics(topics)


def _all_symbols() -> list[str]:
    with _lock:
        conns = list(_conns.values())
    syms: set[str] = set()
    for c in conns:
        syms |= c.symbols()
    return sorted(syms)[:60]


def _has_alert_subs() -> bool:
    with _lock:
        conns = list(_conns.values())
    return any(c.has_alert() for c in conns)


def _broadcast_quotes(rows: list[dict[str, Any]]) -> None:
    with _lock:
        conns = list(_conns.values())
    if not conns:
        return
    ts = _dt.now(_tz.utc).isoformat()
    by_sym = {str(r.get("symbol", "")).upper(): r for r in rows}
    for c in conns:
        want = c.symbols()
        if not want:
            continue
        data = [by_sym[s] for s in want if s in by_sym]
        if data:
            c.push({"topic": "quotes", "ts": ts, "data": data})


def _broadcast_alerts(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    with _lock:
        conns = [c for c in _conns.values() if c.has_alert()]
    for c in conns:
        c.push({"topic": "alerts", "ts": _dt.now(_tz.utc).isoformat(), "data": events})


# ======================================================================
# 报价抓取（秒级路径）
# ======================================================================
def _market_of(symbol: str) -> str:
    try:
        from .markets import symbols as mksym
        return mksym.parse(symbol).market
    except Exception:  # noqa: BLE001
        return "HK" if symbol.upper().endswith(".HK") else "US"


def _fresh_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    """秒级报价：IBKR 流式缓存 > 港股腾讯直连 > 免费源（标注延迟）。"""
    out: dict[str, dict[str, Any]] = {}

    us = [s for s in symbols if _market_of(s) != "HK"]
    hk = [s for s in symbols if _market_of(s) == "HK"]

    if us:
        # 1) IBKR（连接时即秒级：流式缓存内存直读）
        try:
            from . import state as appstate
            from .brokers import get_broker

            cfg = appstate.get_broker_settings()
            if str(cfg.get("provider")) == "ibkr":
                broker, _mode = get_broker(cfg)
                for r in broker.quotes(us) or []:
                    if r.get("price", 0) > 0:
                        out[str(r["symbol"]).upper()] = r
        except Exception:  # noqa: BLE001
            pass
        # 2) 免费源补齐（get_quote 自带 20s 缓存，实际 ~20s 级）
        missing = [s for s in us if s not in out]
        if missing:
            try:
                from .data_provider import get_quotes

                for r in get_quotes(missing):
                    if r.get("price", 0) > 0:
                        out.setdefault(str(r["symbol"]).upper(), r)
            except Exception:  # noqa: BLE001
                pass

    for s in hk:
        # 3) 港股：腾讯实时快照直连（不走 20s 缓存）
        try:
            from .data_provider import _from_tencent_hk_quote, get_quote

            qt = _from_tencent_hk_quote(s)
            if qt is None:
                qt = get_quote(s)
            if qt and qt.get("price", 0) > 0:
                out[s] = qt
        except Exception:  # noqa: BLE001
            pass

    # 附加交易所本地时间与延迟标记，供前端分时 append 与 UI 标注
    rows = []
    for s in symbols:
        r = out.get(s)
        if not r:
            continue
        r = dict(r)
        try:
            from zoneinfo import ZoneInfo

            tzname = "Asia/Hong_Kong" if _market_of(s) == "HK" else "America/New_York"
            r["rt_t"] = _dt.now(ZoneInfo(tzname)).strftime("%H:%M")
        except Exception:  # noqa: BLE001
            r["rt_t"] = _dt.now(_tz.utc).strftime("%H:%M")
        r["rt_delayed"] = _market_of(s) != "HK" and not _ibkr_active()
        rows.append(r)
    return rows


def _ibkr_active() -> bool:
    try:
        from . import state as appstate
        from .brokers import get_broker

        cfg = appstate.get_broker_settings()
        if str(cfg.get("provider")) == "ibkr":
            broker, _mode = get_broker(cfg)
            return bool(getattr(broker, "connected", False))
    except Exception:  # noqa: BLE001
        pass
    return False


# ======================================================================
# 后台循环
# ======================================================================
def _tick_loop() -> None:
    """2 秒一拍：所有订阅标的的报价推送到关心它们的连接。"""
    while True:
        time.sleep(2)
        try:
            syms = _all_symbols()
            if not syms:
                continue
            rows = _fresh_quotes(syms)
            if rows:
                _broadcast_quotes(rows)
        except Exception as exc:  # noqa: BLE001 —— 后台循环绝不能死
            print(f"[realtime] tick 异常 {type(exc).__name__}: {exc}", flush=True)


def _alerts_loop() -> None:
    """60 秒一拍：日内实时扫描；有新事件且有人订阅 alerts → 推送。"""
    while True:
        time.sleep(60)
        try:
            if not _has_alert_subs():
                continue
            from . import alerts as alerts_mod

            res = alerts_mod.scan()          # 内置 90s 冷却
            events = res.get("events") or []
            if events:
                _broadcast_alerts(events)
        except Exception as exc:  # noqa: BLE001
            print(f"[realtime] alerts 异常 {type(exc).__name__}: {exc}", flush=True)


def _ensure_started() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_tick_loop, daemon=True, name="rt-tick").start()
    threading.Thread(target=_alerts_loop, daemon=True, name="rt-alerts").start()
    print("[realtime] 后台循环已启动（tick 2s / alerts 60s）", flush=True)
