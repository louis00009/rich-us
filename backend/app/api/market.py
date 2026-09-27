"""行情接口。"""
from __future__ import annotations

import asyncio
import datetime as dt
import threading
import time
import re

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..brokers import get_broker
from ..data_provider import (
    UNIVERSE,
    available_providers,
    cache_stats,
    clear_cache,
    fetch_history,
    get_preferred,
    get_quote,
    get_quotes,
    provider_status,
    recent_source_errors,
    chain_cooldown_count,
    yf_breaker_active,
    search_symbols,
    set_preferred,
)
from ..strategies import indicators as ind
from .deps import CurrentUser

router = APIRouter(prefix="/market", tags=["行情"])

MAJOR_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "^VIX", "TLT", "GLD", "USO", "^TNX", "SMH", "FXI", "EEM"]


def _broker_quotes(symbols: list[str]) -> list[dict]:
    """
    优先用当前配置券商的行情（IBKR 时即为真实实时/延迟行情），
    券商不可用则自动退回免费源。这样「实盘看到的价」与「分析用的价」保持一致。
    """
    try:
        cfg = appstate.get_broker_settings()
        if str(cfg.get("provider")) == "ibkr":
            broker, _ = get_broker(cfg)
            rows = broker.quotes(symbols)
            if rows and any(r.get("price", 0) > 0 for r in rows):
                return rows
    except Exception:  # noqa: BLE001
        pass
    return get_quotes(symbols)


@router.get("/universe")
def universe(kind: str = Query("", description="ETF/STOCK/INDEX，留空返回全部"), user: CurrentUser = None) -> dict:  # noqa: ARG001
    items = [
        {"symbol": s.symbol, "name": s.name, "kind": s.kind}
        for s in UNIVERSE
        if not kind or s.kind.upper() == kind.upper()
    ]
    return {"count": len(items), "items": items}


@router.get("/search")
def search(q: str = "", limit: int = 20, user: CurrentUser = None) -> dict:  # noqa: ARG001
    items = search_symbols(q, limit)
    # 中文名匹配：关键词命中中文名的标的也纳入（如搜「腾讯」→ 0700.HK）。
    # 只读缓存绝不联网；未命中中文名时回落关键词包含比对（enrich 渐进填充）。
    try:
        from ..company import names_cn_cached

        items_syms = [str(i.get("symbol", "")) for i in items]
        cn = names_cn_cached(items_syms)
        q_key = (q or "").strip()
        if q_key and not any(cn.get(s) for s in items_syms):
            # 当前结果无中文命中：查库补入中文名包含关键词的标的（如搜「腾讯」→ 0700.HK）
            from ..database import SessionLocal
            from ..models import CompanyProfile

            with SessionLocal() as _s:
                hit_rows = (
                    _s.query(CompanyProfile)
                    .filter(CompanyProfile.name_cn.contains(q_key))
                    .limit(limit)
                    .all()
                )
            for row in hit_rows:
                if not any(i.get("symbol") == row.symbol for i in items):
                    cn[row.symbol] = row.name_cn
                    items.append({"symbol": row.symbol, "name": row.name or row.symbol, "kind": "STK", "name_cn": row.name_cn})
        for i in items:
            i["name_cn"] = cn.get(str(i.get("symbol", "")), "")
            if i["name_cn"]:
                i["name"] = f"{i['name_cn']} ({i.get('name', '')})"
    except Exception:  # noqa: BLE001
        pass
    return {"items": items}


@router.get("/quote")
async def quote(symbols: str = Query(..., description="逗号分隔，如 SPY,QQQ,NVDA"), user: CurrentUser = None) -> dict:  # noqa: ARG001
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:40]
    if not syms:
        raise HTTPException(400, "至少需要一个标的")
    items = await run_in_threadpool(_broker_quotes, syms)
    return {"count": len(items), "items": items}


