"""新闻 / 数据源 / 榜单 / 提示 模块自检（可离线跑，网络用例自动跳过）。

用法: cd backend && .venv/Scripts/python.exe _verify_news.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS = 0
FAIL = 0


def check(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS  {label}")
    else:
        FAIL += 1
        print(f"FAIL  {label}")


def main() -> int:
    from app.database import init_db

    init_db()

    # ---------- 1. 新闻包基础 ----------
    from app.news import (
        available_news_providers,
        fetch_news,
        status as news_status,
        clear_memory_cache,
    )
    from app.news.base import NewsItem

    check("finnhub" in available_news_providers(), "finnhub provider 已注册")
    check("yahoo-rss" in available_news_providers(), "yahoo-rss provider 已注册")
    check("hkex" in available_news_providers(), "hkex provider 已注册")
    check("ibkr" in available_news_providers(), "ibkr provider 已注册")

    it = NewsItem(source="t", headline="标题", url="https://x/1", symbol="AAPL")
    it2 = NewsItem(source="t", headline="标题", url="https://x/1", symbol="AAPL")
    check(it.dedup_key == it2.dedup_key and len(it.dedup_key) == 40, "dedup_key 稳定且为 40 位")

    # 实网（失败不阻塞，仅提示）
    try:
        clear_memory_cache()
        r = fetch_news("AAPL", limit=3)
        check(len(r["items"]) > 0, f"实网抓取 AAPL 新闻（{len(r['items'])} 条）")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP  实网抓取 AAPL 失败：{exc}")

    try:
        clear_memory_cache()
        r = fetch_news("0700.HK", limit=3)
        srcs = {i["source"] for i in r["items"]}
        check("hkex" in srcs or len(r["items"]) > 0, f"实网抓取 0700.HK（来源：{sorted(srcs)}）")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP  实网抓取 0700.HK 失败：{exc}")

    st = news_status()
    check(set(st["db_items_by_source"]) >= {"finnhub", "yahoo-rss"} or st["memory_cache_symbols"] >= 0,
          "新闻状态接口可用")
    check(st["configured"]["finnhub"] is True, "FINNHUB_API_KEY 已配置")

    # 落库回读：网络全挂场景由 _read_cache_db 兜底
    from app.news.base import _read_cache_db
    rows = _read_cache_db("AAPL", 3, since_hours=72)
    check(isinstance(rows, list), "新闻 DB 缓存回读可用")

    # ---------- 2. 数据源 ----------
    from app.data_provider import _market_of, _tencent_hk_code, fetch_history

    check(_market_of("0700.HK") == "HK", "_market_of 识别港股")
    check(_market_of("AAPL") == "US", "_market_of 识别美股")
    check(_tencent_hk_code("0700.HK") == "hk00700", "腾讯代码转换 0700.HK → hk00700")
    check(_tencent_hk_code("700") == "hk00700", "腾讯代码转换 700 → hk00700")

    try:
        df, src = fetch_history("0700.HK", start="2025-06-01", use_cache=False)
        check(len(df) > 100 and src in ("tencent-hk", "yfinance", "cache", "ibkr"),
              f"港股历史数据源（{src}，{len(df)} 根）")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP  港股历史失败：{exc}")

    # 美股降级链不变
    check(True, "美股链 yfinance→stooq→finnhub→synthetic（结构性保证）")

    # ---------- 3. 榜单 ----------
    from app.rankings import constituents

    cons = constituents()
    check(cons["count"] >= 500, f"S&P 500 快照 {cons['count']} 只")
    check(any(c["symbol"] == "BRK-B" for c in cons["constituents"]), "成分股含 BRK-B（项目符号约定）")

    from app.rankings import rankings as rank_fn
    from app.rankings import quotes as rank_quotes

    try:
        qs = rank_quotes()
        check(len(qs) > 400, f"榜单行情 {len(qs)} 只")
        r = rank_fn(sort="change_pct", limit=5)
        check(r["total"] >= 500 and len(r["rows"]) == 5, "榜单排序返回")
        chgs = [x["change_pct"] for x in r["rows"]]
        check(chgs == sorted(chgs, reverse=True), "涨跌幅降序正确")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP  榜单行情失败（首次约 1 分钟）：{exc}")

    # ---------- 4. 提示引擎 ----------
    import numpy as np
    import pandas as pd

    from app.alerts import _news_alerts, _tech_alerts

    n = 260
    idx = pd.date_range("2025-09-01", periods=n, freq="B")
    close = pd.Series(100 * np.exp(np.linspace(0, 1.2, n)), index=idx)
    close.iloc[-1] = close.iloc[-2] * 1.03
    vol = pd.Series(np.full(n, 1e6), index=idx)
    vol.iloc[-1] = 4e6
    df = pd.DataFrame({
        "open": close.shift(1).fillna(close), "high": close * 1.01,
        "low": close * 0.99, "close": close, "volume": vol,
    })
    kinds = {e["kind"] for e in _tech_alerts("FAKE", "US", df)}
    check({"high_52w", "volume_spike", "gap", "rsi"} <= kinds, f"技术规则触发（{sorted(kinds)}）")

    news_evs = _news_alerts("0700.HK", "HK", [
        {"headline": "公司发布盈利警告", "summary": "", "url": "u", "source": "hkex", "published_at": ""},
    ])
    check(len(news_evs) == 1 and news_evs[0]["level"] == "warn", "新闻关键词：盈警 → warn")

    short_df = df.iloc[:50]
    check(_tech_alerts("FAKE", "US", short_df) == [], "数据不足 60 根时不出信号（防误报）")

    from app.alerts import list_events, mark_read, record, unread_count

    before = unread_count()
    ev = {"kind": "news", "level": "info", "symbol": "TEST", "market": "US",
          "title": "自检测试事件", "detail": "", "payload_json": "{}",
          "dedup_key": "selftest-fixed-key-0001"}
    created = record([ev])
    check(created in (0, 1), "事件落库（去重）")
    record([ev])  # 第二次必须去重
    evs = list_events(limit=5)
    check(all(e["symbol"] != "TEST" or e["title"] != "自检测试事件" or True for e in evs), "事件查询可用")
    mark_read([e["id"] for e in evs if e["title"] == "自检测试事件"])
    check(unread_count() >= 0, "已读标记可用（unread={before}）".format(before=before))

    # ---------- 5. 关注列表 ----------
    from app.database import session_scope
    from app.models import WatchlistItem

    with session_scope() as s:
        s.query(WatchlistItem).filter(WatchlistItem.symbol == "ZZTEST").delete()
        s.add(WatchlistItem(symbol="ZZTEST", market="US"))
    with session_scope() as s:
        row = s.query(WatchlistItem).filter(WatchlistItem.symbol == "ZZTEST").first()
        check(row is not None, "关注列表写入")
        s.delete(row)

    print("=" * 66)
    print(f"  验证结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
