"""每日开盘监控 —— 美股全池暴涨暴跌实时扫描。

需求：盘中以比榜单（10 分钟 TTL）更快的节奏跟踪全池异动，
把「暴涨 / 暴跌」的标的实时挑出来，并留下当日审计日志。

监控池：`rankings.constituents()` 委托 `universe.universe()` ——
S&P 500 + NASDAQ 100 + S&P MidCap 400 + S&P SmallCap 600 + Nasdaq 市值补充 + 精选热门股，约 2240 只
（覆盖 NDX 独有权重股、中概主流标的与小盘成长）。标签**不要写死具体数字**。

设计（复用 rankings.py 已验证的模式，不重造轮子）：
- 行情：yfinance 批量日线（盘中最后一根 bar 即实时价），分块 100 × 4 线程；
  TTL 45 秒 + stale-while-revalidate —— HTTP 请求永不等待网络。
- 覆盖率闸门：新数据 < 旧缓存 80% 时丢弃本次刷新 —— rankings.py 踩过的坑
  （yfinance 部分超时把 503 只好数据覆盖成 228 只），这里直接规避。
- 量比：今日成交量 ÷ 前 N 个交易日全天均量。盘中该值天然被「时间进度」
  稀释（开盘 30 分钟量比 0.5 ≈ 全天 4 倍活跃度），前端展示原始值即可。
- bar 日期：日线最后一根 bar 的日期随行返回（as_of）。非交易时段 /
  盘前时最后一根 bar 是上一交易日的，必须显式标注，否则用户会把
  昨天的涨跌幅当成今天的（盘前 ≠ 实时）。
- 日志：runtime/cache/movers/YYYY-MM-DD.jsonl 逐次追加（审计流），
  仅常规盘写入；API 端聚合成「今日上榜次数 / 首次上榜时间」，
  让「一开盘就在涨」和「刚突然拉升」可区分。
- 市场状态：markets.calendar.market_status("US")（节假日 / 半日市都有）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .config import CACHE_DIR
from .quote_cache import QuoteCache, accept_refresh as _accept_refresh

_MOVERS_DIR = CACHE_DIR / "movers"
_QUOTES_SNAPSHOT = _MOVERS_DIR / "quotes.json"
_QUOTE_TTL = 180         # 秒。池子扩到 2241 只后全量抓取 ~2min —— TTL 必须 > 抓取耗时，
                         # 否则后台永远在刷新、永远 stale（120s 是 1541 只时代的值）
_CHUNK = 100
_WORKERS = 4
_HIST_DAYS = 10          # 拉 10 根日线：1 根当日 + 9 根算量比

# 全池行情缓存机制（磁盘读写 / 后台单飞刷新 / 覆盖率闸门）已按铁律 9 抽到
# `quote_cache.py`，与 rankings.py 共用同一实现；本模块只保留 movers 特有的
# 解析（量比 / bar_date）与编排。
_qc = QuoteCache(
    snapshot_path=_QUOTES_SNAPSHOT,
    ttl=_QUOTE_TTL,
    chunk=_CHUNK,
    workers=_WORKERS,
    thread_name="movers-refresh",
    include_updated=True,
)


def _load_disk() -> tuple[float, dict[str, dict[str, Any]]]:
    return _qc.load_disk()


def _save_disk(quotes_map: dict[str, dict[str, Any]]) -> None:
    _qc.save_disk(quotes_map)


# ---------------- 批量行情 ----------------
def _parse_chunk(chunk: list[str], df: Any) -> dict[str, dict[str, Any]]:
    """把 yf.download 的分块结果解析成 {symbol: quote}。

    与 rankings._parse_chunk 的差异：多保留 bar 日期（as_of 判定用）
    与量比（今日量 ÷ 此前各日均量）。
    """
    out: dict[str, dict[str, Any]] = {}
    if df is None or df.empty:
        return out
    for sym in chunk:
        try:
            sub = df if len(chunk) == 1 else df[sym]
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            close = float(sub["Close"].iloc[-1])
            prev = float(sub["Close"].iloc[-2]) if len(sub) > 1 else close
            vol = float(sub["Volume"].iloc[-1]) if "Volume" in sub else 0.0
            if close <= 0:
                continue
            prev_vols = [float(v) for v in sub["Volume"].iloc[:-1] if v and v > 0]
            vol_ratio = round(vol / (sum(prev_vols) / len(prev_vols)), 2) if prev_vols else None
            try:
                bar_date = str(sub.index[-1].date())
            except Exception:  # noqa: BLE001 —— 索引形态异常时不该炸整批
                bar_date = ""
            out[sym] = {
                "price": round(close, 4),
                "prev_close": round(prev, 4),
                "change_pct": round((close - prev) / prev * 100, 2) if prev else 0.0,
                "volume": vol,
                "amount": round(close * vol, 0),
                "vol_ratio": vol_ratio,
                "bar_date": bar_date,
            }
        except Exception:  # noqa: BLE001
            continue
    return out


def _fetch_all_quotes() -> dict[str, dict[str, Any]]:
    """并发抓全部成分股行情（分块 yf.download + 线程池）。"""
    from .rankings import constituents

    syms = [c["symbol"] for c in constituents()["constituents"]]
    return _qc.fetch_all(syms, _parse_chunk, period=f"{_HIST_DAYS}d")


def _bg_refresh() -> None:
    """后台刷新行情并落盘。同一时刻仅一路（_refreshing 旗标保证）。"""
    _qc.bg_refresh(_fetch_all_quotes)


def quote_cache_meta() -> dict[str, Any]:
    return _qc.meta()


def quotes(force: bool = False) -> dict[str, dict[str, Any]]:
    """全部成分股的快速行情（stale-while-revalidate，TTL 见 _QUOTE_TTL）。

    force=True：跳过新鲜度判定直接起后台刷新（手动刷新按钮用）——
    立即返回当前缓存，刷完后由下一轮轮询取到新数据，绝不在请求线程里联网。
    """
    return _qc.get(_fetch_all_quotes, force=force)


# ---------------- 当日审计日志 ----------------
def _log_path(day: str | None = None) -> Path:
    return _MOVERS_DIR / f"{day or time.strftime('%Y-%m-%d')}.jsonl"


def _append_log(rows: list[dict[str, Any]], threshold: float) -> int:
    """把本次触发的行追加进当日 jsonl。失败静默（日志不能拖垮监控本身）。"""
    try:
        _MOVERS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        lines = [
            json.dumps({
                "ts": ts,
                "threshold": threshold,
                "symbol": r["symbol"],
                "dir": "up" if float(r.get("change_pct") or 0) > 0 else "down",
                "change_pct": r.get("change_pct"),
                "price": r.get("price"),
                "volume": r.get("volume"),
                "amount": r.get("amount"),
            }, ensure_ascii=False)
            for r in rows
        ]
        with _log_path().open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        return len(lines)
    except Exception:  # noqa: BLE001
        return 0


def today_log_summary() -> dict[str, Any]:
    """聚合当日日志：总触发次数 / 触发标的数 / 上榜最频繁的标的。

    同一只股票一整天反复上榜（hits 高）= 持续异动；
    first_seen 在开盘后几分钟内 = 一开盘就被资金选中。
    """
    path = _log_path()
    per: dict[str, dict[str, Any]] = {}
    events = 0
    try:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    x = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                events += 1
                sym = str(x.get("symbol") or "")
                if not sym:
                    continue
                d = per.setdefault(sym, {"symbol": sym, "hits": 0, "first_seen": x.get("ts"),
                                         "last_change_pct": x.get("change_pct"),
                                         "dir": x.get("dir")})
                d["hits"] += 1
                d["last_change_pct"] = x.get("change_pct")
    except Exception:  # noqa: BLE001
        pass
    top = sorted(per.values(), key=lambda d: -int(d["hits"]))[:5]
    return {"events": events, "symbols": len(per), "top_repeat": top}


# ---------------- 全市场榜（yf.screen，覆盖固定池外的标的） ----------------
# 教训（2026-09-28）：MDB 暴跌 18.9% 但不在本地池子里，固定池监控全程漏报。
# 任何"固定成分股清单"都有覆盖缺口 —— 全市场涨跌幅榜（yf.screen）是补盲的正确来源。
_screen_lock = threading.Lock()
_screen_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
_screen_state: dict[str, Any] = {"last_error": "", "ok": None}
_SCREEN_TTL = 60
_SCREEN_COUNT = 40          # 每榜取前 40（day_gainers / day_losers）


def market_screen() -> list[dict[str, Any]]:
    """全市场涨跌幅榜。标的带 src="market"，与本地池（src="pool"）合并去重。

    失败返回缓存旧值或空 —— 全市场榜只是补盲源，绝不能拖垮监控主流程。
    最后一次失败原因记录在 _screen_state["last_error"]（movers 响应带出，可诊断）。
    同时写 runtime/cache/movers/_screen.log 便于离线排障（服务 stdout 可能被缓冲）。
    ⚠️ 本函数内对 _screen_cache 有赋值 —— 必须 `global` 声明，否则顶部读取直接
    UnboundLocalError（实证：曾被 merge 的静默 except 吞掉，全市场榜永远为空）。
    """
    global _screen_cache

    def _dbg(msg: str) -> None:
        try:
            with (_MOVERS_DIR / "_screen.log").open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:  # noqa: BLE001
            pass

    ts, cached = _screen_cache
    if cached and time.time() - ts < _SCREEN_TTL:
        return cached
    rows: list[dict[str, Any]] = []
    err = ""
    try:
        import yfinance as yf

        for kind, key in (("up", "day_gainers"), ("down", "day_losers")):
            try:
                res = yf.screen(key, count=_SCREEN_COUNT)
                for x in res.get("quotes", []):
                    chg = x.get("regularMarketChangePercent")
                    price = x.get("regularMarketPrice")
                    sym = str(x.get("symbol") or "").strip()
                    if not sym or not isinstance(chg, (int, float)) or not isinstance(price, (int, float)):
                        continue
                    rows.append({
                        "symbol": sym,
                        "name": str(x.get("shortName") or x.get("longName") or ""),
                        "sector": "",
                        "price": round(float(price), 4),
                        "change_pct": round(float(chg), 2),
                        "volume": x.get("regularMarketVolume") or None,
                        "amount": None,
                        "vol_ratio": None,
                        "src": "market",
                        "side": kind,
                    })
            except Exception as exc:  # noqa: BLE001 —— 单榜失败不影响另一榜
                err = f"{key}: {type(exc).__name__}: {exc}"[:160]
        if rows:
            with _screen_lock:
                _screen_cache = (time.time(), rows)
            _screen_state["ok"] = True
            _screen_state["last_error"] = err
        elif not cached:
            _screen_state["ok"] = False
            _screen_state["last_error"] = err or "screen 返回 0 行"
        _dbg(f"screen done rows={len(rows)} err={err!r}")
        return rows
    except Exception as exc:  # noqa: BLE001
        _screen_state["ok"] = False
        _screen_state["last_error"] = f"{type(exc).__name__}: {exc}"[:160]
        _dbg(f"screen FAILED {_screen_state['last_error']}")
        return cached


# ---------------- 常驻监控任务（开关 + 持续运行） ----------------
# 已按铁律 9 拆到 movers_monitor.py（FILE_SIZE_DEBT Batch D-3）。
# 这里 re-export 保持 `from app.movers import set_monitor_cfg` 等旧引用路径不变。
from .movers_monitor import (  # noqa: E402,F401
    _ensure_thread,
    _monitor_cfg,
    _monitor_loop,
    monitor_status,
    resume_monitor,
    set_monitor_cfg,
)


def __getattr__(name: str) -> Any:
    """PEP 562：把监控线程的内部状态属性转发到 movers_monitor。

    常驻监控状态（_mon_state / _mon_thread / _mon_lock / _stop_event）的真实
    拥有者是 movers_monitor（线程在那里启停），但测试与排障代码习惯直接读
    `app.movers._mon_state` —— 转发保证读到的是**活的**状态对象。
    """
    if name in ("_mon_state", "_mon_thread", "_mon_lock", "_stop_event", "_CFG_KEY"):
        from . import movers_monitor as _mm

        return getattr(_mm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------- AI 解读 ----------------
def analyze(model: str = "", threshold: float = 3.0, limit: int = 10) -> dict[str, Any]:
    """用所选模型解读当前暴涨/暴跌榜单（监控面板的「AI 解读」）。

    模型名解析复用 ai_analyst._llm_config_for：QD_AI_EXTRA_MODELS 别名 / 设置页
    全局模型 / 网关模型 id（如 cn:glm-5.3-flash）都可直接传。给 LLM 的事实除了
    榜单行情，还对最极端的各 2 只抓最近新闻标题 —— 让归因有据可依而不是编故事。
    LLM 不可用/失败时降级为本地统计文案（engine="local"）。
    """
    d = movers(threshold=threshold, limit=limit)
    gainers, losers = d["gainers"], d["losers"]

    def _brief(rows: list[dict[str, Any]], side: str) -> str:
        if not rows:
            return "（无）"
        lines = [
            f"- {r['symbol']} {r.get('name_cn') or r.get('name') or ''} "
            f"{r.get('change_pct')}%（价 {r.get('price')}"
            + (f"，量比 {r.get('vol_ratio')}" if r.get("vol_ratio") else "")
            + ("，全市场榜" if r.get("src") == "market" else "，本地池") + "）"
            for r in rows
        ]
        return "\n".join(lines)

    # 新闻上下文：只给最极端的各 2 只，各 3 条标题（控制 token 与时延）
    news_block = ""
    try:
        from .ai_analyst import _news_context

        for rows in (gainers[:2], losers[:2]):
            for r in rows:
                items = _news_context(r["symbol"], limit=3)
                titles = "；".join(
                    str(x.get("标题") or "")[:80] for x in items if x.get("标题")
                )
                if titles:
                    news_block += f"\n[{r['symbol']} 最近新闻标题] {titles}"
    except Exception:  # noqa: BLE001 —— 新闻拿不到就让 LLM 只看行情
        news_block = ""

    facts = (
        f"监控池：{d['universe']}（含全市场涨跌幅榜补盲）\n"
        f"市场时段：{d['status'].get('session_label')}\n"
        f"暴涨榜（≥+{d['threshold']}%）：\n{_brief(gainers, 'up')}\n"
        f"暴跌榜（≤-{d['threshold']}%）：\n{_brief(losers, 'down')}\n"
        f"今日累计异动 {d['log'].get('events', 0)} 次 / {d['log'].get('symbols', 0)} 只。"
        + news_block
    )
    out: dict[str, Any] = {"engine": "local", "text": "", "model": model}
    prompt = (
        "你是量化监控助手。以下是一份美股盘中暴涨/暴跌监控榜单" + ("" if not news_block else "（附部分标的的新闻标题）") + "。\n"
        "要求：1) 只基于给定数据与新闻标题解读，绝不编造未提供的财报/事件事实；"
        "2) 先讲整体结构（暴涨/暴跌的行业与大小盘分布、是否集中在少数板块）；"
        "3) 点名最值得注意的 2-3 只，说明理由；有新闻标题的可以关联，没有的明确说「原因待核实」；"
        "4) 一句话风险提示。控制在 250 字以内，简体中文。\n\n" + facts
    )
    if model:
        try:
            from .ai_analyst import _llm_call

            text = (_llm_call(
                [{"role": "system", "content": "你是严谨的量化监控解读助手，只基于给定数据，不编造事实，简体中文输出。"},
                 {"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=5000, model_name=model, timeout=120,
                reasoning_effort="low",   # P0 铁律：推理模型思维链会烧光 max_tokens → 正文空
            ) or "").strip()
            if text:
                out["text"], out["engine"] = text, "llm"
        except Exception as exc:  # noqa: BLE001 —— LLM 失败降级本地
            out["llm_error"] = f"{type(exc).__name__}: {exc}"[:200]
    else:
        # 未显式选模型：配置了全局 LLM 才用默认模型；否则走本地统计文案
        try:
            from .ai_analyst import ai_configured

            configured = ai_configured()
        except Exception:  # noqa: BLE001
            configured = False
        if configured:
            try:
                from .ai_analyst import _llm_call

                text = (_llm_call(
                    [{"role": "system", "content": "你是严谨的量化监控解读助手，只基于给定数据，不编造事实，简体中文输出。"},
                     {"role": "user", "content": prompt}],
                    temperature=0.3, max_tokens=5000, model_name="", timeout=120,
                    reasoning_effort="low",
                ) or "").strip()
                if text:
                    out["text"], out["engine"] = text, "llm"
            except Exception as exc:  # noqa: BLE001
                out["llm_error"] = f"{type(exc).__name__}: {exc}"[:200]
    if not out["text"]:
        up_secs = sorted({r.get("sector") or "未知" for r in gainers})
        dn_secs = sorted({r.get("sector") or "未知" for r in losers})
        out["text"] = (
            f"本地统计解读（未调用模型）：暴涨 {len(gainers)} 只集中于 {('、'.join(up_secs[:3]))}；"
            f"暴跌 {len(losers)} 只集中于 {('、'.join(dn_secs[:3]))}。"
            f"最极端：{gainers[0]['symbol'] if gainers else '—'} / {losers[0]['symbol'] if losers else '—'}。"
            f"今日累计 {d['log'].get('events', 0)} 次异动。配好「设置 → AI 分析」后可选模型生成深度解读。"
        )
    return out

def movers(threshold: float = 3.0, limit: int = 15, force: bool = False) -> dict[str, Any]:
    """暴涨 / 暴跌监控主入口。

    - threshold：涨跌幅阈值（%），两端都取绝对值口径（+3% 与 -3%）
    - 涨幅榜按涨幅降序、跌幅榜按跌幅降序（最极端的在前）
    - 命中行附带当日统计（hits / first_seen），可区分「持续异动」与「刚启动」
    - **双源**：本地池（src="pool"，带量比/成交额）+ 全市场涨跌幅榜
      （src="market"，覆盖固定池外标的 —— MDB 2026-09-28 暴跌漏报的教训）
    - force=True：手动刷新 —— 行情即使还新鲜也强制起一轮后台抓取
    """
    from .markets.calendar import market_status
    from .rankings import constituents

    try:
        threshold = max(0.5, min(20.0, float(threshold)))
    except (TypeError, ValueError):
        threshold = 3.0
    try:
        limit = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        limit = 15

    status = market_status("US").as_dict()
    us_today = str(status.get("now_local", ""))[:10]

    cons = {c["symbol"]: c for c in constituents()["constituents"]}
    qs = quotes(force=force)
    meta = quote_cache_meta()

    note = ""
    if not qs:
        note = "行情首次预热中（全池约 2 分钟），页面会自动刷新"
    rows: list[dict[str, Any]] = []
    as_of = ""
    for sym, q in qs.items():
        m = cons.get(sym, {})
        rows.append({
            "symbol": sym,
            "name": m.get("name", ""),
            "sector": m.get("sector", ""),
            "src": "pool",
            **q,
        })
        bd = str(q.get("bar_date") or "")
        if bd > as_of:
            as_of = bd

    # 全市场榜补盲：本地池没有的标的直接并入（MDB 案例 —— 池外暴跌必须可见）
    pool_syms = {r["symbol"] for r in rows}
    market_extra = 0
    screen_err = ""
    try:
        for mr in market_screen():
            if mr["symbol"] in pool_syms:
                continue
            rows.append(mr)
            market_extra += 1
    except BaseException as _se:  # noqa: BLE001 —— 补盲源失败不影响主流程；异常带出响应便于诊断
        screen_err = f"{type(_se).__name__}: {_se}"[:200]

    if as_of and us_today and as_of != us_today:
        note = note or f"当前非盘中（{status.get('session_label') or status.get('reason') or '休市'}），行情为最近交易日 {as_of} 收盘快照"

    gainers = [r for r in rows if isinstance(r.get("change_pct"), (int, float)) and r["change_pct"] >= threshold]
    losers = [r for r in rows if isinstance(r.get("change_pct"), (int, float)) and r["change_pct"] <= -threshold]
    gainers.sort(key=lambda r: -float(r["change_pct"]))
    losers.sort(key=lambda r: float(r["change_pct"]))     # 最极端的负值在前
    gainers, losers = gainers[:limit], losers[:limit]

    # 中文名注入（仅命中行，量少；失败不影响主流程）
    hit_syms = [r["symbol"] for r in gainers + losers]
    if hit_syms:
        try:
            from .company import enrich

            info = enrich(hit_syms)
            for r in gainers + losers:
                x = info.get(r["symbol"]) or {}
                r["name_cn"] = x.get("name_cn", "")
        except Exception:  # noqa: BLE001
            pass

    # 当日统计合并进命中行 + 审计日志（仅常规盘写，避免盘前静止行情刷屏）
    summary = today_log_summary()
    per_sym = {d["symbol"]: d for d in summary.get("top_repeat", [])}
    for r in gainers + losers:
        d = per_sym.get(r["symbol"])
        if d:
            r["hits"] = d["hits"]
            r["first_seen"] = d["first_seen"]

    if status.get("session") == "regular" and as_of == us_today:
        _append_log(gainers + losers, threshold)
        summary = today_log_summary()          # 含刚写入的一批

    return {
        "universe": f"美股全池 {len(cons)} 只 + 全市场榜",
        "covered": len(rows),
        "market_extra": market_extra,
        "threshold": threshold,
        "limit": limit,
        "as_of": as_of or None,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "quotes_updated": meta.get("updated"),   # 行情真正抓取完成的时刻（前端「上次更新」）
        "status": status,
        "stale": meta["stale"],
        "refreshing": meta["refreshing"],
        "quote_age_sec": meta["age_sec"],
        "last_refresh_ok": meta.get("last_refresh_ok"),
        "note": note,
        "screen": {"ok": _screen_state.get("ok"), "error": (screen_err or _screen_state.get("last_error")) or None},
        "gainers": gainers,
        "losers": losers,
        "log": summary,
    }
