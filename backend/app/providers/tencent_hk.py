"""腾讯行情（港股日线 / m1 / 实时报价）（FILE_SIZE_DEBT Batch F-3 拆出）。

⚠️ 腾讯 m1 预转换的 UTC 序列依赖 `_normalize` 默认 naive_tz='UTC' 语义。
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pandas as pd

from ..config import settings
from .common import OHLCV, _normalize
from .synthetic import _market_of


def _tencent_hk_code(symbol: str) -> str:
    """0700.HK → hk00700。"""
    code = symbol.upper().split(".")[0].strip()
    return f"hk{code.zfill(5)}"



def _from_tencent_hk(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    """腾讯港股日线（前复权）。免费、无需 key，可回溯 800+ 根。

    接口: web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk00700,day,,,320,qfq
    返回 data.hk00700.qfqday = [[date, open, close, high, low, volume, ...], ...]
    """
    if interval != "1d" or not symbol.upper().endswith(".HK"):
        return pd.DataFrame(columns=OHLCV)
    code = _tencent_hk_code(symbol)
    days = max(80, (datetime.now() - datetime.fromisoformat(start)).days + 30)
    count = min(int(days / 5 * 7) + 10, 800)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{count},qfq"
    with httpx.Client(timeout=settings.data_timeout_sec, follow_redirects=True) as c:
        r = c.get(url, headers={"User-Agent": "Mozilla/5.0 QuantDesk"})
    r.raise_for_status()
    data = r.json().get("data", {}).get(code, {})
    rows = data.get("qfqday") or data.get("day") or []
    if not rows:
        return pd.DataFrame(columns=OHLCV)
    recs = []
    for row in rows:
        try:
            recs.append({
                "date": pd.Timestamp(row[0]),
                "open": float(row[1]), "close": float(row[2]),
                "high": float(row[3]), "low": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 and row[5] else 0.0,
            })
        except (ValueError, IndexError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=OHLCV)
    df = pd.DataFrame(recs).set_index("date").sort_index()
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return _normalize(df)



def _from_tencent_hk_m1(symbol: str, start: str, end: str | None = None, interval: str = "1m") -> pd.DataFrame:
    """腾讯港股当日分时（minute/query，实测可用）。
    返回行: "HHMM 价格 累计成交量 累计成交额" → 1 分钟 close 序列 + 差分成交量。
    """
    if not symbol.upper().endswith(".HK"):
        return pd.DataFrame(columns=OHLCV)
    code = _tencent_hk_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}"
    with httpx.Client(timeout=settings.data_timeout_sec, follow_redirects=True) as c:
        r = c.get(url, headers={"User-Agent": "Mozilla/5.0 QuantDesk"})
    r.raise_for_status()
    node = (r.json().get("data", {}).get(code, {}) or {}).get("data", {}) or {}
    rows = node.get("data") or []
    if not rows or not isinstance(rows, list):
        return pd.DataFrame(columns=OHLCV)
    # 分钟只有 HHMM 没有日期；优先用接口自带 date，否则退回今天
    base = pd.Timestamp.now().normalize()
    try:
        if node.get("date"):
            base = pd.Timestamp(str(node["date"]))
    except Exception:  # noqa: BLE001
        pass
    recs = []
    prev_cum = 0.0
    prev_px: float | None = None
    for row in rows:
        try:
            parts = str(row).split()
            if len(parts) < 2:
                continue
            hm = parts[0]
            if len(hm) != 4 or not hm.isdigit():
                continue
            px = float(parts[1])
            cum = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0
            ts_hk = base + pd.Timedelta(hours=int(hm[:2]), minutes=int(hm[2:]))
            # 统一时区语义：把「HK 本地时间」转成真实时刻的 UTC 表示（naive）。
            # _normalize 会把 naive 当 UTC 转 NY —— 与 yfinance 写缓存（aware→UTC→NY）
            # 完全同语义，缓存才可混用；展示层再用 NY→HK 还原回港交所本地时间。
            ts_utc = ts_hk.tz_localize("Asia/Hong_Kong").tz_convert("UTC").tz_localize(None)
            vol = max(0.0, cum - prev_cum)      # 接口给的是累计量，差分还原每分钟
            prev_cum = cum
            o = prev_px if prev_px is not None else px
            recs.append({"date": ts_utc, "open": o, "close": px, "high": max(o, px), "low": min(o, px), "volume": vol})
            prev_px = px
        except (ValueError, IndexError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=OHLCV)
    return _normalize(pd.DataFrame(recs).set_index("date").sort_index())



def _from_tencent_hk_quote(symbol: str) -> dict | None:
    """腾讯港股实时快照（秒级）。IB 断连时是港股报价的兜底。"""
    if not symbol.upper().endswith(".HK"):
        return None
    code = _tencent_hk_code(symbol)
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as c:
            r = c.get(f"https://qt.gtimg.cn/q={code}", headers={"User-Agent": "Mozilla/5.0 QuantDesk"})
        r.raise_for_status()
        text = r.content.decode("gbk", errors="ignore")
        if "~" not in text:
            return None
        f = text.split('"')[1].split("~")
        price = float(f[3]) if f[3] else 0.0
        if price <= 0:
            return None
        prev = float(f[4]) if len(f) > 4 and f[4] else 0.0
        vol = float(f[6]) if len(f) > 6 and f[6] else 0.0
        high = float(f[33]) if len(f) > 33 and f[33] else price
        low = float(f[34]) if len(f) > 34 and f[34] else price
        return {
            "symbol": symbol.upper(),
            "price": round(price, 4),
            "prev_close": round(prev, 4),
            "change": round(price - prev, 4) if prev else 0.0,
            "change_pct": round((price - prev) / prev * 100, 3) if prev else 0.0,
            "volume": vol,
            "day_high": round(high, 4),
            "day_low": round(low, 4),
            "open": float(f[5]) if len(f) > 5 and f[5] else 0.0,
            "name": f[1] if f else "",
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": "tencent-hk",
        }
    except Exception:  # noqa: BLE001
        return None



def v_tencent_hk(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_tencent_hk(symbol, start, end, interval)



def v_tencent_hk_m1(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_tencent_hk_m1(symbol, start, end, interval)

