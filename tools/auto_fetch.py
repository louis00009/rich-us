"""QuantDesk 自动新闻抓取执行器（无需 AI Agent 联网——直接拉新闻源）。

流程：poll 领任务 → 东财新闻搜索（公司名/代码，title 相关性过滤）→
提交事件到 Bridge → done。可挂 Windows 计划任务 / cron 每 15 分钟。

用法：
    python tools/auto_fetch.py --token-file backend/runtime/bridge_token.txt
    python tools/auto_fetch.py --once NVDA,AAPL      # 只抓指定标的（调试）
    python tools/auto_fetch.py --dry-run NVDA        # 只看抓到什么，不提交
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787/api"
UA = {"User-Agent": "Mozilla/5.0 QuantDesk-AutoFetch"}
MAX_PER_SYMBOL = 6          # 每家每次最多提交条数
DEFAULT_DAYS = 7            # 只收最近 N 天新闻

# 类别粗分类（标题关键词 → category）
_CAT_RULES = [
    (r"减持|增持|回购|套现|出售", "personnel"),
    (r"财报|业绩|营收|指引|季报", "earnings"),
    (r"合作|签约|协议|战略|订单|中标", "partnership"),
    (r"监管|调查|罚款|诉讼|禁令|关税|出口", "regulatory"),
    (r"发布|推出|上线|首发|新品|芯片|GPU|模型", "product_launch"),
    (r"人事|任命|离职|聘请|CEO|CFO|总裁", "personnel"),
]

_TOKEN_FILE = Path(__file__).resolve().parent.parent / "backend" / "runtime" / "bridge_token.txt"


def _http(url: str, method: str = "GET", data=None, headers=None, timeout=30):
    """本机 Bridge 调用：trust_env=False 确保 127.0.0.1 不走代理。"""
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    r = httpx.request(method, url, content=body, headers={
        "Content-Type": "application/json", **(headers or {})}, timeout=timeout, trust_env=False)
    return json.loads(r.read())


def bridge(token: str, path: str, method: str = "GET", data=None):
    return _http(BASE + path, method, data, {"X-Intel-Token": token})


def fetch_em_news(keyword: str, page_size: int = 10) -> list[dict]:
    """东财全网新闻搜索（时间倒序）。返回 [{date,title,url,media}]。"""
    param = json.dumps({
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                                       "pageIndex": 1, "pageSize": page_size,
                                       "preTag": "", "postTag": ""}},
    }, ensure_ascii=False)
    url = "https://search-api-web.eastmoney.com/search/jsonp?cb=x&param=" + urllib.parse.quote(param)
    try:
        r = httpx.get(url, headers=UA, timeout=15)          # 外网：走系统代理
        t = r.text
        body = t[t.index("(") + 1:t.rindex(")")]
        arts = (json.loads(body).get("result") or {}).get("cmsArticleWebOld") or []
    except Exception:
        return []
    out = []
    for a in arts:
        out.append({
            "date": str(a.get("date") or "")[:10],
            "title": re.sub(r"</?em>", "", str(a.get("title") or "")),
            "url": str(a.get("url") or ""),
            "media": str(a.get("mediaName") or ""),
            "summary": re.sub(r"<[^>]+>", "", str(a.get("content") or ""))[:300],
        })
    return out


def classify(title: str) -> str:
    for pat, cat in _CAT_RULES:
        if re.search(pat, title):
            return cat
    return "other"


def gather_events(symbol: str, search_kws: list[str], match_kws: list[str], cutoff: str) -> list[dict]:
    """抓取并过滤一家公司的新闻 → 事件列表。

    search_kws：用于东财搜索的关键词（取前 2 个）；match_kws：标题相关性别名
    （代码/英文名/中文名任一命中即相关——NVDA 与 NVIDIA 必须互通）。
    """
    seen_titles: set[str] = set()
    events: list[dict] = []
    match_lowers = [m.lower() for m in match_kws if m]
    for kw in search_kws[:2]:
        for art in fetch_em_news(kw, 10):
            title = art["title"]
            norm = re.sub(r"\s+", "", title.lower())
            if norm in seen_titles:
                continue
            # 相关性：标题含任一别名（代码/全称/中文名）
            if not any(m in title.lower() for m in match_lowers):
                continue
            if not art["date"] or art["date"] < cutoff:
                continue
            seen_titles.add(norm)
            events.append({
                "symbol": symbol,
                "occurred_on": art["date"],
                "category": classify(title),
                "title": title[:300],
                "summary": art["summary"],
                "source_name": art["media"],
                "source_url": art["url"],
                "sentiment": "neutral",
                "impact": 3,
            })
            if len(events) >= MAX_PER_SYMBOL:
                return events
    return events[:MAX_PER_SYMBOL]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token-file", default=str(_TOKEN_FILE))
    ap.add_argument("--once", default="", help="只抓指定标的（逗号分隔），不 poll")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--agent", default="autofetch")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--throttle-minutes", type=int, default=0,
                    help="节流：距上次真正抓取不足 N 分钟则直接退出（0=关闭）")
    args = ap.parse_args()

    token = Path(args.token_file).read_text().strip() if Path(args.token_file).exists() else ""
    if not token:
        print("bridge_token 缺失：", args.token_file)
        return 1

    # 节流：状态文件记录上次真正抓取时间（调度器高频触发时避免打爆新闻源）
    stamp_file = Path(args.token_file).parent / "autofetch_last.txt"
    if args.throttle_minutes > 0 and stamp_file.exists():
        try:
            last = dt.datetime.fromisoformat(stamp_file.read_text().strip())
            gap = (dt.datetime.now() - last).total_seconds() / 60
            if gap < args.throttle_minutes:
                print(f"节流：距上次抓取 {gap:.0f} 分钟 < {args.throttle_minutes} 分钟，跳过本轮")
                return 0
        except Exception:  # noqa: BLE001
            pass
    stamp_file.parent.mkdir(parents=True, exist_ok=True)
    stamp_file.write_text(dt.datetime.now().isoformat())

    cutoff = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
    today = dt.date.today().isoformat()

    # 领任务：{symbol: [keywords]}（中文名 + 代码）
    tasks: dict[str, list[str]] = {}
    if args.once:
        for sym in [x.strip().upper() for x in args.once.split(",") if x.strip()]:
            kws = [sym]
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
                from app.company import enrich

                info = enrich([sym]).get(sym) or {}
                prof = info.get("name") or ""
                cn = info.get("name_cn") or ""
                kws += [x for x in (prof, cn) if x]
            except Exception:  # noqa: BLE001
                pass
            tasks[sym] = list(dict.fromkeys(kws))
    else:
        poll = bridge(token, "/intel/bridge/poll?agent=" + args.agent)
        for t in poll.get("tasks") or []:
            sym = t.get("symbol", "")
            name = t.get("name") or ""
            tasks[sym] = [name or sym, sym]
        if not tasks:
            print("无到期任务（由平台抓取周期节流）")
            return 0

    print(f"[{today}] 待抓 {len(tasks)} 家：{list(tasks)}")

    all_events: list[dict] = []
    for sym, keywords in tasks.items():
        try:
            evs = gather_events(sym, keywords, keywords, cutoff)
            if args.dry_run:
                print(f"  {sym}: {len(evs)} 条（dry-run）")
                for e in evs:
                    print("   -", e["occurred_on"], e["title"][:50])
                continue
            if not evs:
                print(f"  {sym}: 无新新闻")
                continue
            r = bridge(token, "/intel/bridge/events", "POST",
                       {"agent": args.agent, "events": evs})
            print(f"  {sym}: 提交 {r.get('inserted', 0)} 条（重复 {r.get('duplicates', 0)}）")
            all_events.extend(evs)
        except Exception as exc:  # noqa: BLE001
            print(f"  {sym}: 失败 {type(exc).__name__}: {exc}")

    if args.dry_run:
        return 0

    bridge(token, "/intel/bridge/done", "POST", {
        "agent": args.agent,
        "note": f"自动抓取完成：{len(tasks)} 家，提交 {len(all_events)} 条事件",
    })
    print(f"完成：{len(tasks)} 家 / {len(all_events)} 条事件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
