"""
行情数据层
===========
三级数据源自动降级，保证「永远有数据可跑」：
    1) yfinance   —— 首选，日线/周线/小时线
    2) Stooq CSV  —— 纯 HTTP，无需 key，日线兜底
    3) Synthetic  —— 确定性合成行情（按 symbol 哈希播种），离线演示/自检用

所有返回统一为 DataFrame(index=DatetimeIndex, columns=[open,high,low,close,volume])
且 index 单调递增、无重复、无 NaN 的交易日序列。
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import io
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx
import numpy as np
import pandas as pd

from .config import CACHE_DIR, settings

OHLCV = ["open", "high", "low", "close", "volume"]

_TTL = {"1d": 6 * 3600, "1wk": 12 * 3600, "1h": 1800, "30m": 900, "15m": 600, "5m": 300, "1m": 60}
# 缓存覆盖度容差（天）：缓存起始日必须不晚于「请求起始日 + 容差」，否则视为未命中
_COVER_TOL = {"1d": 7, "1wk": 14, "1h": 3, "30m": 2, "15m": 1, "5m": 1, "1m": 1}
# 单标的缓存上限行数（防止长期运行后 CSV 无限膨胀）
_CACHE_MAX_ROWS = {"1d": 6000, "1wk": 1500, "1h": 8000, "30m": 8000, "15m": 8000, "5m": 8000, "1m": 2000}


# ------------------------------------------------------------------
# 符号宇宙（用于搜索联想）
# ------------------------------------------------------------------
@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    kind: str  # ETF | STOCK | INDEX


UNIVERSE: list[SymbolInfo] = [
    SymbolInfo("SPY", "SPDR S&P 500 ETF Trust", "ETF"),
    SymbolInfo("QQQ", "Invesco QQQ Trust (Nasdaq 100)", "ETF"),
    SymbolInfo("IWM", "iShares Russell 2000 ETF", "ETF"),
    SymbolInfo("DIA", "SPDR Dow Jones Industrial Average ETF", "ETF"),
    SymbolInfo("VTI", "Vanguard Total Stock Market ETF", "ETF"),
    SymbolInfo("VOO", "Vanguard S&P 500 ETF", "ETF"),
    SymbolInfo("SMH", "VanEck Semiconductor ETF", "ETF"),
    SymbolInfo("SOXX", "iShares Semiconductor ETF", "ETF"),
    SymbolInfo("XLK", "Technology Select Sector SPDR", "ETF"),
    SymbolInfo("XLF", "Financial Select Sector SPDR", "ETF"),
    SymbolInfo("XLE", "Energy Select Sector SPDR", "ETF"),
    SymbolInfo("XLV", "Health Care Select Sector SPDR", "ETF"),
    SymbolInfo("XLI", "Industrial Select Sector SPDR", "ETF"),
    SymbolInfo("XLP", "Consumer Staples Select Sector SPDR", "ETF"),
    SymbolInfo("XLY", "Consumer Discretionary Select Sector SPDR", "ETF"),
    SymbolInfo("XLU", "Utilities Select Sector SPDR", "ETF"),
    SymbolInfo("XLB", "Materials Select Sector SPDR", "ETF"),
    SymbolInfo("XLRE", "Real Estate Select Sector SPDR", "ETF"),
    SymbolInfo("GLD", "SPDR Gold Shares", "ETF"),
    SymbolInfo("SLV", "iShares Silver Trust", "ETF"),
    SymbolInfo("USO", "United States Oil Fund", "ETF"),
    SymbolInfo("TLT", "iShares 20+ Year Treasury Bond ETF", "ETF"),
    SymbolInfo("IEF", "iShares 7-10 Year Treasury Bond ETF", "ETF"),
    SymbolInfo("HYG", "iShares High Yield Corporate Bond ETF", "ETF"),
    SymbolInfo("LQD", "iShares Investment Grade Corporate Bond ETF", "ETF"),
    SymbolInfo("EEM", "iShares MSCI Emerging Markets ETF", "ETF"),
    SymbolInfo("EFA", "iShares MSCI EAFE ETF", "ETF"),
    SymbolInfo("FXI", "iShares China Large-Cap ETF", "ETF"),
    SymbolInfo("KWEB", "KraneShares CSI China Internet ETF", "ETF"),
    SymbolInfo("ARKK", "ARK Innovation ETF", "ETF"),
    SymbolInfo("TQQQ", "ProShares UltraPro QQQ (3x)", "ETF"),
    SymbolInfo("SOXL", "Direxion Daily Semiconductor Bull 3X", "ETF"),
    SymbolInfo("UVXY", "ProShares Ultra VIX Short-Term Futures", "ETF"),
    SymbolInfo("VIXY", "ProShares VIX Short-Term Futures ETF", "ETF"),
    SymbolInfo("IBIT", "iShares Bitcoin Trust ETF", "ETF"),
    SymbolInfo("AAPL", "Apple Inc.", "STOCK"),
    SymbolInfo("MSFT", "Microsoft Corporation", "STOCK"),
    SymbolInfo("NVDA", "NVIDIA Corporation", "STOCK"),
    SymbolInfo("AMZN", "Amazon.com, Inc.", "STOCK"),
    SymbolInfo("GOOGL", "Alphabet Inc. Class A", "STOCK"),
    SymbolInfo("META", "Meta Platforms, Inc.", "STOCK"),
    SymbolInfo("TSLA", "Tesla, Inc.", "STOCK"),
    SymbolInfo("AVGO", "Broadcom Inc.", "STOCK"),
    SymbolInfo("AMD", "Advanced Micro Devices, Inc.", "STOCK"),
    SymbolInfo("NFLX", "Netflix, Inc.", "STOCK"),
    SymbolInfo("CRM", "Salesforce, Inc.", "STOCK"),
    SymbolInfo("ORCL", "Oracle Corporation", "STOCK"),
    SymbolInfo("ADBE", "Adobe Inc.", "STOCK"),
    SymbolInfo("INTC", "Intel Corporation", "STOCK"),
    SymbolInfo("MU", "Micron Technology, Inc.", "STOCK"),
    SymbolInfo("QCOM", "QUALCOMM Incorporated", "STOCK"),
    SymbolInfo("TSM", "Taiwan Semiconductor Manufacturing (ADR)", "STOCK"),
    SymbolInfo("ASML", "ASML Holding N.V. (ADR)", "STOCK"),
    SymbolInfo("ARM", "Arm Holdings plc (ADR)", "STOCK"),
    SymbolInfo("PLTR", "Palantir Technologies Inc.", "STOCK"),
    SymbolInfo("COIN", "Coinbase Global, Inc.", "STOCK"),
    SymbolInfo("MSTR", "MicroStrategy Incorporated", "STOCK"),
    SymbolInfo("UBER", "Uber Technologies, Inc.", "STOCK"),
    SymbolInfo("ABNB", "Airbnb, Inc.", "STOCK"),
    SymbolInfo("SHOP", "Shopify Inc.", "STOCK"),
    SymbolInfo("SQ", "Block, Inc.", "STOCK"),
    SymbolInfo("PYPL", "PayPal Holdings, Inc.", "STOCK"),
    SymbolInfo("JPM", "JPMorgan Chase & Co.", "STOCK"),
    SymbolInfo("BAC", "Bank of America Corporation", "STOCK"),
    SymbolInfo("GS", "The Goldman Sachs Group, Inc.", "STOCK"),
    SymbolInfo("MS", "Morgan Stanley", "STOCK"),
    SymbolInfo("V", "Visa Inc.", "STOCK"),
    SymbolInfo("MA", "Mastercard Incorporated", "STOCK"),
    SymbolInfo("BRK-B", "Berkshire Hathaway Inc. Class B", "STOCK"),
    SymbolInfo("UNH", "UnitedHealth Group Incorporated", "STOCK"),
    SymbolInfo("LLY", "Eli Lilly and Company", "STOCK"),
    SymbolInfo("JNJ", "Johnson & Johnson", "STOCK"),
    SymbolInfo("PFE", "Pfizer Inc.", "STOCK"),
    SymbolInfo("MRK", "Merck & Co., Inc.", "STOCK"),
    SymbolInfo("ABBV", "AbbVie Inc.", "STOCK"),
    SymbolInfo("TMO", "Thermo Fisher Scientific Inc.", "STOCK"),
    SymbolInfo("ISRG", "Intuitive Surgical, Inc.", "STOCK"),
    SymbolInfo("XOM", "Exxon Mobil Corporation", "STOCK"),
    SymbolInfo("CVX", "Chevron Corporation", "STOCK"),
    SymbolInfo("COP", "ConocoPhillips", "STOCK"),
    SymbolInfo("OXY", "Occidental Petroleum Corporation", "STOCK"),
    SymbolInfo("WMT", "Walmart Inc.", "STOCK"),
    SymbolInfo("COST", "Costco Wholesale Corporation", "STOCK"),
    SymbolInfo("HD", "The Home Depot, Inc.", "STOCK"),
    SymbolInfo("MCD", "McDonald's Corporation", "STOCK"),
    SymbolInfo("NKE", "NIKE, Inc.", "STOCK"),
    SymbolInfo("SBUX", "Starbucks Corporation", "STOCK"),
    SymbolInfo("PG", "The Procter & Gamble Company", "STOCK"),
    SymbolInfo("KO", "The Coca-Cola Company", "STOCK"),
    SymbolInfo("PEP", "PepsiCo, Inc.", "STOCK"),
    SymbolInfo("DIS", "The Walt Disney Company", "STOCK"),
    SymbolInfo("BA", "The Boeing Company", "STOCK"),
    SymbolInfo("CAT", "Caterpillar Inc.", "STOCK"),
    SymbolInfo("GE", "GE Aerospace", "STOCK"),
    SymbolInfo("DE", "Deere & Company", "STOCK"),
    SymbolInfo("F", "Ford Motor Company", "STOCK"),
    SymbolInfo("GM", "General Motors Company", "STOCK"),
    SymbolInfo("RIVN", "Rivian Automotive, Inc.", "STOCK"),
    SymbolInfo("LCID", "Lucid Group, Inc.", "STOCK"),
    SymbolInfo("NIO", "NIO Inc. (ADR)", "STOCK"),
    SymbolInfo("BABA", "Alibaba Group Holding (ADR)", "STOCK"),
    SymbolInfo("PDD", "PDD Holdings Inc. (ADR)", "STOCK"),
    SymbolInfo("JD", "JD.com, Inc. (ADR)", "STOCK"),
    SymbolInfo("TCEHY", "Tencent Holdings (ADR)", "STOCK"),
    SymbolInfo("^GSPC", "S&P 500 Index", "INDEX"),
    SymbolInfo("^NDX", "Nasdaq 100 Index", "INDEX"),
    SymbolInfo("^DJI", "Dow Jones Industrial Average", "INDEX"),
    SymbolInfo("^VIX", "CBOE Volatility Index", "INDEX"),
    SymbolInfo("^TNX", "CBOE 10-Year Treasury Note Yield", "INDEX"),
    # T-134：加密与外汇（只读行情，仅供看板/分析；不在交易白名单）
    SymbolInfo("BTC-USD", "Bitcoin (USD)", "CRYPTO"),
    SymbolInfo("ETH-USD", "Ethereum (USD)", "CRYPTO"),
    SymbolInfo("EURUSD=X", "Euro / US Dollar", "FX"),
]

UNIVERSE_MAP = {s.symbol: s for s in UNIVERSE}

# ------------------------------------------------------------------
# 全市场搜索（Yahoo search API 兜底）：本地 UNIVERSE 是精选集（S&P 500 + 常用
# ETF/港股/指数），覆盖不了全市场——搜 SPCX（SpaceX）之类的新上市标的必须联网搜。
# 带 10 分钟 TTL 缓存 + 失败静默降级（本地结果兜底）。
# ------------------------------------------------------------------
_yahoo_search_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_YAHOO_SEARCH_TTL = 600.0

_KIND_MAP = {
    "EQUITY": "STK", "ETF": "ETF", "INDEX": "IDX", "CRYPTOCURRENCY": "CRYPTO",
    "FUTURE": "FUT", "OPTION": "OPT", "CURRENCY": "FX", "MUTUALFUND": "FUND",
}


def _yahoo_search(q: str, limit: int) -> list[dict[str, str]]:
    """Yahoo Finance 全市场搜索（股票/ETF/指数/加密，无需 key）。失败返回空。"""
    key = f"{q.upper()}|{limit}"
    now = time.time()
    hit = _yahoo_search_cache.get(key)
    if hit and now - hit[0] < _YAHOO_SEARCH_TTL:
        return hit[1]
    out: list[dict[str, str]] = []
    try:
        r = httpx.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": limit, "newsCount": 0, "listsCount": 0},
            headers={"User-Agent": "Mozilla/5.0 QuantDesk"},
            timeout=8,
        )
        r.raise_for_status()
        for qt in (r.json().get("quotes") or [])[:limit]:
            sym = str(qt.get("symbol") or "").strip()
            if not sym:
                continue
            kind = _KIND_MAP.get(str(qt.get("quoteType") or ""), "STK")
            name = str(qt.get("longname") or qt.get("shortname") or "")
            exch = str(qt.get("exchDisp") or qt.get("exchange") or "")
            out.append({"symbol": sym, "name": f"{name} [{exch}]" if exch else name, "kind": kind})
        _yahoo_search_cache[key] = (now, out)
    except Exception as exc:  # noqa: BLE001 —— 搜索失败静默，本地结果兜底
        _last_errors["yahoo-search"] = f"{type(exc).__name__}: {exc}"[:160]
        _yahoo_search_cache[key] = (now, [])
    return _yahoo_search_cache[key][1]


def search_symbols(q: str, limit: int = 20) -> list[dict[str, str]]:
    """标的搜索：本地 UNIVERSE 命中排前，Yahoo 全市场结果补充（去重）。"""
    q_raw = (q or "").strip()
    q = q_raw.upper()
    if not q:
        return [{"symbol": s.symbol, "name": s.name, "kind": s.kind} for s in UNIVERSE[:limit]]
    scored: list[tuple[int, SymbolInfo]] = []
    for s in UNIVERSE:
        sym, nm = s.symbol.upper(), s.name.upper()
        if sym == q:
            scored.append((0, s))
        elif sym.startswith(q):
            scored.append((1, s))
        elif q in sym:
            scored.append((2, s))
        elif q_raw.upper() in nm:
            scored.append((3, s))
    scored.sort(key=lambda x: (x[0], len(x[1].symbol)))
    local = [{"symbol": s.symbol, "name": s.name, "kind": s.kind} for _, s in scored[:limit]]
    # 全市场兜底（q 长度 ≥ 2 才联网，单字符结果太多没意义）
    remote: list[dict[str, str]] = []
    if len(q_raw) >= 2:
        seen = {x["symbol"] for x in local}
        for r in _yahoo_search(q_raw, limit):
            if r["symbol"] not in seen:
                remote.append(r)
    return (local + remote)[:limit]


# ------------------------------------------------------------------
# 缓存
# ------------------------------------------------------------------
def _cache_path(symbol: str, interval: str) -> "PathLike":  # type: ignore[name-defined]
    safe = symbol.replace("^", "IDX_").replace("/", "_").replace("\\", "_")
    d = CACHE_DIR / interval
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.csv"


# P1-5：按缓存文件路径分锁 —— 并发写同一 CSV 时避免半截文件与「读-合并-写」丢更新。
_cache_locks: dict[str, threading.Lock] = {}


def _cache_lock(path: Any) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lk = _cache_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _cache_locks[key] = lk
        return lk


def _read_cache(
    symbol: str, interval: str, ttl: int,
    start: str | None = None, end: str | None = None,
    ignore_ttl: bool = False,
) -> pd.DataFrame | None:
    """读缓存。**必须校验覆盖度**。

    历史缺陷：缓存只按 TTL 判断新鲜度，不看请求区间。一旦先用短区间（如 2024 起）
    填充过缓存，之后请求 2019 起的数据会直接命中这份短缓存并返回 ——
    回测和优化器于是静默地在错误的时间区间上计算。
    ignore_ttl=True 时跳过新鲜度检查（增量更新分支用：过期缓存仍可作合并基底）。
    """
    p = _cache_path(symbol, interval)
    if not p.exists():
        return None
    if not ignore_ttl and time.time() - p.stat().st_mtime > ttl:
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    try:
        df.index = pd.to_datetime(df.index)
    except Exception:
        return None

    tol = _COVER_TOL.get(interval, 7)
    if start:
        try:
            want = pd.to_datetime(start)
            if df.index.min() > want + pd.Timedelta(days=tol):
                return None                      # 缓存起点晚于请求区间 → 未命中
        except Exception:
            pass
    if end:
        try:
            want_end = pd.to_datetime(end)
            if df.index.max() < want_end - pd.Timedelta(days=tol):
                return None
        except Exception:
            pass
    return df


def _write_cache(symbol: str, interval: str, df: pd.DataFrame) -> None:
    """写缓存；与已有内容合并，使覆盖区间随时间增长而不是被短区间覆盖掉。

    P1-5：**原子写**。旧实现直接 `merged.to_csv(path)`（先截断再写），并发场景下
    读者可能解析出半截文件；若截断恰好落在行边界，`read_csv` 还会「成功」返回
    缺尾部的短数据，被当成有效缓存长期复用。改为：同路径加锁 + 写临时文件后
    `Path.replace` 原子替换 —— 读方要么看到完整旧文件、要么看到完整新文件。
    """
    try:
        path = _cache_path(symbol, interval)
        with _cache_lock(path):
            merged = df
            if path.exists():
                try:
                    old = pd.read_csv(path, index_col=0, parse_dates=True)
                    if old is not None and not old.empty:
                        old.index = pd.to_datetime(old.index)
                        merged = pd.concat([old, df])
                        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                except Exception:
                    merged = df
            cap = _CACHE_MAX_ROWS.get(interval, 6000)
            if len(merged) > cap:
                merged = merged.iloc[-cap:]
            tmp = path.with_name(f"{path.name}.tmp{threading.get_ident()}")
            try:
                merged.to_csv(tmp)
                tmp.replace(path)          # 同盘 rename → 原子替换
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
    except Exception:
        pass


# ------------------------------------------------------------------
# 数据源
# ------------------------------------------------------------------
def _normalize(df: pd.DataFrame, naive_tz: str | None = "UTC") -> pd.DataFrame:
    """统一为「真实时刻的 NY naive」语义。

    naive_tz 语义（P1-1 幂等性配套）：
      * "UTC"（默认）—— naive 输入按 UTC 解释再转 NY（腾讯 m1 预转换的 UTC 序列依赖此语义）；
      * None         —— naive 输入已是 NY 墙钟时间，原样保留（幂等：重复调用不再漂移）；
      * aware 输入    —— 无论 naive_tz 取值，一律 tz_convert 到 NY 后去 tz。
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=OHLCV)
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower().replace("adj close", "close") for c in df.columns]
    df = df.rename(columns={"adj_close": "close", "adjclose": "close"})
    for c in OHLCV:
        if c not in df.columns:
            if c == "volume":
                df["volume"] = 0.0
            elif c == "close":
                return pd.DataFrame(columns=OHLCV)
            else:
                df[c] = df["close"]
    df = df[OHLCV].apply(pd.to_numeric, errors="coerce")
    df.index = pd.to_datetime(df.index, utc=naive_tz is not None, errors="coerce")
    df = df[df.index.notna()]
    if naive_tz is not None:
        try:
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        except (TypeError, AttributeError):
            pass
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    df["volume"] = df["volume"].fillna(0.0)
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(df["close"])
    return df


