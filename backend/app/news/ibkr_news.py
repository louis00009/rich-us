"""IBKR 新闻 provider（reqNewsBullets / reqHistoricalNews）。

注意：
  · 新闻订阅随账户配置而异（paper 一般有 DJ 摘要）。无订阅时返回空列表，
    原因记在 provider 状态里 —— 优雅降级，绝不抛异常打断聚合。
  · 必须走券商对象的 _call/_await（独立事件循环），不得阻塞主线程。
"""
from __future__ import annotations

import datetime as _dt

from .base import NewsItem, register_news_provider

_PROVIDER_CODES = "DJ,FLY,IB"       # Dow Jones / FlyOnTheWall / IB 展望


def _broker():
    from ..brokers import get_ibkr
    return get_ibkr()


class IbkrNews:
    name = "ibkr"

    def fetch(self, symbol: str | None, limit: int = 20) -> list[NewsItem]:
        try:
            b = _broker()
        except Exception:  # noqa: BLE001
            return []
        if not b.connected:
            return []
        if symbol:
            return self._historical(b, symbol.upper(), limit)
        return self._bullets(b, limit)

    def _historical(self, b, symbol: str, limit: int) -> list[NewsItem]:
        try:
            contract = b._contract(symbol)
        except Exception:  # noqa: BLE001
            return []
        con_id = int(getattr(contract, "conId", 0) or 0)
        if con_id <= 0:
            return []
        end = _dt.datetime.now(_dt.timezone.utc)
        start = end - _dt.timedelta(days=7)
        try:
            # P1-3：必须用 Async 变体（同步版 reqHistoricalNews 在专属事件循环线程外
            # 调用会抛 "This event loop is already running" 或直接阻塞）。
            ticks = b._await(
                b._ib.reqHistoricalNewsAsync(
                    con_id, _PROVIDER_CODES,
                    start.strftime("%Y%m%d %H:%M:%S"), end.strftime("%Y%m%d %H:%M:%S"),
                    min(limit, 20),
                ),
                timeout=8.0,
            )
        except Exception:  # noqa: BLE001
            return []
        out: list[NewsItem] = []
        for t in ticks or []:
            out.append(NewsItem(
                source="ibkr",
                headline=str(getattr(t, "headline", "") or "")[:500],
                url="",
                summary="",
                symbol=symbol,
                category="company",
                published_at=str(getattr(t, "time", "") or ""),
                extra={"provider_code": getattr(t, "providerCode", ""), "article_id": getattr(t, "articleId", "")},
            ))
        return out

    def _bullets(self, b, limit: int) -> list[NewsItem]:
        # P1-3：`reqNewsBullets` 这个方法在 ib_insync/ib_async 里不存在（实际是
        # reqNewsBulletins，且是纯发送无回包）—— 旧代码 AttributeError 被吞成空列表，
        # IBKR 新闻功能等于不存在。改为读 IB 的 bulletin 缓存属性。
        try:
            bullets = list(getattr(b._ib, "newsBulletins", []) or [])[: min(limit, 20)]
        except Exception:  # noqa: BLE001
            return []
        out: list[NewsItem] = []
        for t in bullets:
            out.append(NewsItem(
                source="ibkr",
                headline=str(getattr(t, "message", getattr(t, "headline", "")) or "")[:500],
                url="",
                summary="",
                symbol="",
                category="market",
                published_at=str(getattr(t, "time", "") or ""),
                extra={"provider_code": getattr(t, "providerCode", ""), "msg_id": getattr(t, "msgId", "")},
            ))
        return out


def register() -> None:
    register_news_provider(IbkrNews())
