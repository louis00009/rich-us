"""HKEX 披露易公告 provider（港股公告：业绩 / 配股 / 停复牌等）。

两步：prefix.do（符号 → 内部 stockId，带内存缓存）→ titleSearchServlet.do（最近公告）。
节奏温和：stockId 缓存永不过期；公告列表由上层 TTL 控制频率。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any

import requests

from .base import NewsItem, register_news_provider

_TIMEOUT = 10.0
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_prefix_cache: dict[str, int] = {}


def _digits(sym: str) -> str:
    """0700.HK / 700 / 0700 → 00700（4 位，保留 5 位 GEM 码原样）。"""
    code = sym.split(".")[0].strip()
    return code.zfill(4)


def _stock_id(symbol: str) -> int | None:
    sym = symbol.upper()
    if sym in _prefix_cache:
        return _prefix_cache[sym]
    code = _digits(sym)
    url = (
        "https://www1.hkexnews.hk/search/prefix.do?callback=callback&lang=ZH"
        f"&type=A&name={code}&market=SEHK"
    )
    r = requests.get(url, timeout=_TIMEOUT, headers=_UA)
    r.raise_for_status()
    m = re.search(r"callback\((.*)\)\s*;?\s*$", r.text, re.S)
    if not m:
        return None
    data = json.loads(m.group(1))
    stock_list = data.get("stockInfo") or []
    for d in stock_list:
        if str(d.get("code", "")).lstrip("0") == code.lstrip("0"):
            sid = int(d["stockId"])
            _prefix_cache[sym] = sid
            return sid
    return None


def _hkex_dt(s: str) -> str:
    """披露易日期形如 '23/09/2026 20:11' → ISO UTC；解析失败返回空串。"""
    if not s:
        return ""
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(s.strip(), fmt).replace(tzinfo=_dt.timezone.utc).isoformat()
        except ValueError:
            continue
    return ""


class HkexNews:
    name = "hkex"

    def fetch(self, symbol: str | None, limit: int = 20) -> list[NewsItem]:
        if not symbol or not symbol.upper().endswith(".HK"):
            return []               # 只服务港股
        sid = _stock_id(symbol)
        if sid is None:
            return []
        to = _dt.date.today()
        frm = to - _dt.timedelta(days=60)
        params = {
            "sortDir": "0", "sortByOptions": "DateTime", "category": "0",
            "market": "SEHK", "stockId": sid, "documentType": "-1",
            "fromDate": frm.strftime("%Y%m%d"), "toDate": to.strftime("%Y%m%d"),
            "title": "", "searchType": "1", "t1code": "-2", "t2Gcode": "-2",
            "t2code": "-2", "rowRange": str(min(40, limit * 2)), "lang": "zh",
        }
        r = requests.get(
            "https://www1.hkexnews.hk/search/titleSearchServlet.do",
            params=params, timeout=_TIMEOUT, headers=_UA,
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        rows = json.loads(data.get("result") or "[]")
        out: list[NewsItem] = []
        for d in rows[: limit * 2]:
            title = str(d.get("TITLE") or "").strip()
            if not title:
                continue
            link = str(d.get("FILE_LINK") or "")
            out.append(NewsItem(
                source="hkex",
                headline=title[:500],
                url=f"https://www1.hkexnews.hk{link}" if link.startswith("/") else link,
                summary="",
                symbol=symbol.upper(),
                market="HK",
                category="announcement",
                published_at=_hkex_dt(str(d.get("DATE_TIME") or "")),
                extra={"is_ie": d.get("IS_IE")},   # 内幕消息标记
            ))
        return out


def register() -> None:
    register_news_provider(HkexNews())
