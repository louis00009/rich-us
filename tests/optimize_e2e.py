"""组合优化 · 真实 HTTP 端到端演示。

连接一个**已启动**的本机服务（默认 127.0.0.1:8787），跑一次完整链路的组合优化
并把逐标的的权重/收益/波动/风险贡献打成人能看的表格。

区别于 run_checks.py 的 optimize 段：那边用合成数据做回归断言（快、可复现），
这里用真实行情看结果是否符合金融直觉（相关簇识别、低波动资产是否被多配）。
两者都需要账户 trader / QuantDesk#2026（run_checks.py 会自动创建）。

用法：
    cd backend && .venv/Scripts/python.exe ../tests/optimize_e2e.py
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8787/api"


def post(path, body, token=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


tok = post("/auth/login", {"username": "trader", "password": "QuantDesk#2026"})["access_token"]
print("登录成功")

res = post("/optimize/run", {
    "symbols": ["SPY", "QQQ", "IWM", "EFA", "EEM", "AGG", "GLD"],
    "start": "2019-01-01",
    "objective": "max_sharpe",
    "cov_method": "ledoit_wolf",
    "return_method": "shrunk",
    "max_weight": 0.30,
    "corr_threshold": 0.80,
    "max_cluster_weight": 0.45,
    "include_frontier": True,
}, tok)

print(f"\n标的 {len(res['symbols'])} 个 · 数据源 {res['data_source_used']} · 可行 {res['feasible']}")
print(f"权重合计 {sum(res['weights'].values()):.6f}")
print(f"预期年化收益 {res['portfolio']['ann_return']*100:.2f}%  "
      f"波动 {res['portfolio']['ann_vol']*100:.2f}%  "
      f"夏普 {res['portfolio']['sharpe']:.2f}")
print(f"等权基准      收益 {res['benchmark_equal_weight']['ann_return']*100:.2f}%  "
      f"波动 {res['benchmark_equal_weight']['ann_vol']*100:.2f}%  "
      f"夏普 {res['benchmark_equal_weight']['sharpe']:.2f}")
print(f"有效标的数 {res['portfolio']['effective_n']:.2f} / 名义 {len(res['symbols'])}")
print(f"前沿点数 {len(res['frontier'])} · 相关簇 {res['clusters']}")
print("\n逐标的一览：")
print(f"{'标的':<6}{'权重':>9}{'年化收益':>11}{'年化波动':>11}{'夏普':>8}{'风险贡献':>11}")
for a in sorted(res["assets"], key=lambda x: -x["weight"]):
    print(f"{a['symbol']:<6}{a['weight']*100:>8.2f}%{a['ann_return']*100:>10.2f}%"
          f"{a['ann_vol']*100:>10.2f}%{a['sharpe']:>8.2f}{a['risk_contrib_pct']:>10.1f}%")

print("\n备注：")
for n in res["notes"]:
    print("  ·", n)
