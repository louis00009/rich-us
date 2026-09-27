"""智能提示引擎：技术信号 + 新闻关键词 → alert_events（去重落库）。

设计原则：
  · 提示只来自「用户关心的标的」：关注列表 ∪ 当前持仓，绝不全市场扫。
  · 每条事件带 dedup_key：同一标的一天内同一种信号只提示一次。
  · 扫描有冷却（默认 90s），前端轮询 /alerts?auto=1 也不会打爆数据源。
"""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from .config import settings

_scan_lock = threading.Lock()
_last_scan = 0.0

# 新闻关键词 → (级别, 标签)。命中任一即生成一条 news 提示。
NEWS_KEYWORDS: list[tuple[str, str, str]] = [
    # (关键词, level, 中文标签)
    ("停牌", "warn", "停牌"),
    ("复牌", "info", "复牌"),
    ("盈警", "warn", "盈利警告"),
    ("盈利警告", "warn", "盈利警告"),
    ("盈喜", "hot", "盈喜"),
    ("业绩预告", "info", "业绩预告"),
    ("業績", "info", "业绩"),
    ("earnings", "info", "Earnings"),
    ("回购", "hot", "回购"),
    ("buyback", "hot", "Buyback"),
    ("收购", "hot", "收购/并购"),
    ("并购", "hot", "收购/并购"),
    ("merger", "hot", "Merger"),
    ("acquisition", "hot", "Acquisition"),
    ("要约", "hot", "要约收购"),
    ("私有化", "hot", "私有化"),
    ("评级下调", "warn", "评级下调"),
    ("downgrade", "warn", "Downgrade"),
    ("upgrade", "info", "Upgrade"),
    ("上调评级", "info", "评级上调"),
    ("增发", "warn", "增发/配股"),
    ("配股", "warn", "增发/配股"),
    ("减持", "warn", "减持"),
    ("诉讼", "warn", "诉讼"),
    ("调查", "warn", "调查"),
    ("investigation", "warn", "Investigation"),
    ("派息", "info", "派息"),
    ("dividend", "info", "Dividend"),
]


def _dedup(kind: str, symbol: str, extra: str = "") -> str:
    day = time.strftime("%Y%m%d")
    raw = f"{kind}|{symbol}|{day}|{extra}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:40]


# ======================================================================
# 标的集合
# ======================================================================
def _symbols_to_scan() -> list[str]:
    from .database import SessionLocal
    from .models import PositionSnapshot, WatchlistItem

    syms: list[str] = []
    with SessionLocal() as s:
        for row in s.query(WatchlistItem).all():
            if row.symbol not in syms:
                syms.append(row.symbol)
        for row in s.query(PositionSnapshot).filter(PositionSnapshot.quantity > 0).all():
            if row.symbol not in syms:
                syms.append(row.symbol)
    return syms[: max(1, settings.news_scan_symbols)]


def _market_of(symbol: str) -> str:
    try:
        from .markets import symbols as mksym
        return mksym.parse(symbol).market
    except Exception:  # noqa: BLE001
        return "HK" if symbol.upper().endswith(".HK") else "US"