def _from_yfinance(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    kw: dict = {"interval": interval, "auto_adjust": True, "actions": False}
    if interval == "1d":
        kw["start"] = start
        if end:
            kw["end"] = end
    else:
        # 1m 数据 Yahoo 只给近 7 天，请求 180d 会直接报错
        kw["period"] = {"1m": "5d", "5m": "60d", "15m": "60d", "30m": "60d"}.get(interval, "180d")
    df = ticker.history(**kw)
    return _normalize(df)


def _stooq_symbol(symbol: str) -> str:
    s = symbol.lower()
    if s.startswith("^"):
        return s
    return f"{s}.us"


def _from_stooq(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    """Stooq 免费日线 CSV。仅日线可用。"""
    d1 = start.replace("-", "")
    d2 = (end or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(symbol)}&d1={d1}&d2={d2}&i=d"
    with httpx.Client(timeout=settings.data_timeout_sec, follow_redirects=True) as c:
        r = c.get(url, headers={"User-Agent": "Mozilla/5.0 QuantDesk"})
    if r.status_code != 200 or "Date" not in r.text[:200]:
        return pd.DataFrame(columns=OHLCV)
    df = pd.read_csv(io.StringIO(r.text))
    if "Date" not in df.columns:
        return pd.DataFrame(columns=OHLCV)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    # P1-1 配套：Stooq 的日期是「交易日」本身（无时刻语义），不应被 UTC→NY 平移
    # 成前一天 20:00。naive_tz=None 让日期原样保留，同时保证幂等。
    return _normalize(df, naive_tz=None)


def _market_of(symbol: str) -> str:
    """判定标的市场（港股符号判断优先，失败回落后缀）。"""
    s = symbol.strip().upper()
    try:
        from .markets import symbols as mksym
        return mksym.parse(s).market
    except Exception:  # noqa: BLE001
        return "HK" if s.endswith(".HK") else "US"


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


def _from_finnhub(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    """Finnhub 美股日线备援（需要 key；免费档失败时返回空，让降级链继续）。"""
    from .config import settings as _s

    if interval != "1d" or _market_of(symbol) != "US" or not _s.finnhub_api_key:
        return pd.DataFrame(columns=OHLCV)
    d1 = start.replace("-", "")
    d2 = (end or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    url = (
        f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}"
        f"&from={d1}&to={d2}&resolution=D&token={_s.finnhub_api_key}"
    )
    try:
        with httpx.Client(timeout=settings.data_timeout_sec) as c:
            r = c.get(url)
        r.raise_for_status()
        data = r.json()
        if data.get("s") != "ok":
            return pd.DataFrame(columns=OHLCV)
        df = pd.DataFrame({
            "date": pd.to_datetime(data["t"], unit="s"),
            "open": data["o"], "high": data["h"],
            "low": data["l"], "close": data["c"], "volume": data["v"],
        }).set_index("date")
        return _normalize(df)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=OHLCV)


def _synthetic(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    """确定性合成行情：同一 symbol 永远生成同一序列，便于离线自检与演示。"""
    seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.now().normalize()
    start_ts = pd.Timestamp(start)
    freq = {"1d": "B", "1wk": "W-FRI", "1h": "h", "30m": "30min", "15m": "15min", "5m": "5min", "1m": "1min"}[interval]
    idx = pd.date_range(start_ts, end_ts, freq=freq)
    if len(idx) < 60:
        idx = pd.date_range(end_ts - pd.Timedelta(days=800), end_ts, freq=freq)
    n = len(idx)
    base = 30.0 + (seed % 400)
    drift = ((seed % 100) / 100.0 - 0.35) * 0.0004
    vol = 0.010 + (seed % 23) / 1000.0
    rets = rng.normal(drift, vol, n)
    # 叠加温和的均值回归与波动率聚集
    for i in range(1, n):
        rets[i] -= 0.06 * rets[i - 1]
    vol_series = np.abs(rng.normal(1.0, 0.25, n)).clip(0.4, 3.0)
    rets = rets * vol_series
    close = base * np.exp(np.cumsum(rets))
    intra = np.abs(rng.normal(0, vol, n)) * close
    open_ = np.concatenate([[close[0] * (1 - rets[0])], close[:-1]])
    high = np.maximum(open_, close) + intra * 0.6
    low = np.minimum(open_, close) - intra * 0.6
    volume = (rng.lognormal(15.5, 0.5, n)).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    ).pipe(_normalize)


# ------------------------------------------------------------------
# 数据源偏好与外部提供者注册
# ------------------------------------------------------------------
# 允许把券商（如 IBKR）注册为优先数据源。IBKR 的优势：
#   · 分钟级数据可回溯数年（免费源通常只给 60 天）
#   · 与实盘看到的价格完全一致，避免「回测用 A 源、交易用 B 源」的偏差
#
# 提供者需实现：
#   history(symbol, start, end, interval) -> DataFrame | None
#   snapshot(symbols) -> list[dict]      （可选）
_history_providers: dict[str, Any] = {}
_preferred: str | None = None


def register_history_provider(name: str, provider: Any) -> None:
    _history_providers[name] = provider


def available_providers() -> list[str]:
    return ["auto", *sorted(_history_providers.keys())]


def set_preferred(name: str | None) -> None:
    """设置全局优先数据源（None / 'auto' 表示走免费源链）。"""
    global _preferred
    _preferred = None if not name or name == "auto" else name


def get_preferred() -> str | None:
    return _preferred


def provider_status(name: str) -> dict:
    p = _history_providers.get(name)
    if p is None:
        return {"name": name, "available": False}
    try:
        st = getattr(p, "status", None)
        return st() if callable(st) else {"name": name, "available": True}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "available": False, "error": str(exc)[:120]}


# ------------------------------------------------------------------
# 并发治理：单飞（single-flight）+ 报价短缓存 + 失败原因记录
# ------------------------------------------------------------------
# 曾 symptom：「获取 GOOGL 行情失败」偶发。根因是前端一次标的切换并发打出
# history / indicators / snapshot 三个请求，加上各页 15~20s 的报价轮询，
# 同一标的瞬间会有 3~6 路相同请求 → Yahoo 限流（429）→ 免费链集体失败。
# 治理三件套：
#   1) single-flight：同 (symbol, interval) 同时只放一路真正打到网络，
#      其余等待后直接读它写入的缓存；
#   2) 报价短缓存：get_quote 结果缓存 20s，吸收各页面的轮询突发；
#   3) 失败原因记录：每个数据源最近一次失败原因可在 /market/data-source 查看。
_locks_guard = threading.Lock()

# P2-12：报价并行抓取复用**单一受限线程池**。旧实现每次 get_quotes 都新建
# ThreadPoolExecutor(8)，而调用方（market.py / ws.py）本身已经跑在线程池里 ——
# 嵌套线程池会让线程数随并发请求成倍膨胀。
_QUOTE_POOL = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="qd-quote")
# P0-2：单飞改用 Future 而不是 Lock。
# 旧实现（threading.Lock 版）的释放不对称：只有 leader 在 finally 里 release，
# 跟随者 acquire 到锁后从不释放 —— 同一 (symbol, interval) 第 3 个并发请求会
# 永久阻塞，把 anyio 线程池逐个吃干（全站 504），realtime 守护线程与 stream
# poller 走同一把锁，行情中枢整体停摆且无自愈。
_inflight: dict[str, "cf.Future"] = {}
_INFLIGHT_TIMEOUT = 60.0   # leader 超时后跟随者自行拉取，绝不无限等
_quote_cache: dict[str, tuple[float, dict]] = {}
_QUOTE_TTL = 20          # 秒
_last_errors: dict[str, str] = {}
# 免费链失败冷却：yfinance cookie/crumb 挂起实测 44.7s（超时+重试），27 个关注标的
# × 8 并发 × 每 20s 报价缓存过期 = 每次进页面都重烧整条降级链 30~40s。
# 冷却期内直接回旧缓存/合成（与原失败终点相同的数据，只是不再重烧网络）。
_chain_fail_at: dict[str, float] = {}
_CHAIN_COOLDOWN = 300.0        # 秒；日内周期取 min(该周期 TTL, 300)，1m 线只冷 60s
_CHAIN_COOLDOWN_DAILY = 1800.0  # 日线/周线冷 30 分钟：日 K 一天只更新一次，
                                # 且避免「每 5 分钟集体过期 → 整批重烧一次」的节律性卡顿

