"""公司档案：英文名 + 英文介绍 + 关键信息（榜单/AI 分析共用）；中文名 + 市值 + 估值（腾讯批量行情）。"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime as _dt, timezone as _tz
from typing import Any

from .database import SessionLocal, session_scope
from .models import CompanyProfile

_TTL_SEC = 30 * 86400        # 档案 30 天刷新一次

# 腾讯美股/港股行情串里已实测确认的字段下标。
# 取证脚本：`tools/_probe_tencent_fields.py`（148 只样本，2026-09-27 实测）。
#   1=中文名 38=换手率% 39=市盈率TTM 43=振幅% 44=流通市值(亿) 45=总市值(亿)
#   46=英文名 47=每股收益TTM 48=52周高 49=52周低 51=市净率 52=股息率%
#   62=总股本 63=流通股本
# ⚠️ 两个坑：
#   ① **44 是流通市值，45 才是总市值** —— 旧实现把 44 当总市值，AAPL/KO 因
#      流通≈总股本没暴露，NVDA 差 4%（52193 vs 54347 亿美元）。
#   ② 51（市净率）腾讯无公开字段文档，仅有间接证据（隐含 ROE 中位数 15.5%，
#      与 S&P 500 实际水平吻合）。若哪天发现 PB 明显离谱，先怀疑这一项。
_F = {
    "name_cn": 1, "turnover": 38, "pe_ttm": 39, "amplitude": 43,
    "market_cap_float": 44, "market_cap": 45, "name_en": 46, "eps_ttm": 47,
    "w52_high": 48, "w52_low": 49, "pb": 51, "div_yield": 52,
    "shares_total": 62, "shares_float": 63,
}
_CAP_KEYS = ("market_cap", "market_cap_float")   # 亿美元 → 美元
# 合理性区间：超界一律置 None，宁可显示 "—" 也不显示离谱数字。
_BOUNDS = {
    "pe_ttm": (-1e4, 1e4), "eps_ttm": (-1e5, 1e5), "pb": (0.0, 1e4),
    "div_yield": (0.0, 100.0), "turnover": (0.0, 1000.0), "amplitude": (0.0, 1000.0),
    "w52_high": (0.0, 1e7), "w52_low": (0.0, 1e7),
    "shares_total": (0.0, 1e15), "shares_float": (0.0, 1e15),
    "market_cap": (0.0, 1e15), "market_cap_float": (0.0, 1e15),
}


def _num(parts: list[str], idx: int) -> float | None:
    """取第 idx 段并转 float；空串/非数字返回 None。"""
    try:
        if idx < len(parts) and parts[idx] not in ("", "-"):
            return float(parts[idx])
    except (ValueError, IndexError):
        pass
    return None


def batch_fields(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """腾讯批量行情：一次请求拿回中文名 / 市值 / 估值等全部已确认字段。

    返回 {symbol: {"name_cn": str, "market_cap": 美元(总市值), "pe_ttm": float|None, ...}}。
    字段口径见模块顶部 `_F` 注释；已用 148 只样本算术自证（见 tools/_probe_tencent_fields.py）。
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
                row: dict[str, Any] = {}
                for key, idx in _F.items():
                    if key in ("name_cn", "name_en"):
                        row[key] = parts[idx] if idx < len(parts) else ""
                        continue
                    val = _num(parts, idx)
                    if val is not None and key in _CAP_KEYS:
                        val *= 1e8                     # 亿美元 → 美元
                    lo, hi = _BOUNDS.get(key, (None, None))
                    if val is not None and lo is not None and not (lo <= val <= hi):
                        val = None
                    row[key] = val
                out[sym] = row
    except Exception:  # noqa: BLE001 —— 名称/市值拉取失败不影响主流程
        pass
    return out


# 兼容旧调用名（模块内两处）；新代码请直接用 batch_fields。
_tencent_batch = batch_fields

# enrich 补拉冷却（防止欠账窗口期每次请求都同步卡 2s+ / 后台线程风暴）
_enrich_sync_last = 0.0
_enrich_bg_last = 0.0


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
    """中文名 + 总市值（美元）。落库缓存（含负缓存，见 names_cn）。

    ⚠️ 缺失标的的补拉**同步只做一批（≤50 只 ≈ 3s）**，其余转后台线程 ——
    扩池到 940 只的首次请求 missing 有 374 只，全量同步要 ~43s，正好是
    「打开榜单慢」的另一个根因。后台补完即落库，下一次请求自然生效。

    ⚠️ 同步补拉有 60s 冷却：欠账未清的窗口期（刚扩池 / 手动加票）里，
    如果每次请求都同步补一批，页面会连续几十秒每次都卡 2s+。冷却期内
    missing 全部转后台 —— 中文名晚几分钟出现完全可接受。
    """
    global _enrich_sync_last, _enrich_bg_last
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
        # ---- 同步补拉：60s 冷却，冷却外只补第一批（≤50 只 ≈ 3s）----
        sync_now = missing[:50] if (time.time() - _enrich_sync_last >= 60) else []
        if sync_now:
            _enrich_sync_last = time.time()
            fetched = _tencent_batch(sync_now)
            with session_scope() as s2:
                for sym in sync_now:
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
        # ---- 其余全部转后台（写库即生效，不阻塞响应）；300s 冷却防线程风暴 ----
        synced = set(sync_now)
        bg_list = [x for x in missing if x not in synced]
        if bg_list and (time.time() - _enrich_bg_last >= 300):
            _enrich_bg_last = time.time()

            def _bg_fill() -> None:
                try:
                    fetched = _tencent_batch(bg_list)
                    with session_scope() as s2:
                        for sym in bg_list:
                            info = fetched.get(sym) or {}
                            row = s2.get(CompanyProfile, sym)
                            if row:
                                row.name_cn = info.get("name_cn") or row.name_cn
                                if info.get("market_cap"):
                                    row.market_cap = info["market_cap"]
                            else:
                                s2.add(CompanyProfile(symbol=sym, name_cn=info.get("name_cn") or "",
                                                      market_cap=info.get("market_cap") or 0.0))
                except Exception:  # noqa: BLE001 —— 后台补拉失败就等下次触发
                    pass

            threading.Thread(target=_bg_fill, daemon=True, name="company-enrich-bg").start()
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