# ======================================================================
# 技术信号
# ======================================================================
def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def _tech_alerts(symbol: str, market: str, df) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        if df is None or len(df) < 60:
            return out
        close = [float(x) for x in df["close"].tolist()]
        high = [float(x) for x in df["high"].tolist()]
        low = [float(x) for x in df["low"].tolist()]
        vol = [float(x) for x in df["volume"].tolist()]
        last = close[-1]
        if last <= 0:
            return out
        window = min(252, len(close) - 1)
        prev_high = max(high[-window - 1:-1])
        prev_low = min(low[-window - 1:-1])
        prev_close = close[-2] if len(close) > 1 else last

        # 52 周新高 / 逼近 / 新低
        if last > prev_high:
            out.append(_mk("high_52w", "hot", symbol, market,
                           f"创 52 周新高 {last:g}", f"突破此前 52 周最高价 {prev_high:g}"))
        elif last >= prev_high * 0.98:
            out.append(_mk("high_52w", "info", symbol, market,
                           f"逼近 52 周新高（距 {((prev_high / last - 1) * 100):.1f}%）",
                           f"52 周最高 {prev_high:g}，现价 {last:g}"))
        if last < prev_low:
            out.append(_mk("low_52w", "warn", symbol, market,
                           f"创 52 周新低 {last:g}", f"跌破此前 52 周最低价 {prev_low:g}"))

        # 放量
        ma20 = sum(vol[-21:-1]) / 20 if len(vol) > 21 else 0
        if ma20 > 0 and vol[-1] > 2.5 * ma20:
            pct = (last - prev_close) / prev_close * 100 if prev_close else 0.0
            lvl = "hot" if pct > 1 else "info"
            out.append(_mk("volume_spike", lvl, symbol, market,
                           f"放量 {vol[-1] / ma20:.1f} 倍",
                           f"成交量 {vol[-1]:,.0f}，20 日均量 {ma20:,.0f}，涨跌 {pct:+.2f}%"))

        # 跳空
        if prev_close > 0:
            gap = (close[-1] / prev_close - 1)
            if abs(gap) >= 0.025:
                out.append(_mk("gap", "hot" if gap > 0 else "warn", symbol, market,
                               f"跳空{'高开' if gap > 0 else '低开'} {abs(gap) * 100:.1f}%",
                               f"前收 {prev_close:g} → 现价 {last:g}"))

        # RSI 极值
        r = _rsi(close)
        if r >= 78:
            out.append(_mk("rsi", "warn", symbol, market, f"RSI 超买 {r:.0f}", "14 日 RSI ≥ 78，注意回撤风险"))
        elif r <= 22:
            out.append(_mk("rsi", "info", symbol, market, f"RSI 超卖 {r:.0f}", "14 日 RSI ≤ 22，关注反弹信号"))

        # 日内急涨急跌（按日线涨跌幅近似）
        if prev_close > 0:
            chg = (last - prev_close) / prev_close * 100
            th = 4.0 if market == "HK" else 5.0
            if abs(chg) >= th:
                out.append(_mk("swing", "hot" if chg > 0 else "warn", symbol, market,
                               f"日内急{'涨' if chg > 0 else '跌'} {abs(chg):.1f}%",
                               f"涨跌幅 {chg:+.2f}%（阈值 ±{th}%）"))
    except Exception:  # noqa: BLE001
        return out
    return out


def _mk(kind: str, level: str, symbol: str, market: str, title: str, detail: str,
        payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": kind, "level": level, "symbol": symbol, "market": market,
        "title": title, "detail": detail,
        "payload_json": __import__("json").dumps(payload or {}, ensure_ascii=False),
        "dedup_key": _dedup(kind, symbol, title[:40]),
    }


