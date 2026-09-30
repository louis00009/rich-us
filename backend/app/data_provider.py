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
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import pandas as pd

from .config import CACHE_DIR, settings
from . import hist_store
# 数据源实现拆至 providers/ 包（FILE_SIZE_DEBT Batch F-3）—— re-export 保持旧路径：
from .providers.common import OHLCV, _normalize  # noqa: F401,E402
from .providers.finnhub import _from_finnhub, v_fh  # noqa: F401,E402
from .providers.stooq import _from_stooq, _stooq_symbol, v_st  # noqa: F401,E402
from .providers.synthetic import _market_of, _synthetic  # noqa: F401,E402
from .providers.tencent_hk import (  # noqa: F401,E402
    _from_tencent_hk,
    _from_tencent_hk_m1,
    _from_tencent_hk_quote,
    _tencent_hk_code,
    v_tencent_hk,
    v_tencent_hk_m1,
)
from .providers.twelvedata import (  # noqa: F401,E402
    TwelveDataProvider,
    _from_twelvedata,
    register_twelvedata_provider,
    v_td,
)
from .providers.yfinance import (  # noqa: F401,E402
    _from_yfinance,
    _mark_yf_fail,
    _mark_yf_ok,
    _yf_incremental_bounded,
    v_yf,
    yf_breaker_active,
)
# 符号宇宙 / 搜索 / 磁盘缓存 / 共享状态已拆出（FILE_SIZE_DEBT Batch F-3 续）——
# re-export 保持旧路径：外部 `from ..data_provider import UNIVERSE / search_symbols / ...` 全部不变。
from .ds_state import _CACHE_CAP, _bounded_set, _last_errors, recent_source_errors  # noqa: F401,E402
from .hist_cache import _cache_path, _read_cache, _write_cache  # noqa: F401,E402
from .symbol_search import _yahoo_search, search_symbols  # noqa: F401,E402
from .universe import UNIVERSE, UNIVERSE_MAP, SymbolInfo  # noqa: F401,E402

OHLCV = ["open", "high", "low", "close", "volume"]

_TTL = {"1d": 6 * 3600, "1wk": 12 * 3600, "1h": 1800, "30m": 900, "15m": 600, "5m": 300, "1m": 60}


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


class _LocalHistProvider:
    """把本地历史库（IBKR 灌库产物）适配成 provider，使其出现在源健康状态里。

    ⚠️ 注意：本地库在 `fetch_history` 中是**第 0 优先**（在 IBKR 之前），
    不走 provider 链；这里注册只是为了 `provider_status()` 能展示覆盖率，
    以及让用户能在设置页看到它。**真正的读取逻辑在 fetch_history 里**。
    """

    name = "local"

    def history(self, symbol, start=None, end=None, interval="1d"):
        return hist_store.history(symbol, start, end, interval)

    def status(self) -> dict:
        try:
            cov = hist_store.coverage()
            return {
                "name": "local",
                "available": bool(cov.get("available")),
                "symbols": cov.get("symbols", 0),
                "dir": cov.get("dir", ""),
                "note": "IBKR 灌库产物；命中时零网络、零限流",
            }
        except Exception as exc:  # noqa: BLE001
            return {"name": "local", "available": False, "error": str(exc)[:120]}


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
# 免费链失败冷却：yfinance cookie/crumb 挂起实测 44.7s（超时+重试），27 个关注标的
# × 8 并发 × 每 20s 报价缓存过期 = 每次进页面都重烧整条降级链 30~40s。
# 冷却期内直接回旧缓存/合成（与原失败终点相同的数据，只是不再重烧网络）。
_chain_fail_at: dict[str, float] = {}
_CHAIN_COOLDOWN = 300.0        # 秒；日内周期取 min(该周期 TTL, 300)，1m 线只冷 60s
_CHAIN_COOLDOWN_DAILY = 1800.0  # 日线/周线冷 30 分钟：日 K 一天只更新一次，
                                # 且避免「每 5 分钟集体过期 → 整批重烧一次」的节律性卡顿


def _chain_cooldown_sec(interval: str) -> float:
    if interval in ("1d", "1wk"):
        return _CHAIN_COOLDOWN_DAILY
    return min(_TTL.get(interval, 3600), _CHAIN_COOLDOWN)