# 全局 yfinance 熔断：yfinance 内部超时不可控（cookie/crumb 挂起实测 20~45s），
# 27 标的并发首拉能把冷启动拖到分钟级。任一 yfinance 调用挂起/空返 → 全局熔断
# _YF_BREAKER_SEC 秒：增量更新与免费链的 yfinance 一环全部跳过（回旧缓存/走下链），
# 任一 yfinance 成功 → 立即解除。健康时熔断永不触发，行为与原来完全一致。
_yf_fail_at: float = 0.0
_YF_BREAKER_SEC = 120.0
_YF_INC_TIMEOUT = 8.0           # 增量更新单次等待上限（健康时 1~3s 内返回）


def _chain_cooldown_sec(interval: str) -> float:
    if interval in ("1d", "1wk"):
        return _CHAIN_COOLDOWN_DAILY
    return min(_TTL.get(interval, 3600), _CHAIN_COOLDOWN)


def _mark_yf_fail() -> None:
    global _yf_fail_at
    _yf_fail_at = time.time()


def _mark_yf_ok() -> None:
    global _yf_fail_at
    _yf_fail_at = 0.0


def yf_breaker_active() -> bool:
    return _yf_fail_at > 0 and time.time() - _yf_fail_at < _YF_BREAKER_SEC


