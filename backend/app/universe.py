"""美股榜单标的池：S&P 500 + NASDAQ 100 + S&P MidCap 400 + S&P SmallCap 600
+ Nasdaq screener 市值前 700（指数外补充）+ 精选热门股。

为什么扩到 ~2200
----------------
用户一路从 940 → 1500 → 2000+：S&P 三指数 + NDX100 去重后 ~1541 只，第五源
从 Nasdaq 官方 screener（全美股 ~7000 只，带市值/行业）按市值补 700 只
（≥$300M，去重后最低 ~$2.7B，全是指数外中大盘），总数 ≈ 2241。
`rankings.constituents()` 委托本模块，下游（行情/估值/技术面/信号）完全无感。

行业分类归一化
--------------
S&P 系快照用 GICS Sector，NASDAQ 100 词条用 ICB。PE 分位**按行业分组**、
前端行业筛选也吃这个字段 —— 两组名称必须对齐，否则非 SP500 的票会掉进
小分组（样本 <5 → 没有分位 → 估值评分退化）。加载时统一映射到 GICS 名称。

刷新策略
--------
四个指数快照都是「内置 json 兜底 + 7 天 Wikipedia 刷新（失败静默用快照）」。
解析用标准库 html.parser（本环境没有 lxml，pandas.read_html 不可用 ——
现有 sp500 刷新静默失败多年就是这个原因）。

⚠️ 全池 ~2200 只的代价（全部在后台、被快照兜底，不影响首屏）：
    · 行情刷新 ~2min（TTL 10min）；估值 ~2min（TTL 30min）；技术面 ~6min（TTL 1h）
    · 预热全量 ~8 分钟，期间新增标的逐步出现，快照保证页面始终完整
"""
from __future__ import annotations

import json
import re
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import CACHE_DIR

SNAP_DIR = Path(__file__).resolve().parent / "markets"
_SP500 = SNAP_DIR / "sp500.json"
_NDX100 = SNAP_DIR / "nasdaq100.json"
_SP400 = SNAP_DIR / "sp400.json"
_SP600 = SNAP_DIR / "sp600.json"
_MCAP_EXTRA = SNAP_DIR / "mcap_extra.json"
_REFRESH_TTL = 7 * 86400

# ICB / 杂项名称 → GICS Sector（榜单全局统一用 GICS 名称分组）
_SECTOR_MAP = {
    "technology": "Information Technology",
    "communication": "Communication Services",
    "communication services": "Communication Services",
    "telecommunications": "Communication Services",
    "consumer discretionary": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "financials": "Financials",
    "financial services": "Financials",
    "industrials": "Industrials",
    "basic materials": "Materials",
    "materials": "Materials",
    "energy": "Energy",
    "oil & gas": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
    # Nasdaq screener 的 sector 口径（mcap_extra 源）
    "finance": "Financials",
    "miscellaneous": "",
}