def _chain_key(symbol: str, interval: str) -> str:
    return f"{symbol}|{interval}"


def _chain_cooling(symbol: str, interval: str) -> bool:
    ts = _chain_fail_at.get(_chain_key(symbol, interval))
    if ts is None:
        # P3：顺手清理过期条目 —— 旧实现只在失败时新增，过期键永不删除，
        # 键空间 = symbol × interval，长期运行会缓慢膨胀。
        if len(_chain_fail_at) > _CACHE_CAP:
            now = time.time()
            for k in [k for k, v in _chain_fail_at.items()
                      if now - v >= _chain_cooldown_sec(k.rsplit("|", 1)[-1])]:
                _chain_fail_at.pop(k, None)
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

    # 0) 本地历史库（IBKR 灌库产物）—— 零网络、零限流，永远第一优先。
    #    只有覆盖请求区间才命中（hist_store 内部保证「宁缺毋滥」：
    #    区间超出本地覆盖时返回 None，避免用部分数据冒充完整历史）。
    #    用 prefer 显式指定其它源时跳过本地库，尊重用户选择。
    if use_cache and not pref:
        try:
            local = hist_store.history(symbol, start, end, interval)
            if local is not None and len(local) > 20:
                return local, "local"
        except Exception as exc:  # noqa: BLE001 —— 本地库异常不得阻断取数
            _last_errors["local"] = f"{type(exc).__name__}: {exc}"[:160]

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
                if inc is None:
                    # 真失败（异常 / 8s 超时）→ 标记 yfinance 全局熔断 + 该标的进入失败冷却。
                    _mark_yf_fail()
                    _chain_fail_at[cool_key] = time.time()
                    return stale_df, "cache-stale"
                # inc 是「调用成功但零行」（休市 / 当日 K 线尚未发布 / 请求区间无数据）：
                # yfinance 本身是**健康的**，绝不能标记全局熔断 —— 否则一个标的的
                # 「无新数据」会把 120s 内**所有**标的的 yfinance 一起冻结（旧实现如此，属误伤），
                # 也不能设该标的的失败冷却（那不是失败，且会把新 K 线出现后的刷新冻 30 分钟）。
                # 旧缓存照常可用；下次请求再试一次增量，成本极低（成功但空会立刻返回）。
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
            ("yfinance", v_yf), ("stooq", v_st),
            # TwelveData 走多 Key 轮询池，额度有限（免费档 8/min/Key）——
            # 刻意放在 stooq 之后当「最后一道真实数据源」：限流器本身就是安全阀，
            # 额度耗尽时返回空 → 继续下探到 finnhub，不会 429 雪崩、也不会阻塞。
            ("twelvedata", v_td), ("finnhub", v_fh),
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


def register_local_provider() -> None:
    """注册本地历史库（IBKR 灌库产物）—— 仅在库非空时注册，避免设置页出现空条目。"""
    if hist_store.available():
        register_history_provider("local", _LocalHistProvider())


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
                # P3：走有界写入 —— _quote_cache 的键来自用户输入的 symbol，
                # 无上限时长时间运行会持续增长且无淘汰。
                _bounded_set(_quote_cache, symbol, (time.time(), qt))
            return qt
    df, src = fetch_history(
        symbol, start=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), interval="1d", prefer=None
    )
    q = _quote_from_df(df, symbol, src)
    if prefer is None and q.get("price", 0) > 0:
        _bounded_set(_quote_cache, symbol, (time.time(), q))
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


def shutdown_pools() -> None:
    """显式关闭报价线程池（由 main.py 的 lifespan 收尾调用）。

    P3：`ThreadPoolExecutor` 的线程非 daemon，atexit 会 join —— 退出时若还有
    卡在网络的报价任务，进程会被拖住。
    """
    try:
        _QUOTE_POOL.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass


def clear_cache() -> int:
    n = 0
    for p in CACHE_DIR.rglob("*.csv"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
        except BaseException:  # noqa: BLE001 —— safe-delete 护栏抛 SystemExit，清理失败不外溢
            pass
    return n


def cache_stats() -> dict:
    files = list(CACHE_DIR.rglob("*.csv"))
    size = sum(p.stat().st_size for p in files)
    return {"files": len(files), "bytes": size, "dir": str(CACHE_DIR)}