def _yf_incremental_bounded(symbol: str, inc_start: str, end: str | None, interval: str) -> pd.DataFrame | None:
    """有界等待的 yfinance 增量拉取：超时按失败处理（返回 None）。

    超时后残留的守护线程会等 yfinance 内部超时后自行结束，不写缓存、不再累积。
    """
    box: dict[str, pd.DataFrame | None] = {}

    def _run() -> None:
        try:
            box["df"] = _from_yfinance(symbol, inc_start, end, interval)
        except Exception:  # noqa: BLE001
            box["df"] = None

    t = threading.Thread(target=_run, daemon=True, name=f"yf-inc-{symbol}")
    t.start()
    t.join(_YF_INC_TIMEOUT)
    return box.get("df")


def _chain_key(symbol: str, interval: str) -> str:
    return f"{symbol}|{interval}"


def _chain_cooling(symbol: str, interval: str) -> bool:
    ts = _chain_fail_at.get(_chain_key(symbol, interval))
    if ts is None:
        return False
    # 日线/周线冷 30 分钟；日内周期 = min(TTL, 300s)：1m 线只冷 60s，
    # 保证实时引擎的分钟数据不会被失败冷却冻太久。
    return time.time() - ts < _chain_cooldown_sec(interval)


def chain_cooldown_count() -> int:
    """当前处于失败冷却期的 (symbol, interval) 数（诊断用）。"""
    now = time.time()
    n = 0
    for key, ts in _chain_fail_at.items():
        interval = key.rsplit("|", 1)[-1]
        if now - ts < _chain_cooldown_sec(interval):
            n += 1
    return n