@router.get("/history")
async def history(
    symbol: str,
    user: CurrentUser,
    start: str = "2019-01-01",
    end: str | None = None,
    interval: str = "1d",
    source: str = "auto",
) -> dict:
    # P2-5：symbol 无界校验 —— 过长/空值会被拼进缓存文件名与外部数据源的 URL 查询串
    symbol = (symbol or "").strip().upper()
    if not symbol or len(symbol) > 32:
        raise HTTPException(400, "标的代码非法（长度需在 1~32 之间）")
    if interval not in ("1d", "1wk", "1h", "30m", "15m", "5m", "1m"):
        raise HTTPException(400, "不支持的周期")
    prefer = None if source in ("", "auto") else source
    try:
        df, used = await run_in_threadpool(
            lambda: fetch_history(symbol, start, end, interval, prefer=prefer)
        )
    except Exception as exc:  # noqa: BLE001 —— 正常情况下 fetch_history 内部已兜底合成数据，
        # 这里只防未知异常裸 500，让前端拿到明确文案而不是「获取 XX 行情失败」
        raise HTTPException(503, f"行情源暂时不可用：{type(exc).__name__}: {exc}") from exc
    if df.empty:
        raise HTTPException(404, f"未获取到 {symbol} 的行情数据")
    # 按请求区间**严格裁剪**：分钟/小时线源用 yfinance period 模式（如 1h=180d），
    # 返回的数据远超请求的 start —— 曾导致「选 1 周显示 180 天小时线」。
    # 注意只裁 API 响应层；snapshot/AI 指标仍用全量历史计算。
    import pandas as _pd

    try:
        _s = _pd.to_datetime(start)
        df = df[df.index >= _s]
    except Exception:  # noqa: BLE001
        pass
    if end:
        try:
            _e = _pd.to_datetime(end) + _pd.Timedelta(days=1)   # end 含当日
            df = df[df.index <= _e]
        except Exception:  # noqa: BLE001
            pass
    if df.empty:
        raise HTTPException(404, f"{symbol} 在请求区间（{start} 起）暂无数据")
    tail = df.tail(3000)
    warn = ""
    if prefer and used != prefer:
        warn = f"请求的数据源「{prefer}」不可用，已自动降级为「{used}」"
    realtime_flag = False
    if interval == "1d":
        # 当日实时 bar：把实时报价融合为最后一根（盘中更新/追加今日），
        # 否则 K 线/折线图永远停在最近收盘日 —— 用户「看不到当日走势」的主因。
        # fetch_history 命中缓存时返回的是缓存内对象，必须 copy 后再改。
        try:
            from ..ai_analyst import _merge_realtime
            from ..data_provider import get_quote

            quote = await run_in_threadpool(get_quote, symbol)
            work = tail.copy()
            work, rt = _merge_realtime(work, quote)
            realtime_flag = bool(rt.get("realtime"))
            if realtime_flag:
                tail = work
                used = used  # 数据源不变，仅末根融合实时价
        except Exception:  # noqa: BLE001 —— 融合失败退化为纯日线
            pass
    return {
        "symbol": symbol.upper(),
        "source": used,
        "source_requested": source,
        "warning": warn,
        "realtime": realtime_flag,
        "interval": interval,
        # P2-16：count 必须与 dates/ohlc 数组同长。旧实现非实时路径用 len(df)，
        # 而数组来自 df.tail(3000) —— df 超 3000 根时前端长度校验/对齐会错位。
        "count": len(tail),
        "dates": [str(d)[:19] for d in tail.index],
        "open": [round(float(x), 4) for x in tail["open"]],
        "high": [round(float(x), 4) for x in tail["high"]],
        "low": [round(float(x), 4) for x in tail["low"]],
        "close": [round(float(x), 4) for x in tail["close"]],
        "volume": [float(x) for x in tail["volume"]],
    }


