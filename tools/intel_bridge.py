"""QuantDesk AI 情报中心 · Bridge 客户端（供 WorkBuddy / Claude Code / Codex 等外部 AI Agent 使用）

用法（在 backend 目录或任意可访问 127.0.0.1:8787 的机器上）：
    python tools/intel_bridge.py token                    # 查看 bridge token
    python tools/intel_bridge.py poll [--agent workbuddy] # 拉取本轮任务
    python tools/intel_bridge.py events --file ev.json    # 提交新闻事件（JSON 数组）
    python tools/intel_bridge.py analysis --file an.json  # 提交买入建议（JSON 数组）
    python tools/intel_bridge.py done --note "本轮完成"    # 结束本轮
    python tools/intel_bridge.py run --symbols NVDA,SPY   # 完整流程（需 agent 自带联网搜索时用）

事件 ev.json 格式（数组，字段见下）：
[
  {
    "symbol": "NVDA", "category": "product", "title": "NVIDIA 发布下一代推理芯片",
    "summary": "…", "source_name": "Reuters", "source_url": "https://…",
    "published_at": "2026-09-24", "sentiment": "positive", "importance": "high"
  }
]
分析 an.json 格式：
[
  {
    "symbol": "NVDA", "recommendation": "BUY", "confidence": 72,
    "rationale": "…", "target_price": 210.0, "horizon": "3M",
    "risk_factors": "…", "key_evidence": ["来源1", "来源2"]
  }
]

事件 categories：product/earnings/partnership/regulatory/management/macro/competition/other
建议 recommendation：STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL
"""
import argparse
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8787/api"
AGENT = "workbuddy"


def _req(path, method="GET", data=None, token=""):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Intel-Token", token)
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    with urllib.request.urlopen(req, body, timeout=60) as r:
        return json.loads(r.read())


def _user_login_token():
    """管理端操作（看 token/开监控）需要平台口令登录；bridge 端只用 X-Intel-Token。"""
    import getpass
    pwd = input("平台口令（trader 账户）: ")
    r = _req("/auth/login", "POST", {"username": "trader", "password": pwd})
    return r["access_token"]


def _user_req(path, method="GET", data=None, token=None):
    tok = token or _user_login_token()
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + tok)
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    with urllib.request.urlopen(req, body, timeout=60) as r:
        return json.loads(r.read())


def cmd_token(_args):
    out = _user_req("/intel/overview")
    print("bridge_token:", out.get("bridge_token"))
    print("监控运行中:", bool(out.get("monitor_running")))


def cmd_poll(args):
    out = _req(f"/intel/bridge/poll?agent={args.agent}", token=args.token)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_events(args):
    with open(args.file, encoding="utf-8") as f:
        events = json.load(f)
    out = _req("/intel/bridge/events", "POST", {"agent": args.agent, "events": events}, token=args.token)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_analysis(args):
    with open(args.file, encoding="utf-8") as f:
        analyses = json.load(f)
    out = _req("/intel/bridge/analysis", "POST", {"agent": args.agent, "analyses": analyses}, token=args.token)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_done(args):
    out = _req("/intel/bridge/done", "POST", {"agent": args.agent, "note": args.note}, token=args.token)
    print(json.dumps(out, ensure_ascii=False))


def cmd_start(args):
    out = _user_req("/intel/monitor/start", "POST", {}, token=getattr(args, "token", None))
    print(json.dumps(out, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("token", help="查看 bridge token（需平台口令）")
    p.set_defaults(fn=cmd_token)

    p = sub.add_parser("poll", help="拉取本轮任务")
    p.add_argument("--agent", default=AGENT)
    p.add_argument("--token", required=True, help="X-Intel-Token（情报中心页面可见）")
    p.set_defaults(fn=cmd_poll)

    p = sub.add_parser("events", help="提交新闻事件")
    p.add_argument("--file", required=True)
    p.add_argument("--agent", default=AGENT)
    p.add_argument("--token", required=True)
    p.set_defaults(fn=cmd_events)

    p = sub.add_parser("analysis", help="提交买入建议")
    p.add_argument("--file", required=True)
    p.add_argument("--agent", default=AGENT)
    p.add_argument("--token", required=True)
    p.set_defaults(fn=cmd_analysis)

    p = sub.add_parser("done", help="结束本轮")
    p.add_argument("--note", default="")
    p.add_argument("--agent", default=AGENT)
    p.add_argument("--token", required=True)
    p.set_defaults(fn=cmd_done)

    p = sub.add_parser("start", help="开启一轮监控（管理端）")
    p.add_argument("--token", default=None, help="平台 JWT（不传则交互登录）")
    p.set_defaults(fn=cmd_start)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