def recent_source_errors() -> dict[str, str]:
    """各数据源最近一次失败原因（诊断用，随时可清空重来）。"""
    return dict(_last_errors)


# ------------------------------------------------------------------
# 对外接口
# ------------------------------------------------------------------
def fetch_history(
    symbol: str,
    start: str = "2019-01-01",
    end: str | None = None,
    interval: str = "1d",
    use_cache: bool = True,
    prefer: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """返回 (DataFrame, 数据源名称)。prefer 指定时优先使用该数据源。"""
    symbol = symbol.strip().upper()
    ttl = _TTL.get(interval, 3600)
    pref = prefer if prefer is not None else _preferred

    # 1) 券商数据源（IBKR）：显式 prefer 或 auto 且已连接时自动作为第一优先
    #    （分钟级可回溯数年，远强于免费源 60 天；未连接时 _broker() 快速返回 None，零开销落回下链）
    auto_ibkr = pref is None and "ibkr" in _history_providers
    if pref and pref in _history_providers:
        try:
            df = _history_providers[pref].history(symbol, start, end, interval)
            if df is not None and len(df) > 20:
                return _normalize(df), pref
        except Exception as exc:  # noqa: BLE001
            # P1-2：失败必须可见 —— 旧实现 except: pass 静默吞掉，
            # 「IBKR 分钟级回溯数年」坏了运维完全看不出来。
            _last_errors["ibkr"] = f"{type(exc).__name__}: {exc}"[:160]
    elif auto_ibkr:
        try:
            df = _history_providers["ibkr"].history(symbol, start, end, interval)
            if df is not None and len(df) > 20:
                return _normalize(df), "ibkr"
        except Exception as exc:  # noqa: BLE001
            _last_errors["ibkr"] = f"{type(exc).__name__}: {exc}"[:160]

    # 2) 本地缓存（必须覆盖请求区间，否则当作未命中）
    if use_cache:
        cached = _read_cache(symbol, interval, ttl, start=start, end=end)
        if cached is not None and not cached.empty:
            return cached, "cache"

    # 2.2) 失败冷却门：该 (symbol, interval) 的免费链刚整体失败过 → 不再重烧网络
    #      （yfinance 挂起一次 20~45s，27 标的关注列表曾把每次进页面拖到 30~40s）。
    #      数据与原失败终点一致：有旧缓存回旧缓存，否则合成 —— 只是把 60s 的等待变成毫秒级。
    if use_cache and _chain_cooling(symbol, interval):
        stale_cool = _read_cache(symbol, interval, ttl, start=start, end=end, ignore_ttl=True)
        if stale_cool is not None and not stale_cool.empty:
            return stale_cool, "cache-stale"
        return _synthetic(symbol, start, end, interval), "synthetic"

    # 2.5) 增量更新：TTL 过期时只补「缓存尾日之后」的新数据，而不是全量重拉 420 天。
    #      合并失败/增量拉不到 → 回退旧缓存（stale-while-revalidate：有旧数据好过等待或空白）。
    #      1wk 合并对齐复杂，跳过；end 指定的回测区间同理走全量（历史不会变）。
    if use_cache and interval != "1wk" and not end:
        cool_key = _chain_key(symbol, interval)
        try:
            stale_df = _read_cache(symbol, interval, ttl, start=start, end=end, ignore_ttl=True)
            if stale_df is not None and not stale_df.empty:
                last_dt = stale_df.index[-1]
                if interval == "1d":
                    inc_start = (last_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    inc_start = str(last_dt)            # 分钟线按时间戳精确增量
                # 注意：旧代码调用的是不存在的 _from_yf（NameError 被上层 except 吞掉），
                # 增量更新分支因此从未真正执行过 —— 顺手修正为 _from_yfinance。
                if yf_breaker_active():
                    # yfinance 全局熔断中：跳过增量网络等待，直接回旧缓存
                    _chain_fail_at[cool_key] = time.time()
                    return stale_df, "cache-stale"
                inc = _yf_incremental_bounded(symbol, inc_start, end, interval)
                if inc is not None and len(inc) > 0:
                    # P1-1：stale_df（缓存，已是 NY-naive）与 inc（_from_yfinance 内部已归一化）
                    # 直接拼接 —— 旧实现在这里对合并结果再跑一次 _normalize，
                    # 已归一化的 naive 时间戳被再次「当 UTC→NY」平移，每次漂移 4h，
                    # 日线 TTL 6h 意味着缓存里的历史 K 线会持续漂移。
                    merged = pd.concat([stale_df, inc])
                    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                    _write_cache(symbol, interval, merged)
                    _mark_yf_ok()                        # yfinance 恢复 → 解除全局熔断
                    _chain_fail_at.pop(cool_key, None)   # 恢复成功 → 解除冷却
                    return merged, "cache+inc"
                # 增量为空/超时（休市 / 被限流 / 挂起）→ 旧缓存照常可用，
                # 同时进入失败冷却 + 标记 yfinance 全局熔断。
                _mark_yf_fail()
                _chain_fail_at[cool_key] = time.time()
                return stale_df, "cache-stale"
        except Exception:
            pass                                        # 增量任何异常都退回全量路径

    # 3) 免费源链（按市场路由：港股优先腾讯，美股 yfinance→stooq→finnhub）
    #    同 (symbol, interval) 单飞：并发请求只有一路真正上网，其余等结果读缓存。
    if _market_of(symbol) == "HK":
        chain: tuple[tuple[str, Any], ...] = (
            (("tencent-hk-m1", v_tencent_hk_m1), ("yfinance", v_yf))
            if interval == "1m"
            else (("tencent-hk", v_tencent_hk), ("yfinance", v_yf))
        )
    else:
        chain = (
            ("yfinance", v_yf), ("stooq", v_st), ("finnhub", v_fh),
        )
    flight_key = f"{symbol}|{interval}"
    with _locks_guard:
        leader_fut = _inflight.get(flight_key)
        is_leader = leader_fut is None
        if is_leader:
            leader_fut = cf.Future()
            _inflight[flight_key] = leader_fut

    if not is_leader:
        # P0-2：跟随者只等待 leader 的 Future（有超时），绝不获取锁 → 不可能死锁。
        try:
            leader_fut.result(timeout=_INFLIGHT_TIMEOUT)
        except Exception:  # noqa: BLE001 —— leader 失败/超时 → 自己走一遍全链
            pass
        if use_cache:
            cached = _read_cache(symbol, interval, ttl, start=start, end=end)
            if cached is not None and not cached.empty:
                return cached, "cache"
    try:
        for name, fn in chain:
            if name == "yfinance" and yf_breaker_active():
                _last_errors["yfinance"] = "熔断跳过（近期挂起/空返，稍后自动重试）"
                continue
            attempts = 2 if name == "yfinance" else 1   # Yahoo 偶发限流，重试一次
            for attempt in range(attempts):
                try:
                    df = fn(symbol, start, end, interval)
                    if df is not None and len(df) > 20:
                        _write_cache(symbol, interval, df)
                        if name == "yfinance":
                            _mark_yf_ok()               # 链路恢复 → 解除全局熔断
                        _chain_fail_at.pop(flight_key, None)   # 链路恢复 → 解除冷却
                        return df, name
                    _last_errors[name] = f"返回为空（第 {attempt + 1} 次尝试）"
                    if name == "yfinance":
                        _mark_yf_fail()
                except Exception as exc:  # noqa: BLE001
                    _last_errors[name] = f"{type(exc).__name__}: {exc}"[:160]
                    if name == "yfinance":
                        _mark_yf_fail()
                if attempt < attempts - 1:
                    time.sleep(0.8)
        # 整条免费链失败 → 该 (symbol, interval) 进入冷却（见 2.2 冷却门）
        _chain_fail_at[flight_key] = time.time()
    finally:
        if is_leader:
            # 唤醒所有等待者（无论成败），并让位给下一代单飞
            if not leader_fut.done():
                leader_fut.set_result(True)
            with _locks_guard:
                if _inflight.get(flight_key) is leader_fut:
                    _inflight.pop(flight_key, None)

    # 4) 合成兜底
    df = _synthetic(symbol, start, end, interval)
    return df, "synthetic"


def v_yf(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_yfinance(symbol, start, end, interval)


def v_st(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    if interval != "1d":
        return pd.DataFrame(columns=OHLCV)
    return _from_stooq(symbol, start, end)


def v_tencent_hk(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_tencent_hk(symbol, start, end, interval)


def v_tencent_hk_m1(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_tencent_hk_m1(symbol, start, end, interval)


def v_fh(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    return _from_finnhub(symbol, start, end, interval)


def fetch_many(
    symbols: Iterable[str],
    start: str = "2019-01-01",
    end: str | None = None,
    interval: str = "1d",
    prefer: str | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    out: dict[str, pd.DataFrame] = {}
    srcs: dict[str, str] = {}
    for s in symbols:
        df, src = fetch_history(s, start, end, interval, prefer=prefer)
        if not df.empty:
            out[s.strip().upper()] = df
            srcs[s.strip().upper()] = src
    return out, srcs


def _quote_from_df(df: pd.DataFrame, symbol: str, source: str) -> dict:
    if df.empty:
        return {
            "symbol": symbol, "price": 0.0, "prev_close": 0.0, "change": 0.0,
            "change_pct": 0.0, "volume": 0.0, "day_high": 0.0, "day_low": 0.0,
            "source": source, "ts": datetime.now(timezone.utc).isoformat(),
        }
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    price = float(last["close"])
    pc = float(prev["close"])
    chg = price - pc
    return {
        "symbol": symbol,
        "price": round(price, 4),
        "prev_close": round(pc, 4),
        "change": round(chg, 4),
        "change_pct": round((chg / pc * 100) if pc else 0.0, 3),
        "volume": float(last["volume"]),
        "day_high": round(float(last["high"]), 4),
        "day_low": round(float(last["low"]), 4),
        "open": round(float(last["open"]), 4),
        "ts": str(df.index[-1]),
        "source": source,
    }


def get_quote(symbol: str, prefer: str | None = None) -> dict:
    symbol = symbol.strip().upper()
    # 报价短缓存：吸收各页面 15~20s 轮询的突发（显式 prefer 券商源时不缓存，保实时性）
    if prefer is None:
        hit = _quote_cache.get(symbol)
        if hit and time.time() - hit[0] < _QUOTE_TTL:
            return hit[1]
    pref = prefer if prefer is not None else _preferred
    if pref and pref in _history_providers:
        try:
            snap = getattr(_history_providers[pref], "snapshot", None)
            if callable(snap):
                rows = snap([symbol])
                if rows and rows[0].get("price", 0) > 0:
                    return rows[0]
        except Exception:
            pass
    # 港股：腾讯实时快照（秒级）优先于 90 天日线推导
    if _market_of(symbol) == "HK":
        qt = _from_tencent_hk_quote(symbol)
        if qt:
            if prefer is None:
                _quote_cache[symbol] = (time.time(), qt)
            return qt
    df, src = fetch_history(
        symbol, start=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), interval="1d", prefer=None
    )
    q = _quote_from_df(df, symbol, src)
    if prefer is None and q.get("price", 0) > 0:
        _quote_cache[symbol] = (time.time(), q)
    return q


def get_quotes(symbols: Iterable[str], prefer: str | None = None) -> list[dict]:
    syms = [s.strip().upper() for s in symbols if s.strip()]
    pref = prefer if prefer is not None else _preferred
    if pref and pref in _history_providers:
        try:
            snap = getattr(_history_providers[pref], "snapshot", None)
            if callable(snap):
                rows = snap(syms)
                if rows and any(r.get("price", 0) > 0 for r in rows):
                    return rows
        except Exception:
            pass
    if len(syms) <= 1:
        return [get_quote(s, prefer=None) for s in syms]
    # P2-12：复用模块级受限线程池，不再每次新建（见 _QUOTE_POOL 注释）
    return list(_QUOTE_POOL.map(lambda s: get_quote(s, prefer=None), syms))


def clear_cache() -> int:
    n = 0
    for p in CACHE_DIR.rglob("*.csv"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


def cache_stats() -> dict:
    files = list(CACHE_DIR.rglob("*.csv"))
    size = sum(p.stat().st_size for p in files)
    return {"files": len(files), "bytes": size, "dir": str(CACHE_DIR)}