@router.get("/intraday")
async def intraday(symbol: str, user: CurrentUser, interval: str = "1m") -> dict:
    """当日分时走势：1 分钟切片 + 累计均价线 + 昨收基准。

    数据链：IBKR（已连接时最实时）→ 腾讯 m1（港股秒级）→ yfinance 1m（美股，~15 分钟延迟）。
    """
    symbol = symbol.strip().upper()
    if interval not in ("1m", "5m"):
        raise HTTPException(400, "分时仅支持 1m / 5m")
    # start 用「今天」而非久远日期：1m 缓存 TTL 60s，覆盖度校验以今天为基准才能命中，
    # 否则前端 30s 轮询每次都穿透到网络层打爆免费源
    df, src = await run_in_threadpool(
        lambda: fetch_history(symbol, dt.date.today().isoformat(), None, interval)
    )
    if df.empty:
        raise HTTPException(404, f"未获取到 {symbol} 的分时数据")
    # 存储口径是「真实时刻的 NY naive」（统一由 _normalize 保证）。
    # 分时展示需还原为交易所本地时间：HK 数据 NY→HK（+12h，EDT）；
    # 若按 NY 口径取"最后一天"，港股整段会错日/错时。
    from ..data_provider import _market_of

    if _market_of(symbol) == "HK":
        df.index = (
            df.index.tz_localize("America/New_York")
            .tz_convert("Asia/Hong_Kong")
            .tz_localize(None)
        )
    # 取序列最后一天作为「当日」（休市/非交易时段 = 最近一个交易日，自动回退）
    day = df.index[-1].normalize()
    df = df[df.index.normalize() == day]
    if df.empty:
        raise HTTPException(404, f"{symbol} 当日无分时数据")
    trade_date = str(day.date())
    # 交易日 vs 今天：不一致说明展示的是上一交易日（休市回退），前端明示
    try:
        from ..data_provider import _market_of as _mkt

        _tzname = "Asia/Hong_Kong" if _mkt(symbol) == "HK" else "America/New_York"
        from zoneinfo import ZoneInfo

        # P2：旧代码写的是未定义的 `_dt`，NameError 被 except 吞掉后恒走
        # 本机本地日期比较 —— 港股时区（UTC+8）收盘后 is_today 会误判。
        is_today = trade_date == dt.datetime.now(ZoneInfo(_tzname)).date().isoformat()
    except Exception:  # noqa: BLE001
        is_today = trade_date == dt.date.today().isoformat()

    quote = await run_in_threadpool(get_quote, symbol)
    prev_close = float(quote.get("prev_close") or 0.0)
    if prev_close <= 0:
        # 退而求其次：当日第一根 open 近似（无昨收时基准失真，标记出来）
        prev_close = float(df["open"].iloc[0])

    c, v = df["close"], df["volume"]
    cum_pv = (c * v).cumsum()
    cum_v = v.cumsum().replace(0, 1e-9)
    avg = (cum_pv / cum_v).round(4)
    last_chg = (float(c.iloc[-1]) / prev_close - 1) * 100 if prev_close else 0.0

    # 免费日内源（yfinance/stooq）有 ~15 分钟延迟；腾讯/IBKR 实时。
    # cache 语义取决于底层源：美股 cache 底层必是免费源 → 视为延迟；
    # 港股 cache 可能来自腾讯 m1（实时），保守标记为不延迟。
    from ..data_provider import v_fh, v_st, v_yf

    _delayed_srcs = {"yfinance", "stooq", "finnhub", "synthetic"}
    is_delayed = src in _delayed_srcs or (src == "cache" and _market_of(symbol) == "US")

    return {
        "symbol": symbol,
        "source": src,
        "interval": interval,
        "trade_date": trade_date,
        "is_today": is_today,
        "prev_close": round(prev_close, 4),
        "last_price": round(float(c.iloc[-1]), 4),
        "change_pct": round(last_chg, 2),
        "delayed": is_delayed,
        "count": int(len(df)),
        "points": [
            {
                "t": str(idx)[11:16] if len(str(idx)) > 16 else str(idx)[:10],
                "price": round(float(cl), 4),
                "avg": round(float(av), 4) if av == av else None,
                "vol": float(vl),
            }
            for idx, cl, av, vl in zip(df.index, c, avg, v)
        ],
    }


_ovw_alock = asyncio.Lock()   # P2：旧代码在协程内 `async with asyncio.Lock()` 每次新建锁，
_ovw_cache: tuple[float, list[dict]] = (0.0, [])   # 双检锁完全失效；:274 的 threading.Lock 也从未被用
_OVW_TTL = 5.0     # 秒：12 标的 IBKR 快照首次订阅 5~15s，无缓存时 Dashboard 首屏被拖住


@router.get("/overview")
async def overview(user: CurrentUser = None) -> dict:  # noqa: ARG001
    """大盘标的概览。5 秒服务端缓存：高频调用共享一次快照，慢源不再串行打满首屏。"""
    global _ovw_cache
    ts, cached = _ovw_cache
    if cached and time.monotonic() - ts < _OVW_TTL:
        return {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "cached": True, "items": cached}
    async with _ovw_alock:
        ts, cached = _ovw_cache
        if cached and time.monotonic() - ts < _OVW_TTL:      # 双检：并发只放一个进慢路径
            return {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "cached": True, "items": cached}
        items = await run_in_threadpool(_broker_quotes, MAJOR_TICKERS)
        _ovw_cache = (time.monotonic(), items)
    return {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "cached": False, "items": items}


@router.get("/data-source")
def data_source(user: CurrentUser = None) -> dict:  # noqa: ARG001
    """查询当前数据源偏好与各提供者可用性。"""
    return {
        "preferred": get_preferred() or "auto",
        "available": available_providers(),
        "providers": {n: provider_status(n) for n in available_providers() if n != "auto"},
        "recent_errors": recent_source_errors(),
        "chain_cooldowns": chain_cooldown_count(),
        "yf_breaker": yf_breaker_active(),
        "chain": [
            "① 券商优先源（IBKR，需已连接）",
            "② 本地缓存",
            "③ yfinance",
            "④ Stooq CSV",
            "⑤ 合成行情（非真实数据）",
        ],
        "note": "日内周期（5m/15m/30m）在免费源只能回溯 60 天；接入 IBKR 后可回溯数年。免费链失败后进入冷却（日线 30 分钟 / 日内 ≤5 分钟）：期间直接回旧缓存/合成，不再重烧网络。",
    }