# 精选热门股：不在两大指数内、但用户（美股/中概交易者）大概率会找的标的。
# ⚠️ 只收高流动性大票 —— 冷门票腾讯没有估值数据、yfinance 偶尔缺行情，
# 放进来只会给榜单添一堆「—」。sector 手写 GICS 名称。
EXTRA_STOCKS: list[dict[str, str]] = [
    {"symbol": "BABA", "name": "Alibaba Group", "sector": "Consumer Discretionary", "sub_sector": "Broadline Retail"},
    {"symbol": "PDD", "name": "PDD Holdings (Pinduoduo)", "sector": "Consumer Discretionary", "sub_sector": "Broadline Retail"},
    {"symbol": "JD", "name": "JD.com", "sector": "Consumer Discretionary", "sub_sector": "Broadline Retail"},
    {"symbol": "BIDU", "name": "Baidu", "sector": "Communication Services", "sub_sector": "Interactive Media"},
    {"symbol": "NTES", "name": "NetEase", "sector": "Communication Services", "sub_sector": "Gaming"},
    {"symbol": "TCOM", "name": "Trip.com Group", "sector": "Consumer Discretionary", "sub_sector": "Travel Services"},
    {"symbol": "TME", "name": "Tencent Music", "sector": "Communication Services", "sub_sector": "Entertainment"},
    {"symbol": "BILI", "name": "Bilibili", "sector": "Communication Services", "sub_sector": "Entertainment"},
    {"symbol": "VIPS", "name": "Vipshop", "sector": "Consumer Discretionary", "sub_sector": "Broadline Retail"},
    {"symbol": "NIO", "name": "NIO Inc.", "sector": "Consumer Discretionary", "sub_sector": "Automobiles"},
    {"symbol": "LI", "name": "Li Auto", "sector": "Consumer Discretionary", "sub_sector": "Automobiles"},
    {"symbol": "XPEV", "name": "XPeng", "sector": "Consumer Discretionary", "sub_sector": "Automobiles"},
    {"symbol": "TSM", "name": "Taiwan Semiconductor ADR", "sector": "Information Technology", "sub_sector": "Semiconductors"},
    {"symbol": "SHOP", "name": "Shopify", "sector": "Information Technology", "sub_sector": "Software"},
    {"symbol": "SE", "name": "Sea Limited", "sector": "Consumer Discretionary", "sub_sector": "Entertainment"},
    {"symbol": "HOOD", "name": "Robinhood Markets", "sector": "Financials", "sub_sector": "Capital Markets"},
    {"symbol": "SOFI", "name": "SoFi Technologies", "sector": "Financials", "sub_sector": "Consumer Finance"},
    {"symbol": "COIN", "name": "Coinbase Global", "sector": "Financials", "sub_sector": "Capital Markets"},
    {"symbol": "MSTR", "name": "MicroStrategy (Strategy)", "sector": "Information Technology", "sub_sector": "Software"},
    {"symbol": "RBLX", "name": "Roblox", "sector": "Communication Services", "sub_sector": "Entertainment"},
    {"symbol": "SNOW", "name": "Snowflake", "sector": "Information Technology", "sub_sector": "Software"},
    {"symbol": "NET", "name": "Cloudflare", "sector": "Information Technology", "sub_sector": "Software"},
    {"symbol": "ROKU", "name": "Roku", "sector": "Communication Services", "sub_sector": "Entertainment"},
    {"symbol": "DKNG", "name": "DraftKings", "sector": "Consumer Discretionary", "sub_sector": "Casinos & Gaming"},
    {"symbol": "FSLR", "name": "First Solar", "sector": "Information Technology", "sub_sector": "Semiconductors & Equipment"},
    {"symbol": "FUTU", "name": "Futu Holdings (moomoo)", "sector": "Financials", "sub_sector": "Capital Markets"},
    {"symbol": "ZTO", "name": "ZTO Express", "sector": "Industrials", "sub_sector": "Air Freight & Logistics"},
    {"symbol": "BEKE", "name": "KE Holdings (Beike)", "sector": "Real Estate", "sub_sector": "Real Estate Services"},
    {"symbol": "YUMC", "name": "Yum China", "sector": "Consumer Discretionary", "sub_sector": "Restaurants"},
]

_lock = threading.Lock()
_merged: dict[str, Any] | None = None
_loaded_at = 0.0
_ndx_state: dict[str, Any] = {"last": 0.0, "ok": None}
_sp400_state: dict[str, Any] = {"last": 0.0, "ok": None}
_sp600_state: dict[str, Any] = {"last": 0.0, "ok": None}
_mcap_extra_state: dict[str, Any] = {"last": 0.0, "ok": None}


