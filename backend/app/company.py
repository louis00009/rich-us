"""公司档案：英文名 + 英文介绍 + 关键信息（榜单/AI 分析共用）；中文名 + 市值（腾讯批量行情）。"""
from __future__ import annotations

import json
import re
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from .database import SessionLocal, session_scope
from .models import CompanyProfile

_TTL_SEC = 30 * 86400        # 档案 30 天刷新一次


def _tencent_batch(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """腾讯批量行情：中文名（第 2 段）+ 总市值（第 45 段，亿美元）。

    返回 {symbol: {"name_cn": ..., "market_cap": 美元}}。
    市值口径验证：AAPL 145.9 亿股 × $337 ≈ 49154 亿 = parts[44] ✓。
    """
    import httpx

    codes = []
    for s in symbols:
        s = s.strip().upper()
        if s.endswith(".HK"):
            # 平台港股 4 位（0700）→ 腾讯 5 位（hk00700）
            codes.append("hk" + s.split(".")[0].zfill(5))
        else:
            codes.append(f"us{s}")
    out: dict[str, dict[str, Any]] = {}
    try:
        for i in range(0, len(codes), 50):
            batch = codes[i : i + 50]
            url = "https://qt.gtimg.cn/q=" + ",".join(batch)
            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 QuantDesk"}, timeout=10)
            r.raise_for_status()
            text = r.content.decode("gbk", errors="ignore")
            for m in re.finditer(r'v_([A-Za-z0-9]+)="([^"]*)"', text):
                var, body = m.group(1), m.group(2)
                parts = body.split("~")
                if len(parts) < 5 or not parts[1]:
                    continue
                if var.startswith("us"):
                    sym = var[2:].upper()
                elif var.startswith("hk"):
                    # 腾讯港股代码 5 位（hk00700）→ 平台 4 位口径（0700.HK）：
                    # lstrip 去多余前导零后 zfill(4)。'00700'→'700'→'0700' ✓
                    sym = var[2:].lstrip("0").zfill(4) + ".HK"
                else:
                    continue
                cap = None
                try:
                    if len(parts) > 44 and parts[44]:
                        cap = float(parts[44]) * 1e8       # 亿美元 → 美元
                except (ValueError, IndexError):
                    cap = None
                out[sym] = {"name_cn": parts[1], "market_cap": cap}
    except Exception:  # noqa: BLE001 —— 名称/市值拉取失败不影响主流程
        pass
    return out


def names_cn(symbols: list[str]) -> dict[str, str]:
    """批量中文名：先查库，缺失的走腾讯批量拉取并落库（一次拉取永久缓存）。

    负缓存：拉取后仍无中文名的（腾讯不覆盖的小票）也落库空标记，
    避免 rankings 每次调用都对同一批"拉不到"的代码重发 11 批请求（曾拖到 9s）。
    """
    syms = [s.strip().upper() for s in symbols if s.strip()]
    if not syms:
        return {}
    known: dict[str, str] = {}
    missing: list[str] = []
    with SessionLocal() as s:
        rows = s.query(CompanyProfile).filter(CompanyProfile.symbol.in_(syms)).all()
        known_syms = {row.symbol for row in rows}          # 有行即视为已知（含负缓存空名）
        for row in rows:
            if row.name_cn:
                known[row.symbol] = row.name_cn
        missing = [x for x in syms if x not in known_syms]
    if missing:
        fetched = _tencent_batch(missing)
        with session_scope() as s2:
            for sym in missing:
                info = fetched.get(sym) or {}
                cn = info.get("name_cn") or ""
                if cn:
                    known[sym] = cn
                row = s2.get(CompanyProfile, sym)
                if row:
                    row.name_cn = cn or row.name_cn
                    if info.get("market_cap") and not row.market_cap:
                        row.market_cap = info["market_cap"]
                else:
                    s2.add(CompanyProfile(symbol=sym, name_cn=cn,
                                          market_cap=info.get("market_cap") or 0.0))
    return known


def names_cn_cached(symbols: list[str]) -> dict[str, str]:
    """只读版中文名：**绝不发起网络请求**（搜索等延迟敏感场景用）。

    未缓存的符号回落空串（前端显示英文名）；中文名由榜单预热/names_cn 渐进填充。
    """
    syms = [s.strip().upper() for s in symbols if s.strip()]
    if not syms:
        return {}
    with SessionLocal() as s:
        return {
            row.symbol: row.name_cn
            for row in s.query(CompanyProfile).filter(CompanyProfile.symbol.in_(syms)).all()
            if row.name_cn
        }


def enrich(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """中文名 + 总市值（美元）。落库缓存（含负缓存，见 names_cn）；缺失的批量补拉一次。"""
    syms = [s.strip().upper() for s in symbols if s.strip()]
    if not syms:
        return {}
    known: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    with SessionLocal() as s:
        rows = s.query(CompanyProfile).filter(CompanyProfile.symbol.in_(syms)).all()
        known_syms = {row.symbol for row in rows}          # 有行即已知（含负缓存空名）
        for row in rows:
            known[row.symbol] = {
                "name_cn": row.name_cn or "",
                "market_cap": float(row.market_cap) if row.market_cap else None,
            }
        missing = [x for x in syms if x not in known_syms]
    if missing:
        fetched = _tencent_batch(missing)
        with session_scope() as s2:
            for sym in missing:
                info = fetched.get(sym) or {}
                if info.get("name_cn") or info.get("market_cap"):
                    known[sym] = info
                row = s2.get(CompanyProfile, sym)
                if row:
                    row.name_cn = info.get("name_cn") or row.name_cn
                    if info.get("market_cap"):
                        row.market_cap = info["market_cap"]
                else:
                    s2.add(CompanyProfile(symbol=sym, name_cn=info.get("name_cn") or "",
                                          market_cap=info.get("market_cap") or 0.0))
    return known


def get_profile(symbol: str, force: bool = False) -> dict[str, Any]:
    """读档案（缓存 30 天）；无缓存或过期时联网拉取；失败返回旧值或空壳。"""
    sym = symbol.strip().upper()
    with SessionLocal() as s:
        row = s.get(CompanyProfile, sym)
        cached = None
        if row:
            # SQLite 存的是 naive UTC；aware now 直接相减会 TypeError——统一补 UTC
            updated = row.updated_at
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=_tz.utc)
            age = (_dt.now(_tz.utc) - updated).total_seconds() if updated else 99999
            cached = {
                "symbol": row.symbol, "name": row.name, "name_cn": row.name_cn,
                "industry": row.industry, "sector": row.sector,
                "country": row.country, "website": row.website,
                "ipo_date": row.ipo_date, "market_cap": float(row.market_cap or 0.0),
                "summary": row.summary, "cached_days": round(age / 86400, 1),
            }
    if cached and not force and cached.get("summary") and (cached.get("cached_days") or 99) < 30:
        return {**cached, "source": "cache"}

    fresh: dict[str, Any] = {}
    try:
        fresh = _fetch_yf(sym)
    except Exception as exc:  # noqa: BLE001
        if cached:
            return {**cached, "source": "cache-stale", "fetch_error": str(exc)[:160]}
        return {"symbol": sym, "name": "", "name_cn": "", "industry": "", "sector": "",
                "country": "", "website": "", "ipo_date": "", "market_cap": 0.0,
                "summary": "", "source": "none", "fetch_error": str(exc)[:160]}

    with session_scope() as s2:
        row = s2.get(CompanyProfile, sym)
        if row:
            for k in ("name", "industry", "sector", "country", "website", "ipo_date", "market_cap", "summary"):
                v = fresh.get(k)
                if v not in (None, ""):
                    setattr(row, k, v)
        else:
            s2.add(CompanyProfile(symbol=sym, **{k: fresh.get(k) or (0.0 if k == "market_cap" else "") for k in
                                                 ("name", "industry", "sector", "country", "website", "ipo_date", "summary")}))
    # 中文名顺带补齐
    try:
        cn = names_cn([sym]).get(sym, "")
        if cn:
            fresh["name_cn"] = cn
    except Exception:  # noqa: BLE001
        pass
    return {**fresh, "source": "yfinance", "cached_days": 0}


def _fetch_yf(symbol: str) -> dict[str, Any]:
    """yfinance info 拉档案。慢（~2s），所以必须有缓存。"""
    import yfinance as yf

    info = yf.Ticker(symbol).info or {}
    return {
        "symbol": symbol,
        "name": str(info.get("shortName") or info.get("longName") or ""),
        "industry": str(info.get("industry") or ""),
        "sector": str(info.get("sector") or ""),
        "country": str(info.get("country") or ""),
        "website": str(info.get("website") or ""),
        "ipo_date": str(info.get("ipoDate") or ""),
        "market_cap": float(info.get("marketCap") or 0.0),
        "summary": str(info.get("longBusinessSummary") or ""),
    }