@router.post("/data-source")
def set_data_source(payload: dict, user: CurrentUser) -> dict:
    name = str(payload.get("preferred", "auto"))
    if name not in available_providers():
        raise HTTPException(400, f"未知数据源：{name}，可选：{', '.join(available_providers())}")
    set_preferred(name)
    appstate.log("data_source_change", "INFO", f"数据源偏好切换为 {name}", actor=user.username)
    return {"ok": True, "preferred": get_preferred() or "auto"}


@router.get("/snapshot")
async def snapshot(symbol: str, lookback_days: int = 300, user: CurrentUser = None) -> dict:  # noqa: ARG001
    from ..ai_analyst import market_snapshot

    snap = await run_in_threadpool(market_snapshot, symbol.upper(), lookback_days)
    if snap.get("error"):
        raise HTTPException(404, snap["error"])
    return snap


@router.get("/indicators")
async def indicator_panel(symbol: str, list: str = "rsi,macd,bb,adx,atr,vol", user: CurrentUser = None) -> dict:  # noqa: ARG001
    """返回指定指标的完整时间序列，用于前端叠加图表。"""
    start = (dt.date.today() - dt.timedelta(days=800)).isoformat()
    df, source = await run_in_threadpool(fetch_history, symbol.upper(), start, None, "1d")
    if df.empty:
        raise HTTPException(404, f"未获取到 {symbol} 的数据")
    keys = [k.strip() for k in list.split(",") if k.strip()]
    out: dict[str, list] = {}
    dates = [str(d)[:10] for d in df.index]
    for k in keys:
        try:
            m_sma = re.fullmatch(r"sma(\d+)", k)     # 任意周期均线：sma5/sma20/sma60/...
            m_ema = re.fullmatch(r"ema(\d+)", k)
            if k == "macd":
                m = ind.macd(df["close"])
                out["macd"] = [None if v != v else round(float(v), 4) for v in m["macd"]]
                out["macd_signal"] = [None if v != v else round(float(v), 4) for v in m["signal"]]
                out["macd_hist"] = [None if v != v else round(float(v), 4) for v in m["hist"]]
            elif m_sma:
                s = ind.sma(df["close"], int(m_sma.group(1)))
                out[k] = [None if v != v else round(float(v), 4) for v in s]
            elif m_ema:
                s = ind.ema(df["close"], int(m_ema.group(1)))
                out[k] = [None if v != v else round(float(v), 4) for v in s]
            elif k == "bb":
                b = ind.bollinger(df["close"], 20, 2)
                for name, col in (("bb_upper", "upper"), ("bb_mid", "mid"), ("bb_lower", "lower")):
                    out[name] = [None if v != v else round(float(v), 4) for v in b[col]]
            elif k == "adx":
                a = ind.adx(df["high"], df["low"], df["close"], 14)
                for name in ("adx", "plus_di", "minus_di"):
                    out[name] = [None if v != v else round(float(v), 3) for v in a[name]]
            else:
                mapping = {
                    "rsi": lambda: ind.rsi(df["close"], 14),
                    "atr": lambda: ind.atr(df["high"], df["low"], df["close"], 14),
                    "vol": lambda: ind.realized_vol(df["close"], 20) * 100,
                    "obv": lambda: ind.obv(df["close"], df["volume"]),
                    "cmf": lambda: ind.cmf(df["high"], df["low"], df["close"], df["volume"], 20),
                    "zscore": lambda: ind.zscore(df["close"], 20),
                }
                if k not in mapping:
                    continue
                s = mapping[k]()
                out[k] = [None if v != v else round(float(v), 4) for v in s]
        except Exception:  # noqa: BLE001
            continue
    return {"symbol": symbol.upper(), "source": source, "dates": dates, "series": out}


@router.get("/catalog")
def catalog(user: CurrentUser = None) -> dict:  # noqa: ARG001
    return {
        "quote_fields": [
            "price", "prev_close", "change", "change_pct", "volume",
            "day_high", "day_low", "open", "bid", "ask", "source",
        ],
        "intervals": ["1d", "1wk", "1h", "30m", "15m", "5m"],
        "data_sources": [
            {"key": "ibkr", "label": "IBKR 券商行情（真实/延迟，日内可回溯数年）"},
            {"key": "yfinance", "label": "yfinance（首选免费源，支持多周期）"},
            {"key": "stooq", "label": "Stooq（免费日线兜底）"},
            {"key": "synthetic", "label": "合成行情（离线自检，非真实数据）"},
            {"key": "cache", "label": "本地缓存"},
        ],
        "preferred": get_preferred() or "auto",
        "major_tickers": MAJOR_TICKERS,
        "cache": cache_stats(),
    }


@router.post("/cache/clear")
async def cache_clear(user: CurrentUser) -> dict:
    n = await run_in_threadpool(clear_cache)
    appstate.log("cache_clear", "INFO", f"清理行情缓存 {n} 个文件", actor=user.username)
    return {"ok": True, "removed": n}