def _norm_sector(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    key = s.lower()
    if key in _SECTOR_MAP:
        return _SECTOR_MAP[key]  # 命中（含映射为空串的 miscellaneous）直接用
    # 已是 GICS 名称或接近 GICS 名称的原样返回；完全不认识的保留原文
    # （宁可分组粗一点，也不要把票丢进「无行业」组失去分位）
    return s


def _load_json(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cons = data.get("constituents") or []
        return cons if isinstance(cons, list) else []
    except Exception:  # noqa: BLE001 —— 快照损坏时用另一来源兜底，不让整页 500
        return []


def _merge() -> dict[str, Any]:
    """六源去重合并。同代码以 S&P 500 优先（它的 GICS sector 口径最权威）。

    优先级（低 → 高）：mcap_extra < 精选热门股 < 四大指数 —— 即 Nasdaq 市值源
    只负责填指数覆盖不到的空隙，精选股的手写 sector 也压过 screener 口径。
    """
    out: dict[str, dict[str, Any]] = {}
    src: dict[str, str] = {}
    for path, tag in (
        (_SP500, "sp500"), (_NDX100, "ndx100"), (_SP400, "sp400"),
        (_SP600, "sp600"), (_MCAP_EXTRA, "mcap_extra"),
    ):
        for c in _load_json(path):
            sym = str(c.get("symbol") or "").strip().upper()
            if not sym or sym in out:
                continue
            out[sym] = {
                "symbol": sym,
                "name": str(c.get("name") or ""),
                "sector": _norm_sector(str(c.get("sector") or "")),
                "sub_sector": str(c.get("sub_sector") or ""),
            }
            src[sym] = tag
    for c in EXTRA_STOCKS:
        sym = c["symbol"]
        if sym not in out:
            out[sym] = dict(c)
            src[sym] = "extra"
    cons = list(out.values())
    return {
        "updated": time.strftime("%Y-%m-%d"),
        "count": len(cons),
        "constituents": cons,
        "sources": {
            "sp500": sum(1 for v in src.values() if v == "sp500"),
            "ndx100": sum(1 for v in src.values() if v == "ndx100"),
            "sp400": sum(1 for v in src.values() if v == "sp400"),
            "sp600": sum(1 for v in src.values() if v == "sp600"),
            "mcap_extra": sum(1 for v in src.values() if v == "mcap_extra"),
            "extra": sum(1 for v in src.values() if v == "extra"),
        },
    }


def universe() -> dict[str, Any]:
    """合并后的标的池（内存缓存；重启后首次调用读三份 json，<10ms）。"""
    global _merged, _loaded_at
    with _lock:
        if _merged is not None:
            return _merged
        _merged = _merge()
        _loaded_at = time.time()
        return _merged


# ---------------- 指数成分刷新（7 天，失败静默用内置快照） ----------------
class _WikiTableParser(HTMLParser):
    """提取维基页面全部 <table> 的行列文本（标准库实现，环境无 lxml 也能跑）。

    ⚠️ handle_data 必须容忍 `self._cells` 为空的情况：td 之间的换行/空白文本
    节点会触发它，`[-1] += data` 在空列表上会 IndexError（实测炸过一次刷新）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._rows: list[list[str]] | None = None
        self._cells: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cells.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._rows is not None:
            if self._rows:
                self.tables.append(self._rows)
            self._rows = None
        elif tag == "tr" and self._cells is not None:
            if self._cells:
                self._rows.append(self._cells)
            self._cells = None

    def handle_data(self, data: str) -> None:
        if self._cells is not None and self._cells:
            self._cells[-1] += data


def _parse_components(html: str, min_rows: int = 80) -> list[dict[str, str]]:
    """解析维基指数成分表。

    兼容两种表头：
      · GICS 系（List of S&P 500 / S&P 400 companies）：Symbol/Security/GICS Sector/…
      · ICB 系（List of NASDAQ-100 companies）：Ticker/Company/ICB/Industry
    Company 名带括号（Alphabet Inc. (Class A)）会多拆一个 td 使分类列错位 ——
    sector 位上是不认识的值 → 置空；分类词跑进 sub → 顶回 sector。
    """
    p = _WikiTableParser()
    p.feed(html)
    for rows in p.tables:
        if not rows:
            continue
        header = [re.sub(r"\s+", " ", c).strip() for c in rows[0]]
        ti = next((i for i, h in enumerate(header) if h.lower() in ("ticker", "symbol")), None)
        ni = next((i for i, h in enumerate(header) if h.lower() in ("company", "security")), None)
        # ⚠️ NDX100 词条的表头是 "ICB Industry[1]"（带引用角标），必须子串匹配；
        # 等值匹配会让 si=None → 整表被跳过 → 静默解析出 0 只。
        si = next((i for i, h in enumerate(header) if "icb" in h.lower() or "gics sector" in h.lower()), None)
        if ti is None or ni is None or si is None:
            continue
        # 合法 sector = ICB 短名（map keys）∪ GICS 全名（map values）——
        # SP400 页面给的就是 GICS 全名（"Information Technology"），
        # 只认 keys 会把 49 只合法值误清空（实测踩过）。
        valid = set(_SECTOR_MAP) | {v.lower() for v in _SECTOR_MAP.values()}
        out = []
        for r in rows[1:]:
            def cell(i: int | None) -> str:
                if i is None or i >= len(r):
                    return ""
                return re.sub(r"\s+", " ", r[i]).strip()

            sym = cell(ti).replace(".", "-")
            if not sym or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", sym):
                continue
            sector = cell(si)
            sub = cell(si + 1)
            if sector and sector.lower() not in valid:
                sector = ""
            if not sector and sub.lower() in valid:
                sector, sub = sub, ""
            if not sector:
                # 行内错位兜底（Security 名带括号/逗号会多拆 td）：从本行
                # si 位起扫第一个分类词；分类词后面那格是 sub-industry。
                found = next((j for j in range(si, len(r))
                              if r[j].strip().lower() in valid), None)
                if found is not None:
                    sector = re.sub(r"\s+", " ", r[found]).strip()
                    sub = re.sub(r"\s+", " ", r[found + 1]).strip() if found + 1 < len(r) else ""
            out.append({"symbol": sym, "name": cell(ni), "sector": sector, "sub_sector": sub})
        if len(out) >= min_rows:
            return out
    return []


def _refresh_index(url: str, path: Path, min_rows: int, source: str,
                   state: dict[str, Any], force: bool) -> dict[str, Any]:
    if not force and time.time() - state["last"] < _REFRESH_TTL:
        return {"refreshed": False, "reason": "ttl"}
    state["last"] = time.time()
    try:
        import requests

        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        rows = _parse_components(r.text, min_rows=min_rows)
        if len(rows) < min_rows:
            raise ValueError(f"解析出 {len(rows)} 只，低于安全阈值 {min_rows}")
        data = {
            "updated": time.strftime("%Y-%m-%d"),
            "source": source,
            "count": len(rows),
            "constituents": rows,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        global _merged
        with _lock:
            _merged = None          # 下次 universe() 重新合并
        state["ok"] = True
        return {"refreshed": True, "count": len(rows)}
    except Exception as exc:  # noqa: BLE001
        state["ok"] = False
        state["error"] = f"{type(exc).__name__}: {exc}"[:160]
        return {"refreshed": False, "error": f"{type(exc).__name__}: {exc}"}


def refresh_ndx100(force: bool = False) -> dict[str, Any]:
    """NASDAQ 100：组件表在独立词条（主页面 2024 年起只剩导航模板）。"""
    return _refresh_index(
        "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
        _NDX100, 80, "wikipedia List of NASDAQ-100 companies", _ndx_state, force,
    )


def refresh_sp400(force: bool = False) -> dict[str, Any]:
    """S&P MidCap 400（中盘，选股面的重要补充）。"""
    return _refresh_index(
        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        _SP400, 350, "wikipedia List of S&P 400 companies", _sp400_state, force,
    )


def refresh_sp600(force: bool = False) -> dict[str, Any]:
    """S&P SmallCap 600（小盘，扩池到 ~1500 的主要增量）。"""
    return _refresh_index(
        "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        _SP600, 550, "wikipedia List of S&P 600 companies", _sp600_state, force,
    )


# Nasdaq screener 市值补充源
_MC_URL = ("https://api.nasdaq.com/api/screener/stocks"
           "?tableonly=true&limit=25&download=true")
_MC_MIN_MCAP = 3e8        # $300M 以下不收：数据残缺率高，只会给榜单添「—」
_MC_TAKE = 700            # 补 700 只 → 池子 ~2240（指数源去重后 ~1541）
_MC_MIN_NEW = 500         # 安全阈值：去重后新增不足此数视为接口口径变化，放弃写入


def refresh_mcap_extra(force: bool = False) -> dict[str, Any]:
    """Nasdaq 官方 screener：按市值补充指数外标的（扩池 1500 → 2200+）。

    ⚠️ api.nasdaq.com 封锁 python TLS 指纹 —— requests 握手直接被掐
    （SSLError/10053，走不走代理都一样），必须用 subprocess curl
    （Windows 10+ 自带，代理走环境变量 HTTP(S)_PROXY）。
    失败静默：快照兜底，只影响新票出现，不影响已有数据。
    """
    if not force and time.time() - _mcap_extra_state["last"] < _REFRESH_TTL:
        return {"refreshed": False, "reason": "ttl"}
    _mcap_extra_state["last"] = time.time()
    try:
        import subprocess

        r = subprocess.run(
            ["curl", "-s", "--max-time", "60",
             "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
             "-H", "Accept: application/json, text/plain, */*",
             _MC_URL],
            capture_output=True, text=True, timeout=90,
        )
        if r.returncode != 0:
            raise ValueError(f"curl exit {r.returncode}: {(r.stderr or '')[:120]}")
        rows = ((json.loads(r.stdout).get("data") or {}).get("rows")) or []
        existing = {c["symbol"] for c in universe()["constituents"]}
        out: list[dict[str, Any]] = []
        for row in rows:
            sym = str(row.get("symbol") or "").strip().upper().replace(".", "-")
            if not sym or sym in existing:
                continue
            if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", sym):
                continue
            try:
                mcv = float(str(row.get("marketCap") or "").replace(",", ""))
            except ValueError:
                continue
            if mcv < _MC_MIN_MCAP:
                continue
            out.append({"_mc": mcv, "symbol": sym,
                        "name": str(row.get("name") or "").strip(),
                        "sector": _norm_sector(str(row.get("sector") or "")),
                        "sub_sector": str(row.get("industry") or "").strip()})
        out.sort(key=lambda c: -c["_mc"])
        cons = [{k: v for k, v in c.items() if k != "_mc"} for c in out[:_MC_TAKE]]
        if len(cons) < _MC_MIN_NEW:
            raise ValueError(f"去重后仅 {len(cons)} 只，低于安全阈值 {_MC_MIN_NEW}")
        data = {
            "updated": time.strftime("%Y-%m-%d"),
            "source": "nasdaq screener top by market cap",
            "count": len(cons),
            "constituents": cons,
        }
        tmp = _MCAP_EXTRA.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_MCAP_EXTRA)   # 原子替换，不留半截文件
        global _merged
        with _lock:
            _merged = None
        _mcap_extra_state["ok"] = True
        return {"refreshed": True, "count": len(cons)}
    except Exception as exc:  # noqa: BLE001
        _mcap_extra_state["ok"] = False
        _mcap_extra_state["error"] = f"{type(exc).__name__}: {exc}"[:160]
        return {"refreshed": False, "error": f"{type(exc).__name__}: {exc}"}


def maybe_refresh_async() -> None:
    """启动时后台尝试刷新四个动态源（7 天 TTL，不阻塞、失败静默）。"""
    threading.Thread(
        target=lambda: (refresh_ndx100(), refresh_sp400(), refresh_sp600(),
                        refresh_mcap_extra()),
        daemon=True, name="universe-refresh",
    ).start()