# ======================================================================
# 新闻关键词
# ======================================================================
def _news_alerts(symbol: str, market: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        text = f"{it.get('headline', '')} {it.get('summary', '')}"
        for kw, level, tag in NEWS_KEYWORDS:
            if kw.lower() in text.lower():
                out.append({
                    "kind": "news", "level": level, "symbol": symbol, "market": market,
                    "title": f"[{tag}] {it.get('headline', '')[:120]}",
                    "detail": (it.get("summary") or it.get("headline") or "")[:300],
                    "payload_json": __import__("json").dumps(
                        {"url": it.get("url", ""), "source": it.get("source", ""),
                         "published_at": it.get("published_at", "")}, ensure_ascii=False),
                    "dedup_key": _dedup("news", symbol, it.get("headline", "")[:60]),
                })
                break           # 一条新闻只发一次提示
    return out


# ======================================================================
# 落库 / 查询
# ======================================================================
def record(events: list[dict[str, Any]]) -> int:
    return len(record_events(events))


def record_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """落库并返回**真正入库**的事件（供 WebSocket 即时广播）。"""
    if not events:
        return []
    from .database import session_scope
    from .models import AlertEvent

    saved: list[dict[str, Any]] = []
    with session_scope() as s:
        for ev in events:
            try:
                exists = s.query(AlertEvent.id).filter(AlertEvent.dedup_key == ev["dedup_key"]).first()
                if exists:
                    continue
                row = AlertEvent(
                    kind=ev["kind"], level=ev.get("level", "info"),
                    symbol=ev["symbol"], market=ev.get("market", "US"),
                    title=ev.get("title", ""), detail=ev.get("detail", ""),
                    payload_json=ev.get("payload_json", "{}"),
                    dedup_key=ev["dedup_key"],
                )
                s.add(row)
                s.flush()
                saved.append({
                    "id": row.id, "ts": row.ts.isoformat() if row.ts else "",
                    "kind": ev["kind"], "level": ev.get("level", "info"),
                    "symbol": ev["symbol"], "market": ev.get("market", "US"),
                    "title": ev.get("title", ""), "detail": ev.get("detail", ""),
                })
            except Exception:  # noqa: BLE001
                s.rollback()
                continue
    return saved


def _intraday_alerts(symbol: str, market: str, quote: dict[str, Any]) -> list[dict[str, Any]]:
    """日内实时规则（T-102）：基于秒级报价，与日线口径的 _tech_alerts 互补。

    · 日内急涨/急跌：相对昨收 ±5%（US）/ ±4%（HK）
    · 日内大幅波动预警：±3%（仅 hot 提示一次，晚间复盘用）
    dedup 按「天 + 类型」，盘中同类型只提示一次，避免刷屏。
    """
    out: list[dict[str, Any]] = []
    try:
        px = float(quote.get("price", 0) or 0)
        pc = float(quote.get("prev_close", 0) or 0)
        if px <= 0 or pc <= 0:
            return out
        chg = (px / pc - 1) * 100
        src = str(quote.get("source", ""))
        tag = f"（来源 {src}）" if src else ""
        th_move = 4.0 if market == "HK" else 5.0
        th_warn = 3.0
        if abs(chg) >= th_move:
            out.append(_mk("rt_move", "hot" if chg > 0 else "warn", symbol, market,
                           f"盘中急{'涨' if chg > 0 else '跌'} {abs(chg):.1f}%",
                           f"现价 {px:g} ｜ 昨收 {pc:g} ｜ {chg:+.2f}% {tag}"))
        elif abs(chg) >= th_warn:
            out.append(_mk("rt_warn", "info", symbol, market,
                           f"盘中波动 {abs(chg):.1f}%",
                           f"现价 {px:g} ｜ {chg:+.2f}%，接近 {th_move}% 阈值 {tag}"))
    except Exception:  # noqa: BLE001
        return out
    return out


def scan(force: bool = False) -> dict[str, Any]:
    """跑一轮扫描（技术 + 新闻 + 日内实时）。返回 {created, events, scanned, ...}。"""
    global _last_scan
    with _scan_lock:
        if not force and time.time() - _last_scan < max(15, settings.alert_scan_cooldown_sec):
            return {"skipped": True, "cooldown_sec": settings.alert_scan_cooldown_sec,
                    "next_in": round(settings.alert_scan_cooldown_sec - (time.time() - _last_scan), 1)}
        _last_scan = time.time()

    symbols = _symbols_to_scan()
    events: list[dict[str, Any]] = []
    from .data_provider import fetch_history

    for sym in symbols:
        market = _market_of(sym)
        try:
            df, _src = fetch_history(sym, start=(_dt.now(_tz.utc) - _dt.timedelta(days=420)).strftime("%Y-%m-%d"))
            events.extend(_tech_alerts(sym, market, df))
        except Exception:  # noqa: BLE001
            pass
        try:
            # 日内实时规则：绕过 20s 报价缓存拿最新价（港股腾讯直连 / IBKR 快照）
            from .data_provider import _from_tencent_hk_quote, get_quote

            quote = _from_tencent_hk_quote(sym) if market == "HK" else None
            if quote is None:
                quote = get_quote(sym)
            if quote:
                events.extend(_intraday_alerts(sym, market, quote))
        except Exception:  # noqa: BLE001
            pass
        try:
            from .news import fetch_news
            res = fetch_news(sym, limit=5)
            events.extend(_news_alerts(sym, market, res["items"]))
        except Exception:  # noqa: BLE001
            continue

    saved = record_events(events)
    return {
        "skipped": False, "created": len(saved), "events": saved, "scanned": len(symbols),
        "candidates": len(events), "symbols": symbols,
        "at": _dt.now(_tz.utc).isoformat(),
    }


def list_events(limit: int = 50, unread_only: bool = False) -> list[dict[str, Any]]:
    from .database import SessionLocal
    from .models import AlertEvent

    with SessionLocal() as s:
        q = s.query(AlertEvent)
        if unread_only:
            q = q.filter(AlertEvent.is_read.is_(False))
        rows = q.order_by(AlertEvent.ts.desc(), AlertEvent.id.desc()).limit(min(limit, 200)).all()
        return [{
            "id": r.id, "ts": r.ts.isoformat(), "kind": r.kind, "level": r.level,
            "symbol": r.symbol, "market": r.market, "title": r.title, "detail": r.detail,
            "payload": __import__("json").loads(r.payload_json or "{}"), "is_read": r.is_read,
        } for r in rows]


def unread_count() -> int:
    from .database import SessionLocal
    from .models import AlertEvent

    with SessionLocal() as s:
        return int(s.query(AlertEvent.id).filter(AlertEvent.is_read.is_(False)).count())


def mark_read(ids: list[int] | None = None) -> int:
    """标记已读；ids 为空 = 全部。"""
    from .database import session_scope
    from .models import AlertEvent

    n = 0
    with session_scope() as s:
        q = s.query(AlertEvent)
        rows = q.filter(AlertEvent.id.in_(ids)).all() if ids else q.all()
        for r in rows:
            if not r.is_read:
                r.is_read = True
                n += 1
    return n
