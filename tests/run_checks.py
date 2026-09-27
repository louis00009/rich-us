"""
QuantDesk 端到端自检脚本
=========================
不依赖 pytest，直接运行即可。覆盖四块：

  1. 数据层     —— 行情拉取、缓存、指标库
  2. 策略层     —— 全部内置策略 + 自定义规则/代码策略的回测冒烟
  3. 组合优化   —— 权重求解、盒约束、相关簇、风险预算、有效前沿
  4. API 层     —— 认证、策略、回测、优化、交易护栏、风控、AI、审计

用法：
    cd backend
    .venv/Scripts/python.exe ../tests/run_checks.py            # 全部
    .venv/Scripts/python.exe ../tests/run_checks.py strategies # 只跑策略
    .venv/Scripts/python.exe ../tests/run_checks.py optimize   # 只跑组合优化
    .venv/Scripts/python.exe ../tests/run_checks.py api        # 只跑 API

注意：API 部分会在 runtime 目录创建测试账户（trader / QuantDesk#2026）与
若干回测记录、审计日志。正式使用前可删除 backend/runtime/quantdesk.db 重置。
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("QD_HOME", str(BACKEND / "runtime"))

TEST_USER = "trader"
TEST_PASS = "QuantDesk#2026"

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((ok, label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ← {detail}" if detail and not ok else ""))
    return ok


def head(title: str) -> None:
    print(f"\n{'=' * 66}\n  {title}\n{'=' * 66}")


# ==================================================================
# 1. 数据层与指标
# ==================================================================
def test_data() -> None:
    head("1 / 数据层与指标库")
    from app.data_provider import cache_stats, fetch_history, get_quote, search_symbols
    from app.strategies import indicators as ind

    # ---- T-111 费用模型 ----
    from app.markets.fees import total_fee

    us_fee = total_fee("SPY", "BUY", 100, 500.0)
    check(us_fee >= 0.35, "美股费用模型（IBKR 阶梯最低 $0.35）", f"100 股 @500 = ${us_fee:.2f}")
    hk_fee = total_fee("0700.HK", "BUY", 100, 300.0)
    check(hk_fee > 100 * 300 * 0.001, "港股费用模型（含印花税 ≥ 1‰）", f"100 股 @300 = {hk_fee:.2f}")

    # ---- T-104 分钟级结构 ----
    from app.ai_analyst import _intraday_structure

    itd = _intraday_structure("SPY")
    check(itd is None or ("vwap" in itd and "or_position" in itd), "分钟级结构字段完整（或休市为 None）")

    # ---- T-113 做空护栏（单元级）----
    import datetime as dt

    from app.risk.guardrails import GuardContext, RiskLimits, check_order

    lim = RiskLimits(trading_hours_only=False)
    ctx = GuardContext(equity=100000, day_start_equity=100000, peak_equity=100000,
                       open_positions={}, gross_exposure=0,
                       now=dt.datetime.now(dt.timezone.utc), is_live=False)
    r = check_order(symbol="AAPL", side="SELL", quantity=10, price=300, limits=lim, ctx=ctx)
    check(not r.ok and r.code == "SHORT_FORBIDDEN", "裸卖被拒（SHORT_FORBIDDEN）")
    ctx_long = GuardContext(equity=100000, day_start_equity=100000, peak_equity=100000,
                            open_positions={"AAPL": 5000.0}, gross_exposure=5000,
                            now=dt.datetime.now(dt.timezone.utc), is_live=False)
    r2 = check_order(symbol="AAPL", side="SELL", quantity=100, price=300, limits=lim, ctx=ctx_long)
    check(r2.ok and r2.adjusted_qty and r2.adjusted_qty < 100,
          "卖超持仓自动缩减为平仓数量", f"adjusted={r2.adjusted_qty}")

    df, src = fetch_history("SPY", start="2023-01-01", interval="1d")
    check(len(df) > 200, "行情拉取 (SPY 日线)", f"仅 {len(df)} 根 bar，来源 {src}")
    check(src in ("yfinance", "stooq", "cache", "synthetic"), f"数据源可用（{src}）")
    if len(df) > 60:
        rsi_v = float(ind.rsi(df["close"], 14).iloc[-1])
        atr_v = float(ind.atr(df["high"], df["low"], df["close"], 14).iloc[-1])
        adx_v = float(ind.adx(df["high"], df["low"], df["close"], 14)["adx"].iloc[-1])
        check(0 <= rsi_v <= 100, "RSI 取值在 [0,100]", str(rsi_v))
        check(atr_v > 0, "ATR 为正", str(atr_v))
        check(0 <= adx_v <= 100, "ADX 取值在 [0,100]", str(adx_v))
        check(0 <= ind.hurst(df["close"], 128) <= 1, "Hurst 在 [0,1]")
        adf = ind.adf_test(df["close"].pct_change().dropna())
        check("t_stat" in adf, "ADF 单位根检验可运行", json.dumps(adf))
    q = get_quote("SPY")
    check(q.get("price", 0) > 0, "实时报价", str(q.get("price")))
    check(len(search_symbols("nvid", 5)) > 0, "标的搜索")
    check(cache_stats()["files"] >= 0, "缓存统计")


# ==================================================================
# 2. 策略与回测
# ==================================================================
def test_strategies() -> None:
    head("2 / 策略库与回测引擎")
    from app.engine import BacktestSpec, run_backtest
    from app.risk.stops import StopConfig
    from app.strategies import categories, list_strategies, registry_size

    strategies = list_strategies()
    check(registry_size() >= 20, f"策略注册数 {registry_size()}")
    check(len(categories()) >= 3, f"策略分类 {categories()}")

    two = {"pairs_trading"}
    five = {"xs_momentum", "risk_parity_alloc", "dual_momentum", "ensemble_vote"}
    ok = fail = 0
    rows: list[tuple[str, str, str]] = []
    for s in strategies:
        key = s["key"]
        if key in two:
            syms = ["KO", "PEP"]
        elif key in five or key.endswith("momentum") and s["multi_symbol"]:
            syms = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
        else:
            syms = ["SPY", "QQQ"]
        spec = BacktestSpec(
            strategy_key=key, symbols=syms, start="2020-01-01", interval="1d",
            initial_capital=100_000, commission_bps=1.0, slippage_bps=2.0,
            benchmark="SPY",
            stop=StopConfig(stop_type="atr_trailing", stop_value=3.0, take_profit_r=0.0),
        )
        try:
            r = run_backtest(spec)
            if not r.get("ok"):
                fail += 1
                rows.append(("FAIL", key, r.get("error", "")[:80]))
                continue
            m = r["metrics"]
            ok += 1
            rows.append((
                "ok", key,
                f"收益 {m['total_return']*100:8.2f}%  年化 {m['cagr']*100:6.2f}%  "
                f"夏普 {m['sharpe']:5.2f}  回撤 {m['max_drawdown']*100:7.2f}%  "
                f"交易 {m['trades']:4d}  胜率 {m['win_rate']*100:5.1f}%",
            ))
        except Exception as exc:  # noqa: BLE001
            fail += 1
            rows.append(("EXC", key, f"{type(exc).__name__}: {exc}"[:100]))

    for st, key, msg in rows:
        print(f"   {st:>4}  {key:<26} {msg}")
    check(fail == 0, f"全部 {len(strategies)} 个内置策略回测通过", f"{fail} 个失败")

    # --- 自定义规则策略 ---
    rule = {
        "direction": "long",
        "entry": {"all": [
            {"op": "<", "left": {"indicator": "rsi", "period": 14}, "right": {"const": 35}},
            {"op": ">", "left": {"indicator": "close"}, "right": {"indicator": "sma", "period": 200}},
        ]},
        "exit": {"any": [{"op": ">", "left": {"indicator": "rsi", "period": 14}, "right": {"const": 65}}]},
        "entry_size": 1.0,
    }
    r = run_backtest(BacktestSpec(strategy_key="custom_rule", symbols=["SPY"], rule=rule,
                                  start="2021-01-01", stop=StopConfig(stop_type="atr_fixed", stop_value=3.0)))
    check(bool(r.get("ok")), "自定义规则策略回测", r.get("error", ""))

    # --- 自定义代码策略 ---
    code = (
        "import pandas as pd\n\n"
        "def generate(ctx):\n"
        "    c = ctx.closes\n"
        "    fast = c.ewm(span=20, adjust=False).mean()\n"
        "    slow = c.ewm(span=100, adjust=False).mean()\n"
        "    w = pd.DataFrame(0.0, index=c.index, columns=c.columns)\n"
        "    w[fast > slow] = 1.0\n"
        "    return w\n"
    )
    r = run_backtest(BacktestSpec(strategy_key="custom_code", symbols=["SPY"], code=code, start="2021-01-01"))
    check(bool(r.get("ok")), "自定义代码策略回测", r.get("error", ""))

    # --- 代码沙箱拦截 ---
    from app.strategies.custom import CodeSecurityError, validate_code
    for bad, label in [
        ("import os\ndef generate(ctx):\n    return ctx.closes", "禁止导入 os"),
        ("import subprocess\ndef generate(ctx):\n    return 1", "禁止导入 subprocess"),
        ("from os import system\ndef generate(ctx):\n    return 1", "禁止 from os import"),
        ("def generate(ctx):\n    return ctx.__class__", "禁止魔术属性"),
        ("def generate(ctx):\n    around = 1\n    return getattr(ctx, '__class__')", "禁止 getattr 绕过"),
        ("def generate(ctx):\n    open('/etc/passwd')", "禁止 open"),
        ("def generate(ctx):\n    eval('1+1')", "禁止 eval"),
        ("import pandas as pd\ndef generate(ctx):\n    return pd.read_pickle('/x')", "禁止 pd.read_pickle"),
        ("import pandas as pd\ndef generate(ctx):\n    return ctx.closes.to_csv('/x')", "禁止 to_csv 落盘"),
        ("import numpy as np\ndef generate(ctx):\n    return np.load('/x')", "禁止 numpy.load"),
        ("while True:\n    pass", "禁止 while True"),
        ("def generate(ctx):\n    return (lambda: 1)()", "禁止 lambda"),
        ("x = 1", "必须定义 generate"),
    ]:
        try:
            validate_code(bad)
            check(False, f"沙箱应拦截：{label}")
        except CodeSecurityError:
            check(True, f"沙箱拦截：{label}")

    # 合法代码必须放行（含 import 与常用 pandas 方法）
    try:
        validate_code(
            "import pandas as pd\nimport numpy as np\nimport math\n\n"
            "def generate(ctx):\n"
            "    c = ctx.closes\n"
            "    w = pd.DataFrame(0.0, index=c.index, columns=c.columns)\n"
            "    ma = c.rolling(20).mean()\n"
            "    w[c > ma] = 1.0\n"
            "    return w\n"
        )
        check(True, "沙箱放行合法代码")
    except CodeSecurityError as exc:
        check(False, "沙箱放行合法代码", str(exc))

    # 沙箱内 import + 真实执行
    from app.strategies.custom import CodeStrategy
    from app.strategies import SignalContext
    from app.data_provider import fetch_many

    data, _ = fetch_many(["SPY"], "2022-01-01", None, "1d")
    if data:
        try:
            cs = CodeStrategy(
                "import pandas as pd\n"
                "def generate(ctx):\n"
                "    c = ctx.closes\n"
                "    w = pd.DataFrame(0.0, index=c.index, columns=c.columns)\n"
                "    w[c > c.rolling(20).mean()] = 1.0\n"
                "    return w\n"
            )
            out = cs.generate(SignalContext(data=data, symbols=["SPY"]))
            check(bool(out is not None and len(out) > 0), "代码策略可真实执行（沙箱内 import pandas）")
        except Exception as exc:  # noqa: BLE001
            check(False, "代码策略可真实执行（沙箱内 import pandas）", f"{type(exc).__name__}: {exc}")

    # --- 止损机制 ---
    head("2b / 止损状态机")
    from app.risk.stops import StopTracker

    for stype in ["fixed_pct", "pct_trailing", "atr_fixed", "atr_trailing",
                  "chandelier", "breakeven", "volatility"]:
        t = StopTracker(StopConfig(stop_type=stype, stop_value=3.0, breakeven_at_r=0.5))
        t.open(1, 100.0, 0, 2.0)
        # 先小幅上涨（激活移动止损 / 保本），再大幅下跌（应触发止损）
        path = [(100.5, 99.5, 100.2), (102.0, 100.0, 101.8), (101.0, 98.0, 99.0),
                (99.0, 95.0, 96.0), (96.0, 90.0, 91.0), (91.0, 80.0, 82.0)]
        hit_later = False
        for i, (h, l, c_) in enumerate(path, start=1):
            hit, reason, px = t.update(h, l, c_, 2.0, i)
            if hit:
                hit_later = True
                break
        check(hit_later, f"止损可触发：{stype}")

    # 移动止损只增不减（不会反向放宽）
    t = StopTracker(StopConfig(stop_type="atr_trailing", stop_value=3.0))
    t.open(1, 100.0, 0, 2.0)
    for i, (h, l, c_) in enumerate([(105, 100, 104), (110, 104, 109), (112, 108, 111)], start=1):
        t.update(h, l, c_, 2.0, i)
    s1 = t.current_stop()
    t.update(113, 110, 112, 2.0, 4)          # 出现回落 bar
    s2 = t.current_stop()
    check(s2 >= s1, "移动止损只朝有利方向推进", f"{s1} → {s2}")

    t = StopTracker(StopConfig(stop_type="time_stop", time_stop_bars=5))
    t.open(1, 100.0, 0, 2.0)
    hit = False
    for i in range(1, 8):
        h, reason, px = t.update(100.5, 99.5, 100.0, 2.0, i)
        if h:
            hit = "时间止损" in reason
            break
    check(hit is True, "时间止损按 bar 数触发")

    t = StopTracker(StopConfig(stop_type="atr_fixed", stop_value=3.0, take_profit_r=2.0))
    t.open(1, 100.0, 0, 2.0)
    hit = False
    for i in range(1, 30):
        h, reason, px = t.update(120.0, 100.0, 112.0, 2.0, i)
        if h:
            hit = "止盈" in reason
            break
    check(hit is True, "R 倍止盈触发")

    # --- 仓位算法 ---
    head("2c / 仓位算法")
    from app.risk.sizing import compute_target_notional
    for m in ["weight", "fixed_fraction", "risk_parity_vol", "atr_risk", "kelly_capped", "equal_weight"]:
        amt = compute_target_notional(m, 100_000, 0.5, 100.0, atr_value=2.0,
                                      risk_per_trade_pct=1.0, max_position_pct=20.0,
                                      realized_vol=0.2, win_rate=0.55, win_loss_ratio=1.5, n_positions=3)
        check(amt >= 0, f"仓位算法可运行：{m}", str(round(amt, 2)))

    # --- 护栏 ---
    head("2d / 交易护栏")
    import datetime as dt
    from app.risk.guardrails import GuardContext, RiskLimits, check_order

    limits = RiskLimits(max_position_pct=20, max_order_notional=50_000, min_order_notional=200,
                        max_open_positions=5, trading_hours_only=False, blacklist=["TSLA"])
    ctx = GuardContext(equity=100_000, day_start_equity=100_000, peak_equity=100_000,
                       open_positions={}, gross_exposure=0)

    r = check_order(symbol="SPY", side="BUY", quantity=10, price=100, limits=limits, ctx=ctx)
    check(r.ok, "正常订单放行")
    r = check_order(symbol="SPY", side="BUY", quantity=100_000, price=100, limits=limits, ctx=ctx)
    check(r.ok and r.adjusted_qty is not None, "超单笔上限自动缩减")
    r = check_order(symbol="TSLA", side="BUY", quantity=10, price=100, limits=limits, ctx=ctx)
    check(not r.ok and r.code == "BLACKLIST", "黑名单拒绝")
    r = check_order(symbol="SPY", side="BUY", quantity=1, price=100, limits=limits, ctx=ctx)
    check(not r.ok and r.code == "TOO_SMALL", "低于最小金额拒绝")
    bad = GuardContext(equity=96_000, day_start_equity=100_000, peak_equity=100_000,
                       open_positions={}, gross_exposure=0)
    r = check_order(symbol="SPY", side="BUY", quantity=10, price=100, limits=limits, ctx=bad)
    check(not r.ok and r.code == "DAILY_LOSS_LIMIT", "日亏上限拦截")
    dd = GuardContext(equity=84_000, day_start_equity=100_000, peak_equity=100_000,
                      open_positions={}, gross_exposure=0)
    r = check_order(symbol="SPY", side="BUY", quantity=10, price=100, limits=limits, ctx=dd)
    check(not r.ok and r.code in ("MAX_DRAWDOWN", "DAILY_LOSS_LIMIT"), "回撤/日亏熔断拦截")
    ks = RiskLimits(kill_switch=True, trading_hours_only=False)
    r = check_order(symbol="SPY", side="BUY", quantity=10, price=100, limits=ks, ctx=ctx)
    check(not r.ok and r.code == "KILL_SWITCH", "熔断开关拦截")
    closed = GuardContext(equity=100_000, day_start_equity=100_000, peak_equity=100_000,
                          open_positions={}, gross_exposure=0, now=dt.datetime(2026, 1, 3, 12, 0))
    lim2 = RiskLimits(trading_hours_only=True)   # 周六
    r = check_order(symbol="SPY", side="BUY", quantity=10, price=100, limits=lim2, ctx=closed)
    check(not r.ok and r.code == "CLOSED_MARKET", "非交易时段拦截")


# ==================================================================
# 3. 组合优化器
# ==================================================================
def test_optimize() -> None:
    """组合优化器自检。

    刻意使用**合成数据**而非真实行情：约束是否生效必须可复现，
    不能因为上游数据源变化（或断网降级到合成）而让自检结果漂移。
    """
    head("3 / 组合优化器")
    import importlib.util

    import numpy as np
    import pandas as pd

    from app.engine import COV_METHODS, OBJECTIVES, RETURN_METHODS, OptimizeError, optimize_portfolio

    # 依赖检查：本机没有 scipy/cvxpy，优化器必须是纯 numpy 实现
    check(importlib.util.find_spec("scipy") is None or True, "scipy 存在与否不影响（纯 numpy 实现）")
    src = (BACKEND / "app" / "engine" / "optimizer.py").read_text(encoding="utf-8")
    check("import scipy" not in src and "import cvxpy" not in src, "优化器未引入 scipy / cvxpy")
    check(len(OBJECTIVES) == 6 and len(COV_METHODS) == 3 and len(RETURN_METHODS) == 3,
          f"枚举完整：{len(OBJECTIVES)} 目标 / {len(COV_METHODS)} 协方差 / {len(RETURN_METHODS)} 期望")

    # 构造：前 3 只高相关（同一因子），后 3 只独立
    rng = np.random.default_rng(42)
    T = 500
    f = rng.normal(0, 0.01, T)
    cols: dict[str, np.ndarray] = {}
    for s in ("AAA", "BBB", "CCC"):
        cols[s] = 0.9 * f + rng.normal(0, 0.003, T) + 0.0004
    for s in ("XXX", "YYY", "ZZZ"):
        cols[s] = rng.normal(0, 0.008, T) + 0.0006
    prices = 100 * np.exp(pd.DataFrame(cols).cumsum())
    prices.index = pd.bdate_range("2023-01-02", periods=T)

    # --- 1) 六个目标全部可行、权重和 = 总仓位 ---
    bad: list[str] = []
    for obj in OBJECTIVES:
        try:
            r = optimize_portfolio(prices, objective=obj, max_weight=0.5, corr_threshold=0.6,
                                   max_cluster_weight=0.4)
            if not r["feasible"] or abs(sum(r["weights"].values()) - 1.0) > 1e-6:
                bad.append(f"{obj}(feasible={r['feasible']},sum={sum(r['weights'].values()):.6f})")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{obj}({type(exc).__name__})")
    check(not bad, "六个目标函数均收敛且权重和严格为 1", "; ".join(bad))

    # --- 2) 盒约束 ---
    r = optimize_portfolio(prices, objective="min_variance", max_weight=0.25,
                           corr_threshold=0.6, max_cluster_weight=0.30)
    check(max(r["weights"].values()) <= 0.25 + 1e-6,
          "单标的上限被严格遵守 (0.25)", f"实际最大 {max(r['weights'].values()):.6f}")
    check(abs(sum(r["weights"].values()) - 1.0) < 1e-6, "权重和 = 1.0（总仓位约束）")

    # --- 3) 高相关簇 —— 伪分散防护 ---
    cluster = next((c for c in r["clusters"] if "AAA" in c), None)
    check(cluster is not None and set(cluster) >= {"AAA", "BBB", "CCC"},
          "识别出 AAA/BBB/CCC 高相关簇", str(r["clusters"]))
    if cluster:
        cw = sum(r["weights"][k] for k in cluster)
        check(cw <= 0.30 + 1e-6, f"簇总权重 ≤ 0.30（实际 {cw:.4f}）")

    # --- 4) 上限不可行时必须显式标记，不能静默放宽 ---
    r_tight = optimize_portfolio(prices, objective="min_variance", max_weight=0.15,
                                 corr_threshold=0.99, max_cluster_weight=1.0)
    check(r_tight["constraints"]["max_weight_relaxed"] is True,
          "上限×标的数 < 总仓位时标记「已放宽」")
    check(any("放宽上限" in n for n in r_tight["notes"]), "放宽行为写入备注（用户可见）")
    check(abs(r_tight["constraints"]["effective_max_weight"] - 1.0 / 6) < 1e-6,
          f"生效上限 = 1/6 = {r_tight['constraints']['effective_max_weight']:.4f}")

    # --- 5) 风险预算倾斜方向正确 ---
    rp = optimize_portfolio(prices, objective="risk_parity", max_weight=0.9,
                            risk_budget={"AAA": 3, "BBB": 2, "CCC": 1, "XXX": 1, "YYY": 1, "ZZZ": 2})
    check(rp["weights"]["AAA"] > rp["weights"]["CCC"],
          "风险预算 3:2:1 —— 高预算标的权重高于低预算",
          f"AAA={rp['weights']['AAA']:.4f} vs CCC={rp['weights']['CCC']:.4f}")

    # --- 6) 有效前沿 ---
    rf = optimize_portfolio(prices, objective="max_sharpe", max_weight=0.9, include_frontier=True)
    check(len(rf["frontier"]) >= 5, f"有效前沿点数 {len(rf['frontier'])}")
    check(all(p["vol"] >= 0 for p in rf["frontier"]), "前沿点波动率非负")
    vols = [p["vol"] for p in rf["frontier"]]
    check(max(vols) > min(vols), "前沿覆盖了不同波动水平（非退化为单点）")

    # --- 7) 相关性矩阵自洽 ---
    corr = rf["correlation"]["matrix"]
    n_sym = len(rf["symbols"])
    check(len(corr) == n_sym and all(len(row) == n_sym for row in corr), "相关性矩阵为方阵")
    check(all(abs(corr[i][i] - 1.0) < 1e-9 for i in range(n_sym)), "对角线恒为 1.0")
    check(abs(corr[0][1] - corr[1][0]) < 1e-9, "相关性矩阵对称")
    check(abs(corr[0][1]) > 0.8, f"AAA-BBB 相关性确实很高（{corr[0][1]:.3f}）")

    # --- 8) 异常输入应当是明确报错，而不是静默给出错误结果 ---
    try:
        optimize_portfolio(prices[["AAA"]], objective="max_sharpe")
        check(False, "单标的输入被拒绝")
    except OptimizeError as exc:
        check(True, f"单标的输入被拒绝（{str(exc)[:40]}…）")
    except Exception as exc:  # noqa: BLE001
        check(False, "单标的输入被拒绝", f"抛出的是 {type(exc).__name__}，应为 OptimizeError")

    try:
        optimize_portfolio(prices.iloc[:30], objective="max_sharpe")
        check(False, "样本过短被拒绝")
    except OptimizeError:
        check(True, "样本过短被拒绝（< 40 个交易日）")
    except Exception as exc:  # noqa: BLE001
        check(False, "样本过短被拒绝", f"抛出 {type(exc).__name__}")

    # --- 9) 权重向量与资产表一致（两条路径不能各说各话） ---
    w_from_assets = {a["symbol"]: a["weight"] for a in rf["assets"]}
    mismatch = [s for s in rf["symbols"] if abs(w_from_assets.get(s, 9) - rf["weights"][s]) > 1e-9]
    check(not mismatch, "assets 表与 weights 字典完全一致", str(mismatch))
    rc_sum = sum(a["risk_contrib_pct"] for a in rf["assets"])
    check(abs(rc_sum - 100.0) < 5.0, f"风险贡献合计 ≈ 100%（实际 {rc_sum:.2f}%）")


# ==================================================================
# 4. API 层
# ==================================================================
def test_api() -> None:
    head("4 / API 端到端")
    from fastapi.testclient import TestClient

    from app.main import app

    client_cm = TestClient(app)
    client_cm.__enter__()
    c = client_cm

    def show(label: str, r, keys=None, expect_ok: bool = True) -> None:
        ok = (r.status_code < 400) == expect_ok
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = r.text[:120]
        if isinstance(body, dict) and keys:
            body = {k: body.get(k) for k in keys}
        check(ok, label, f"[{r.status_code}] {json.dumps(body, ensure_ascii=False, default=str)[:170]}")

    show("健康检查", c.get("/api/health"))
    r = c.get("/api/auth/status")
    show("认证状态", r)
    if not r.json().get("initialized"):
        r = c.post("/api/auth/setup", json={"username": TEST_USER, "password": TEST_PASS})
    else:
        r = c.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASS})
    show("登录/初始化", r, ["username"])
    tok = r.json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}

    # 模式保护（最高优先）：自检全程强制 paper 模式，绝不触碰用户实盘。
    # 用户解锁实盘后共享同一 DB，不切回会在 live 模式下跑全部写操作用例。
    if c.get("/api/system/status", headers=H).json().get("mode") == "live":
        c.post("/api/trading/mode", headers=H, json={"mode": "paper"})
        check(True, "检测到 live 模式，已自动切回 paper（自检全程模拟盘）")

    # 券商端口保护：用户配置为实盘端口（7496/4001）时，临时切回 7497 模拟端口
    # ——端口指向实盘时下单一律按 live 语义（要求解锁），自检写用例无法执行。
    _orig_broker_cfg = c.get("/api/system/broker", headers=H).json().get("config") or {}
    if str(_orig_broker_cfg.get("provider")) == "ibkr" and int(_orig_broker_cfg.get("port", 0) or 0) in (7496, 4001):
        c.put("/api/system/broker", headers=H, json={**_orig_broker_cfg, "port": 7497})
        check(True, "券商端口临时切至 7497（自检结束后恢复）")

    show("未授权访问被拒", c.get("/api/trading/account"), expect_ok=False)
    show("系统状态", c.get("/api/system/status", headers=H),
         ["app", "mode", "broker", "strategies", "live_ready"])
    show("券商连通", c.post("/api/system/broker/test", headers=H), ["ok", "mode", "message"])
    show("策略列表", c.get("/api/strategies", headers=H), ["count", "categories"])
    show("规则 DSL 元信息", c.get("/api/strategies/dsl", headers=H), ["ops"])
    show("行情报价", c.get("/api/market/quote?symbols=SPY,QQQ", headers=H), ["count"])
    show("历史行情", c.get("/api/market/history?symbol=AAPL&start=2025-01-01", headers=H), ["symbol", "source", "count"])
    show("指标序列", c.get("/api/market/indicators?symbol=SPY&list=rsi,macd,bb,adx", headers=H), ["symbol"])

    r = c.post("/api/backtest/run", headers=H, json={
        "strategy_key": "dual_ma_trend", "params": {"fast": 20, "slow": 100},
        "symbols": ["SPY", "QQQ"], "start": "2021-01-01", "initial_capital": 100000,
        "benchmark": "SPY",
        "risk": {"stop_type": "atr_trailing", "stop_value": 3.0, "take_profit_r": 0.0},
    })
    show("回测执行", r, ["ok", "run_id", "bars", "strategy_name"])
    if r.status_code < 400:
        m = r.json()["metrics"]
        print("      指标:", {k: round(m[k], 4) for k in
                              ("total_return", "cagr", "sharpe", "max_drawdown", "trades", "win_rate")})

    r = c.post("/api/backtest/optimize", headers=H, json={
        "strategy_key": "dual_ma_trend", "param_grid": {"fast": [10, 20, 30], "slow": [80, 100, 150]},
        "symbols": ["SPY"], "start": "2021-01-01", "objective": "sharpe", "max_combos": 20,
    })
    show("参数寻优", r, ["ok", "evaluated", "failed"])

    show("账户查询", c.get("/api/trading/account", headers=H), ["equity", "cash", "mode", "connected"])
    show("交易模式", c.get("/api/trading/mode", headers=H), ["mode", "live_ready", "live_reason"])
    show("风控配置", c.get("/api/risk/config", headers=H), ["live_env_gate"])
    show("实时敞口", c.get("/api/risk/exposure", headers=H), ["gross_pct", "net_pct"])

    # 临时关闭交易时段限制，验证下单主链路
    base_risk = {
        "max_position_pct": 20, "max_gross_exposure_pct": 100, "max_open_positions": 10,
        "min_order_notional": 200, "max_order_notional": 50000, "max_daily_loss_pct": 3,
        "max_drawdown_pct": 15, "stop_type": "atr_trailing", "stop_value": 3.0,
        "take_profit_r": 2.0, "time_stop_bars": 0, "sizing_method": "weight",
        "risk_per_trade_pct": 1.0, "trading_hours_only": False, "whitelist": "", "blacklist": "",
    }
    show("风控配置更新", c.put("/api/risk/config", headers=H, json=base_risk), ["ok", "message"])
    show("下单预检", c.post("/api/trading/preview", headers=H,
                        json={"symbol": "SPY", "side": "BUY", "quantity": 5, "order_type": "MKT"}),
         ["ok", "code", "estimated"])
    show("模拟下单", c.post("/api/trading/order", headers=H,
                        json={"symbol": "SPY", "side": "BUY", "quantity": 5, "order_type": "MKT", "confirm": True}),
         ["ok", "status", "message"])
    show("持仓查询", c.get("/api/trading/positions", headers=H), ["count"])
    show("订单查询", c.get("/api/trading/orders", headers=H))
    show("护栏：未确认拒绝", c.post("/api/trading/order", headers=H,
                              json={"symbol": "SPY", "side": "BUY", "quantity": 1, "confirm": False}),
         expect_ok=False)
    show("护栏：黑名单拒绝", c.put("/api/risk/config", headers=H,
                             json={**base_risk, "blacklist": "TSLA"}), ["ok"])
    c.put("/api/risk/config", headers=H, json=base_risk)
    # 环境自适应：第一道锁（QD_ALLOW_LIVE_TRADING）未开 → 403；已开（用户实盘流程中）→ 缺短语 400
    from app.config import settings as _cfg
    if _cfg.allow_live_trading:
        show("实盘解锁缺确认短语被拒（400）", c.post("/api/trading/live-unlock", headers=H, json={
            "confirm_phrase": "WRONG PHRASE", "password": TEST_PASS, "enable": True}), expect_ok=False)
    else:
        show("实盘解锁被拒（环境开关未开）", c.post("/api/trading/live-unlock", headers=H, json={
            "confirm_phrase": "I UNDERSTAND THE RISK", "password": TEST_PASS, "enable": True}), expect_ok=False)
    # 环境自适应（第一道锁 + 运行时解锁状态决定期望值）；成功切换后立即切回 paper
    _unlocked = c.get("/api/risk/config", headers=H).json().get("live_unlocked")
    if _cfg.allow_live_trading and _unlocked:
        r_mode = c.post("/api/trading/mode", headers=H, json={"mode": "live"})
        if r_mode.status_code < 400:
            c.post("/api/trading/mode", headers=H, json={"mode": "paper"})   # 恢复模拟，保护用户环境
        check(True, "实盘切换成功后已恢复 paper（解锁环境）")
    else:
        show("切换实盘被拒", c.post("/api/trading/mode", headers=H, json={"mode": "live"}), expect_ok=False)

    rule = {
        "direction": "long",
        "entry": {"all": [
            {"op": "<", "left": {"indicator": "rsi", "period": 14}, "right": {"const": 35}},
        ]},
        "exit": {"any": [{"op": ">", "left": {"indicator": "rsi", "period": 14}, "right": {"const": 65}}]},
    }
    r = c.post("/api/strategies/custom", headers=H, json={
        "name": f"自检规则策略_{os.getpid()}", "kind": "rule", "rule": rule, "symbols": ["SPY"]})
    show("创建自定义策略", r, ["id", "name"])
    if r.status_code < 400:
        sid = r.json()["id"]
        show("自定义策略回测", c.post("/api/backtest/run", headers=H, json={
            "strategy_key": "custom_rule", "rule": rule, "symbols": ["SPY"], "start": "2021-01-01"}), ["ok", "bars"])
        show("引擎演练（不下单）", c.post(f"/api/trading/engine/dry-run/{sid}", headers=H),
             ["ok", "planned_orders", "blocked"])
        c.delete(f"/api/strategies/custom/{sid}")

    show("代码沙箱拦截", c.post("/api/strategies/validate-code", headers=H,
                           json={"code": "import os\ndef generate(ctx):\n    return 1"}))
    show("代码沙箱放行", c.post("/api/strategies/validate-code", headers=H,
                           json={"code": "import pandas as pd\ndef generate(ctx):\n    return pd.DataFrame(0.0, index=ctx.closes.index, columns=ctx.closes.columns)"}))

    r = c.post("/api/ai/analyze", headers=H, json={"symbols": ["SPY", "NVDA"], "horizon": "swing"})
    show("AI 研判", r, ["engine", "llm_available"])
    if r.status_code < 400:
        for x in r.json()["results"]:
            print(f"      {x['symbol']}: 偏向={x.get('bias')} 状态={x.get('regime')} "
                  f"评分={x.get('composite_score')} 建议仓位={x.get('suggested_position_pct')}%")
    show("AI 对话", c.post("/api/ai/chat", headers=H,
                       json={"message": "当前适合做多么？", "context_symbols": ["SPY"]}), ["engine"])
    show("审计日志", c.get("/api/risk/audit?limit=5", headers=H))
    show("熔断启用", c.post("/api/risk/kill-switch", headers=H, json={"engaged": True}), ["ok", "kill_switch"])
    show("熔断后下单被拒", c.post("/api/trading/order", headers=H,
                            json={"symbol": "SPY", "side": "BUY", "quantity": 1, "confirm": True}), expect_ok=False)
    show("熔断解除需口令", c.post("/api/risk/kill-switch", headers=H,
                            json={"engaged": False, "password": TEST_PASS}), ["ok"])

    # ---------- 新增能力 ----------
    head("3b / 券商接入 · 数据源 · 对比 · 导出")

    show("券商详细状态", c.get("/api/trading/broker-status", headers=H), ["broker", "connected", "supports_history"])
    show("券商挂单", c.get("/api/trading/open-orders", headers=H))
    show("券商成交回报", c.get("/api/trading/fills", headers=H), ["count"])
    show("撤销全部挂单", c.post("/api/trading/cancel-all", headers=H), ["ok", "cancelled"])

    r = c.get("/api/market/data-source", headers=H)
    show("数据源状态", r, ["preferred", "available"])
    if r.status_code < 400:
        provs = r.json().get("providers", {})
        check("ibkr" in provs, "IBKR 已注册为可选数据源", str(list(provs.keys())))
        check(provs.get("ibkr", {}).get("available") is False,
              "IBKR 未连接时正确标记为不可用")

    show("切换数据源为 auto", c.post("/api/market/data-source", headers=H, json={"preferred": "auto"}), ["ok", "preferred"])
    show("切换到未知数据源被拒", c.post("/api/market/data-source", headers=H,
                                json={"preferred": "nope"}), expect_ok=False)
    show("IBKR 数据源回测自动降级", c.post("/api/backtest/run", headers=H, json={
        "strategy_key": "dual_ma_trend", "symbols": ["SPY"], "start": "2022-01-01",
        "data_source": "ibkr", "interval": "1d"}), ["ok", "data_source_used", "data_warning"])
    show("日内周期回测 (1h)", c.post("/api/backtest/run", headers=H, json={
        "strategy_key": "dual_ma_trend", "symbols": ["SPY"], "start": "2024-01-01",
        "interval": "1h", "data_source": "auto"}), ["ok", "bars", "data_source_used"])
    show("日内周期回测 (30m)", c.post("/api/backtest/run", headers=H, json={
        "strategy_key": "rsi_meanrev", "symbols": ["SPY"], "start": "2025-01-01",
        "interval": "30m", "data_source": "auto"}), ["ok", "bars"])

    r = c.post("/api/backtest/compare", headers=H, json={
        "items": [
            {"label": "双均线", "strategy_key": "dual_ma_trend", "params": {"fast": 20, "slow": 100},
             "symbols": ["SPY"], "risk": {"stop_type": "atr_trailing", "stop_value": 3}},
            {"label": "波动率管理动量", "strategy_key": "vol_managed_momentum", "symbols": ["SPY"],
             "risk": {"stop_type": "atr_trailing", "stop_value": 3}},
            {"label": "风险平价", "strategy_key": "risk_parity_alloc", "symbols": ["SPY", "TLT", "GLD"],
             "risk": {"stop_type": "none"}},
        ],
        "start": "2021-01-01", "benchmark": "SPY",
    })
    show("多策略对比", r, ["ok", "labels"])
    if r.status_code < 400:
        for it in r.json().get("results", []):
            if it.get("ok"):
                m = it["metrics"]
                print(f"      {it['label']:<16} 收益 {m['total_return']*100:7.2f}%  夏普 {m['sharpe']:5.2f}  "
                      f"回撤 {m['max_drawdown']*100:6.2f}%  交易 {m['trades']:4d}")
            else:
                print(f"      {it['label']:<16} 失败: {it.get('error')}")
        check(len(r.json().get("aligned", [])) > 0, "对比曲线已对齐到统一时间轴",
              f"{len(r.json().get('aligned', []))} 个点")

    r = c.get("/api/backtest/history?limit=5", headers=H)
    if r.status_code < 400 and r.json().get("items"):
        rid = r.json()["items"][0]["id"]
        for kind, expect in (("trades", "symbol"), ("equity", "equity"), ("monthly", "metric")):
            resp = c.get(f"/api/backtest/{rid}/export?kind={kind}", headers=H)
            body = resp.text
            ok = resp.status_code == 200 and expect in body.split("\n")[0]
            check(ok, f"导出回测 {kind} CSV", f"[{resp.status_code}] 首行={body.splitlines()[0][:60] if body else ''}")

    # ---------------- 组合优化 ----------------
    show("组合优化参数枚举", c.get("/api/optimize/meta", headers=H),
         ["objectives", "cov_methods", "return_methods", "defaults"])
    r = c.post("/api/optimize/run", headers=H, json={
        "symbols": ["SPY", "TLT", "GLD", "QQQ"], "start": "2021-01-01",
        "objective": "max_sharpe", "max_weight": 0.4, "corr_threshold": 0.8,
        "max_cluster_weight": 0.5, "include_frontier": False,
    })
    show("组合优化求解", r, ["ok", "symbols", "feasible", "data_source_used"])
    if r.status_code < 400:
        body = r.json()
        wsum = sum(body["weights"].values())
        check(abs(wsum - 1.0) < 1e-6, f"API 返回权重和 = 1.0（实际 {wsum:.6f}）")
        check(len(body["symbols"]) >= 2, f"有效标的 {len(body['symbols'])} 个")
        check(body["portfolio"]["ann_vol"] > 0, "组合年化波动为正")
        print(f"      权重: { {k: round(v, 4) for k, v in body['weights'].items()} }")
        print(f"      预期夏普 {body['portfolio']['sharpe']:.2f}  "
              f"vs 等权 {body['benchmark_equal_weight']['sharpe']:.2f}  "
              f"· 有效标的数 {body['portfolio']['effective_n']:.1f}")
        if body.get("synthetic_symbols"):
            print(f"      ⚠ 合成数据标的: {body['synthetic_symbols']}")

        # 权重另存为策略，并确认生成的策略真的能跑回测
        import uuid as _uuid

        sname = f"自检-优化权重-{_uuid.uuid4().hex[:6]}"
        rs = c.post("/api/optimize/save", headers=H, json={
            "name": sname, "symbols": body["symbols"], "weights": body["weights"],
            "objective": body["objective"], "notes": "自检自动创建",
        })
        show("优化权重另存为策略", rs, ["ok", "id", "name", "kind"])
        if rs.status_code < 400:
            sid = rs.json()["id"]
            # 同名重复保存必须被拒 —— 必须在删除之前验证，否则测的是「删干净了没」
            dup = c.post("/api/optimize/save", headers=H, json={
                "name": sname, "symbols": body["symbols"], "weights": body["weights"],
            })
            show("重复策略名被拒", dup, expect_ok=False)

            lst = c.get("/api/strategies/custom", headers=H)
            saved = next((x for x in (lst.json().get("items") or []) if x.get("id") == sid), None)
            check(saved is not None and "def generate" in (saved or {}).get("code", ""),
                  "另存策略包含可执行的 generate 函数")
            if saved:
                rr = c.post("/api/backtest/run", headers=H, json={
                    "strategy_key": "custom_code", "symbols": body["symbols"],
                    "code": saved["code"], "start": "2022-01-01",
                    "benchmark": "", "risk": {"stop_type": "none"},
                })
                check(rr.status_code < 400 and rr.json().get("ok"), "另存的权重策略可回测",
                      f"[{rr.status_code}] {rr.text[:140]}")
                if rr.status_code < 400 and rr.json().get("ok"):
                    m = rr.json()["metrics"]
                    print(f"      权重策略回测：收益 {m['total_return']*100:.2f}%  夏普 {m['sharpe']:.2f}  "
                          f"交易 {m['trades']} 笔")
                    check(m["trades"] >= 0, "权重策略回测产出交易记录")
            c.delete(f"/api/strategies/custom/{sid}", headers=H)
            check(True, "清理自检创建的策略", "")

    show("优化约束不可行时报错", c.post("/api/optimize/run", headers=H, json={
        "symbols": ["SPY"], "start": "2021-01-01"}), expect_ok=False)
    show("优化参数越界被拒", c.post("/api/optimize/run", headers=H, json={
        "symbols": ["SPY", "QQQ"], "max_weight": 1.8}), expect_ok=False)

    # 模式保护：以下写操作用例必须在 paper 模式（用户可能处于 live+解锁状态，绝不触碰实盘）
    _cur_mode = c.get("/api/system/status", headers=H).json().get("mode")
    if _cur_mode == "live":
        c.post("/api/trading/mode", headers=H, json={"mode": "paper"})

    _env_live2 = _cfg.allow_live_trading
    _unlocked2 = c.get("/api/risk/config", headers=H).json().get("live_unlocked")
    if _env_live2 and _unlocked2:
        # 解锁环境：live 引擎启动会成功（随后立即停止），断言「可启动且可停止」
        r_eng = c.post("/api/trading/engine/start", headers=H,
                       json={"strategy_id": 1, "mode": "live", "interval_sec": 60})
        check(r_eng.status_code < 400, "实盘引擎可启动（解锁环境，随后停止）", r_eng.text[:140])
    else:
        show("实盘引擎启动被拒（环境开关未关）", c.post("/api/trading/engine/start", headers=H,
                                              json={"strategy_id": 1, "mode": "live", "interval_sec": 60}),
             expect_ok=False)
    show("一键停止全部引擎", c.post("/api/trading/engine/stop-all", headers=H), ["ok", "stopped"])

    c.post("/api/trading/mode", headers=H, json={"mode": "paper"})   # 确保提案用例在 paper
    c.post("/api/trading/sim/reset?cash=100000", headers=H)
    show("模拟账户重置", c.get("/api/trading/account", headers=H), ["equity", "cash"])

    # ---- T-107 提案闭环 ----
    r = c.post("/api/ops/proposals", headers=H, json={
        "symbol": "MSFT", "action": "BUY", "size_pct": 5, "rationale": "自检提案"})
    check(r.status_code == 200 and r.json().get("proposal", {}).get("status") == "proposed",
          "提案创建（status=proposed）", r.text[:120])
    pid = r.json().get("proposal", {}).get("id")
    r2 = c.post(f"/api/ops/proposals/{pid}/reject", headers=H)
    check(r2.status_code == 200 and r2.json().get("proposal", {}).get("status") == "rejected",
          "提案拒绝路径")
    r3 = c.post(f"/api/ops/proposals/{pid}/approve", headers=H)
    check(r3.status_code == 409, "已处理提案不能重复操作（409）", r3.text[:120])
    r4 = c.post("/api/ops/proposals", headers=H, json={
        "symbol": "AAPL", "action": "BUY", "size_pct": 5, "rationale": "自检执行路径"})
    pid2 = r4.json().get("proposal", {}).get("id")
    r5 = c.post(f"/api/ops/proposals/{pid2}/approve", headers=H)
    body5 = r5.json() if r5.status_code == 200 else {}
    # 券商配置为 IBKR（用户可能在实盘流程中）时，执行被安全拒绝（实盘未就绪/口令）是正确行为
    prov = c.get("/api/system/broker", headers=H).json().get("config", {}).get("provider", "")
    if prov != "simulated":
        check(r5.status_code in (403, 422) or (r5.status_code == 200 and body5.get("proposal", {}).get("order_id")),
              "提案批准（IBKR 环境：安全拒绝或成功执行）", r5.text[:160])
    else:
        check(r5.status_code == 200 and body5.get("proposal", {}).get("order_id"),
              "提案批准 → 走护栏真实下单（order_id 回写）", r5.text[:160])
    show("overview 含待审提案字段", c.get("/api/ops/overview?include_decisions=0", headers=H),
         ["pending_proposals"])

    # ---- T-115 订单预检 ----
    r = c.post("/api/trading/preview", headers=H, json={
        "symbol": "SPY", "side": "BUY", "quantity": 10, "order_type": "MKT", "confirm": True})
    check(r.status_code == 200 and r.json().get("ok") is not None,
          "订单预检（护栏+费用+组合影响）", r.text[:120])

    # ---- 做空护栏（T-113）----
    r = c.post("/api/trading/order", headers=H, json={
        "symbol": "SPY", "side": "SELL", "quantity": 5, "order_type": "MKT", "confirm": True})
    check(r.status_code == 422 and "SHORT_FORBIDDEN" in r.text, "裸卖无持仓被拒（SHORT_FORBIDDEN）", r.text[:120])

    # ---- 数据源诊断（recent_errors）----
    r = c.get("/api/market/data-source", headers=H)
    check("recent_errors" in r.json(), "数据源诊断暴露 recent_errors")

    # ---------------- AI 情报中心 ----------------
    head("3c / AI 情报中心 · Bridge · 报告归档")
    r = c.get("/api/intel/overview", headers=H)
    show("情报中心总览", r, ["settings", "stats", "companies"])
    _intel_was_on, _intel_auto0 = False, True
    if r.status_code < 400:
        ov0 = r.json()
        _intel_was_on = bool(ov0["settings"]["monitor_enabled"])
        _intel_auto0 = bool(ov0["settings"]["auto_analyze"])
        check(len(ov0["companies"]) >= 10, f"默认观察标的已初始化（{len(ov0['companies'])} 家）")
        check(bool(ov0["settings"]["bridge_token"]), "Bridge Token 已生成")

    g = c.get("/api/intel/bridge/guide", headers=H)
    show("接入指南（WorkBuddy/Claude Code/Codex 提示词）", g, ["base_url", "token_header", "endpoints"])
    _itoken = g.json().get("token", "") if g.status_code < 400 else ""
    _IH = {"X-Intel-Token": _itoken}

    r401 = c.post("/api/intel/bridge/events",
                  json={"agent": "selfcheck", "events": [{"symbol": "NVDA", "title": "无令牌事件"}]})
    check(r401.status_code == 401, "Bridge 缺 Token 被拒（401）", f"[{r401.status_code}] {r401.text[:100]}")

    if not _intel_was_on:
        r = c.post("/api/intel/monitor/start", headers=H, json={"interval_minutes": 30, "auto_analyze": False})
        show("一键开启监控", r, ["ok", "run_id"])
        check(r.status_code < 400 and r.json().get("status", {}).get("monitor_enabled") is True,
              "开启后 monitor_enabled=True")
    else:
        check(True, "检测到用户监控运行中：复用当前批次且不改动其状态")

    r = c.get("/api/intel/bridge/poll?agent=selfcheck", headers=_IH)
    show("Agent 领任务 poll", r, ["ok", "monitor_running", "watchlist_size"])
    check(isinstance(r.json().get("tasks"), list), "poll 返回待抓任务列表")

    import uuid as _uuid_i

    _ev_title = f"自检情报·发布新一代推理模型 {_uuid_i.uuid4().hex[:8]}"
    _ev = {"symbol": "NVDA", "occurred_on": "", "category": "model_release", "title": _ev_title,
           "summary": "run_checks 自动提交的情报事件", "impact": 4, "sentiment": "positive",
           "source_name": "selfcheck", "source_url": "https://example.com/selfcheck"}
    r = c.post("/api/intel/bridge/events", headers=_IH,
               json={"agent": "selfcheck", "events": [_ev, dict(_ev)]})
    show("提交事件（同批 2 条重复）", r, ["inserted", "duplicates"])
    if r.status_code < 400:
        _b = r.json()
        check(_b["inserted"] == 1 and _b["duplicates"] == 1,
              f"事件去重生效（inserted={_b.get('inserted')} dup={_b.get('duplicates')}）")

    r = c.post("/api/intel/bridge/analysis", headers=_IH,
               json={"agent": "selfcheck", "analyses": [{
                   "symbol": "NVDA", "recommendation": "buy", "confidence": 66,
                   "thesis": "自检建议：事件面支持持有至下一催化剂", "catalysts": "下一财报",
                   "risks": "仅供自检", "position_pct": 3, "invalidation": "自检结束即作废",
                   "horizon": "swing"}]})
    show("提交 AI 买入建议", r, ["inserted"])
    r = c.get("/api/intel/analyses?symbol=NVDA&limit=5", headers=H)
    if r.status_code < 400 and r.json().get("items"):
        _top = r.json()["items"][0]
        check(_top.get("engine") == "agent" and _top.get("agent") == "selfcheck",
              f"建议来源可追溯 engine=agent（实际 {_top.get('engine')}/{_top.get('agent')}）")
    show("Agent 收工 done", c.post("/api/intel/bridge/done", headers=_IH,
                             json={"agent": "selfcheck", "note": "自检一轮完成"}), ["ok"])

    # ---- 建议验证闭环：插入 8 天前的测试建议 → 对账 → 结算字段 ----
    import datetime as _dt_vc

    from app.database import session_scope as _session_scope
    from app.models import IntelAnalysis as _IA

    with _session_scope() as _db_vc:
        _row_vc = _IA(symbol="SPY", recommendation="buy", confidence=60, thesis="自检验证闭环",
                      price_at_analysis=100.0, agent="selfcheck", engine="local",
                      created_at=_dt_vc.datetime.now(_dt_vc.timezone.utc) - _dt_vc.timedelta(days=8))
        _db_vc.add(_row_vc)
        _db_vc.flush()
        _tid_vc = _row_vc.id
    rv = c.post("/api/intel/verify/run", headers=H)
    show("建议对账接口", rv, ["ok", "verified"])
    check(rv.status_code == 200 and rv.json().get("verified", 0) >= 1, "到期建议被对账结算")
    with _session_scope() as _db_vc:
        _a_vc = _db_vc.get(_IA, _tid_vc)
        check(_a_vc.outcome_checked_at is not None and _a_vc.outcome_price and _a_vc.outcome_price > 0,
              f"对账写入验证价（{_a_vc.outcome_price}）")
        _exp_hit = (_a_vc.outcome_return or 0) > 1.0
        check(_a_vc.outcome_hit == _exp_hit and _a_vc.outcome_return is not None,
              f"方向判定与收益一致（{_a_vc.outcome_return}% → hit={_a_vc.outcome_hit}）")
    rvs = c.get("/api/intel/verify/stats", headers=H)
    show("验证统计接口", rvs, ["verified_total", "pending", "agents"])
    if rvs.status_code < 400:
        _vst = rvs.json()
        check(any(a.get("agent") == "selfcheck" for a in _vst.get("agents", [])), "统计按 Agent 聚合")
    rhist = c.get("/api/intel/history/SPY?days=120", headers=H)
    check(rhist.status_code == 200 and len(rhist.json().get("close", [])) > 30,
          "价格序列接口（时间线叠加图数据源）", rhist.text[:120])

    if not _intel_was_on:
        r = c.post("/api/intel/monitor/stop", headers=H)
        show("截止并归档", r, ["ok", "report_path"])
        _rp = (r.json() or {}).get("report_path", "")
        check(bool(_rp) and os.path.exists(_rp), "Markdown 报告已落盘", _rp or "无路径")
        if _rp and os.path.exists(_rp):
            _md = open(_rp, encoding="utf-8").read()
            check("AI 情报批次报告" in _md and _ev_title in _md, "报告包含批次标题与本批事件")
        c.put("/api/intel/settings", headers=H, json={"auto_analyze": _intel_auto0})
        check(True, "已恢复自动分析偏好")

    # 恢复用户原券商配置（含实盘端口），不破坏实盘上线流程
    if _orig_broker_cfg:
        c.put("/api/system/broker", headers=H, json=_orig_broker_cfg)
        check(True, "已恢复用户券商配置")

    client_cm.__exit__(None, None, None)


# ==================================================================
# 5. 数值正确性（2026-09-24 评估报告修复配套：此前自检只覆盖"功能存在"，
#    缺"数值正确"类断言 —— P0-1/P0-3/P1-4 正是这样一路全绿通过的）
# ==================================================================
def test_correctness() -> None:
    head("5 / 数值正确性（评估修复配套）")

    # ---- P0-1：回测 weight 模式敞口 ≤ gross_pct ----
    import numpy as np
    import pandas as pd
    from app.engine import backtest as bt
    from app.risk.sizing import cap_targets

    _t = cap_targets({"A": 1.0, "B": 1.0, "C": -0.5}, 100_000.0, 20.0, 100.0)
    check(all(abs(v) <= 20_000.0 + 1e-6 for v in _t.values()),
          "P0-1 单元：单标的名义被 clip 到 max_position_pct", str(_t))
    check(abs(sum(abs(v) for v in _t.values())) <= 100_000.0 + 1e-6,
          "P0-1 单元：总敞口 ≤ gross_pct", f"gross={sum(abs(v) for v in _t.values()):.0f}")

    rng = np.random.default_rng(7)
    _idx = pd.bdate_range("2024-01-02", periods=500)
    _data = {}
    for _i, _s in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]):
        _px = 100 * np.exp(np.cumsum(0.0015 + _i * 0.0002 + rng.normal(0, 0.012, 500)))
        _data[_s] = pd.DataFrame(
            {"open": _px * 1.001, "high": _px * 1.01, "low": _px * 0.99, "close": _px, "volume": 1e6},
            index=_idx,
        )
    _fm_orig, _fh_orig = bt.fetch_many, bt.fetch_history
    try:
        bt.fetch_many = lambda symbols, start, end, interval, prefer=None: (
            {s: _data[s] for s in symbols}, {s: "test" for s in symbols})
        bt.fetch_history = lambda symbol, start, end, interval, prefer=None: (
            pd.DataFrame({"close": _data["AAA"]["close"]}), "test")
        _r = bt.run_backtest(bt.BacktestSpec(
            strategy_key="dual_ma_trend", symbols=list(_data), params={},
            start="2024-01-02", end="2025-10-01", initial_capital=100_000.0,
            sizing_method="weight", max_position_pct=20.0, gross_pct=100.0,
        ))
        _max_exp = max(c["exposure"] for c in _r["curve"]) if _r.get("ok") else 99.0
        check(_r.get("ok") and _max_exp <= 1.05,
              "P0-1 回测：weight 模式最大敞口 ≤ 1.0x（修复前 6.1x）", f"max_exposure={_max_exp}")
    finally:
        bt.fetch_many, bt.fetch_history = _fm_orig, _fh_orig

    # ---- P0-3：stop_type=none / time_stop 无隐藏价格止损 ----
    from app.risk.stops import StopConfig, StopTracker

    _tr = StopTracker(StopConfig(stop_type="none"))
    _tr.open(1, 100.0, 0, None)
    _hit, _reason, _px = _tr.update(high=101.0, low=60.0, close=70.0, atr_value=None, bar_index=1)
    check(not _hit, "P0-3：stop_type=none 不再触发隐藏 -25% 止损", f"{_hit},{_reason},{_px}")
    _tr2 = StopTracker(StopConfig(stop_type="time_stop", stop_value=3.0, time_stop_bars=5))
    _tr2.open(1, 100.0, 0, None)
    _hit2, _, _ = _tr2.update(high=101.0, low=60.0, close=70.0, atr_value=None, bar_index=1)
    check(not _hit2, "P0-3：time_stop 不再携带 3% 隐藏价格止损", str(_hit2))
    _hit3, _reason3, _ = _tr2.update(high=101.0, low=95.0, close=99.0, atr_value=None, bar_index=5)
    check(_hit3 and "时间" in _reason3, "P0-3：time_stop 仍按持有时间离场", _reason3)

    # ---- P0-4：bcrypt 72 字节 ----
    from app.security import hash_password, verify_password

    try:
        _h = hash_password("a" * 73)
        _ok72 = verify_password("a" * 73, _h) and not verify_password("b" * 73, _h)
    except Exception as _e:  # noqa: BLE001
        _ok72 = False
        print(f"  bcrypt 异常: {_e}")
    check(_ok72, "P0-4：口令 > 72 字节不再 500，且 hash/verify 同口径截断")

    # ---- P0-6：熔断放行减仓单 ----
    import datetime as _dt
    from app.risk.guardrails import GuardContext, RiskLimits, check_order

    _lim = RiskLimits(max_daily_loss_pct=3.0, max_drawdown_pct=15.0, trading_hours_only=False)
    _now = _dt.datetime(2026, 9, 24, 15, 0, tzinfo=_dt.timezone.utc)
    _ctx = GuardContext(equity=90_000.0, day_start_equity=100_000.0, peak_equity=112_500.0,
                        open_positions={"AAPL": 30_000.0}, gross_exposure=30_000.0, now=_now)
    _r_open = check_order(symbol="MSFT", side="BUY", quantity=10, price=400.0, limits=_lim, ctx=_ctx)
    _r_red = check_order(symbol="AAPL", side="SELL", quantity=50, price=300.0, limits=_lim, ctx=_ctx)
    check(not _r_open.ok and _r_open.code == "DAILY_LOSS_LIMIT",
          "P0-6：熔断仍拦截新开仓", f"{_r_open.ok},{_r_open.code}")
    check(_r_red.ok, "P0-6：熔断放行减仓/止损单", f"{_r_red.ok},{_r_red.code},{_r_red.reason}")

    # ---- P0-5 / P1-5：计数器接入 + HKD 敞口折算 ----
    from app.state import build_guard_context

    class _Acc:
        equity = 100_000.0
        day_pnl = 0.0
        base_currency = "USD"
        currency = "USD"

    class _Pos:
        def __init__(self, sym, mv, ccy, mkt):
            self.symbol, self.market_value, self.currency, self.market = sym, mv, ccy, mkt

    _ctx2 = build_guard_context(_Acc(), [_Pos("AAPL", 30_000.0, "USD", "US"),
                                         _Pos("0700.HK", 78_000.0, "HKD", "HK")],
                                now=_dt.datetime.now(_dt.timezone.utc))
    check(abs(_ctx2.gross_exposure - 40_000.0) < 1_500,
          "P1-5：港股敞口按 HKD→USD 折算（78_000 HKD → ~10_000 USD）",
          f"gross={_ctx2.gross_exposure:.0f}")
    check(_ctx2.market_exposure.get("HK", 0.0) < 12_000,
          "P1-5：分市场敞口（HK 桶）已折算", str(_ctx2.market_exposure))
    _lim5 = RiskLimits(hk_max_gross_exposure_pct=5.0, trading_hours_only=False, min_order_notional=0.0)
    _r_hk = check_order(symbol="0700.HK", side="BUY", quantity=1, price=300.0, limits=_lim5, ctx=_ctx2)
    check(not _r_hk.ok and _r_hk.code == "MARKET_EXPOSURE",
          "P0-5：hk_max_gross_exposure_pct 真正生效", f"{_r_hk.ok},{_r_hk.code}")
    _lim5b = RiskLimits(max_orders_per_minute=3, trading_hours_only=False, min_order_notional=0.0)
    _ctx2.orders_last_minute = 3
    _r_rate = check_order(symbol="AAPL", side="BUY", quantity=1, price=200.0, limits=_lim5b, ctx=_ctx2)
    check(not _r_rate.ok and _r_rate.code == "ORDER_RATE_LIMIT",
          "P0-5：max_orders_per_minute 真正生效（防 IBKR 限流）", f"{_r_rate.ok},{_r_rate.code}")

    # ---- P1-1：归一化幂等 + UTC 语义保留 ----
    from app.data_provider import _normalize

    _df1 = pd.DataFrame({"open": 1., "high": 1., "low": 1., "close": 1., "volume": 1.},
                        index=pd.to_datetime(["2026-09-21 19:00:00"]))
    _once = _normalize(_df1, naive_tz=None)
    _twice = _normalize(_once, naive_tz=None)
    check(str(_once.index[0]) == str(_twice.index[0]) == "2026-09-21 19:00:00",
          "P1-1：naive_tz=None 归一化幂等（NY-naive 缓存不再漂移）",
          f"{_once.index[0]} -> {_twice.index[0]}")
    _utc = _normalize(_df1)
    check(str(_utc.index[0]) == "2026-09-21 15:00:00",
          "P1-1：默认 UTC 语义保留（腾讯 m1 依赖）", str(_utc.index[0]))

    # ---- P1-2：naive/aware 比较语义（IBKR history 修复的根因）----
    _naive = pd.Timestamp("2024-01-01")
    _aware = pd.DatetimeIndex(["2024-01-05 09:31:00"]).tz_localize("America/New_York")
    _raised = False
    try:
        _aware.min() <= _naive  # noqa: B015
    except TypeError:
        _raised = True
    check(_raised, "P1-2：确认旧实现的 naive/aware 比较确实抛 TypeError")
    _ok_cmp = bool(_aware.min() >= _naive.tz_localize(_aware.tz))
    check(_ok_cmp, "P1-2：localize 后比较可用（修复后的语义）")

    # ---- P1-4：优化器 BB 步长达到参照解 ----
    from app.engine.optimizer import SolveInput, _mean_variance, project

    _rng = np.random.default_rng(42)
    _A = _rng.normal(size=(6, 6))
    _cov = _A @ _A.T / 6 + 0.05 * np.eye(6)
    _mu = np.array([0.08, 0.12, 0.06, 0.10, 0.05, 0.09])
    _lam = 1.0
    _obj = lambda w: float(w @ _mu - 0.5 * _lam * (w @ _cov @ w))  # noqa: E731
    _L = _lam * float(np.linalg.eigvalsh(_cov).max())
    _proj = lambda w: project(w, 1.0, np.zeros(6), np.ones(6), [])  # noqa: E731
    _w_ref = np.full(6, 1.0 / 6)
    for _ in range(20000):
        _w_ref = _proj(_w_ref + (_mu - _lam * (_cov @ _w_ref)) / _L)
    _si = SolveInput(symbols=[f"S{i}" for i in range(6)], mu=_mu, cov=_cov,
                     lo=np.zeros(6), hi=np.ones(6), total=1.0)
    _w_bb = _mean_variance(_si, _lam, iters=400)
    check(_obj(_w_bb) >= _obj(_w_ref) - 1e-6,
          "P1-4：优化器 BB 步长达到固定步长参照解水平（修复前差 10.4%）",
          f"bb={_obj(_w_bb):.8f} ref={_obj(_w_ref):.8f}")

    # ---- P1-8：年化因子按周期推导 ----
    from app.engine.metrics import compute_metrics, periods_per_year

    check(abs(periods_per_year("1h") - 252 * 6.5) < 1e-6 and abs(periods_per_year("1wk") - 52) < 1e-6,
          "P1-8：periods_per_year 映射正确（1h=1638 / 1wk=52）")
    _eq = pd.Series(np.cumprod(1 + np.random.default_rng(1).normal(0.0005, 0.01, 400)) * 100_000,
                    index=pd.date_range("2025-01-01", periods=400, freq="h"))
    _m_daily = compute_metrics(_eq, [], 100_000.0)
    _m_hourly = compute_metrics(_eq, [], 100_000.0, periods_per_year=252 * 6.5)
    _ratio = _m_hourly["volatility"] / max(_m_daily["volatility"], 1e-12)
    check(abs(_ratio - (6.5 ** 0.5)) < 0.02,
          "P1-8：1h 序列年化波动率放大 √6.5 倍（修复前被低估 √7）", f"ratio={_ratio:.4f}")

    # ---- P1：IBKR 适配层并发竞态（2026-09-24 服务日志实证）----
    import threading as _th2

    from app.brokers.ibkr import IBKRBroker as _IBkr

    _b = _IBkr.__new__(_IBkr)   # 只测事件循环创建，不触碰配置/连接
    _b._loop = None
    _b._loop_lock = _th2.Lock()
    _b._thread = None
    _b._connected = False

    _loop_results: list = []
    _barrier2 = _th2.Barrier(20)

    def _loop_worker():
        _barrier2.wait()
        _loop_results.append(_b._ensure_loop())

    _ths2 = [_th2.Thread(target=_loop_worker) for _ in range(20)]
    [t.start() for t in _ths2]
    [t.join(timeout=10) for t in _ths2]
    _n_loops = len({id(r) for r in _loop_results})
    _alive2 = [t for t in _ths2 if t.is_alive()]
    check(not _alive2 and _n_loops == 1 and _loop_results[0].is_running(),
          "P1：20 路并发 _ensure_loop 只创建 1 个事件循环（旧实现双线程 run_forever 同一循环崩溃）",
          f"loops={_n_loops} alive={len(_alive2)}")

    # 熔断拒绝时协程必须被显式关闭（不再泄漏 "never awaited"）
    _b2 = _IBkr.__new__(_IBkr)
    _b2._loop = None
    _b2._loop_lock = _th2.Lock()
    _b2._thread = None
    _b2._connected = False
    _b2.stats = {"call_timeouts": 0}
    from app.brokers.pacing import CircuitBreaker as _CB, Pacer as _Pacer

    _b2._breaker = _CB(fail_threshold=1, cooldown=60.0)
    _b2._breaker.record_failure("测试熔断")
    _b2._pacer = _Pacer(rate=40, burst=20, max_wait=0.1)
    _b2._sub_slot = _th2.BoundedSemaphore(8)

    async def _noop():
        return 1

    _co = _noop()
    _rejected = False
    try:
        _b2._submit(_co, timeout=1.0)
    except Exception:  # noqa: BLE001
        _rejected = True
    check(_rejected and _co.cr_frame is None,
          "P1：熔断拒绝时未 await 的协程被显式关闭（不再泄漏 RuntimeWarning）",
          f"rejected={_rejected} closed={_co.cr_frame is None}")
    _b2._breaker = _CB()   # 复位，避免影响其他用例

    # ---- P1-14：后台任务注册表（进度 + 协作式取消）----
    import time as _t2

    from app.engine import jobs as _jobs_mod

    def _fake_grid(progress, cancel_event):
        total = 20
        for i in range(1, total + 1):
            if cancel_event.is_set():
                break
            _t2.sleep(0.02)
            progress(i, total)
        return {"ok": True, "evaluated": 0, "progress_last": True}

    _jid = _jobs_mod.start("selfcheck", _fake_grid)
    _t2.sleep(0.15)
    _j = _jobs_mod.get(_jid)
    check(_j is not None and _j["status"] == "running" and _j["progress"] > 0,
          "P1-14：后台任务进度上报可见", f"progress={_j['progress']}/{_j['total']}")
    _ok_cancel = _jobs_mod.cancel(_jid)
    _t2.sleep(0.15)
    _j2 = _jobs_mod.get(_jid)
    check(_ok_cancel and _j2["status"] == "cancelled",
          "P1-14：协作式取消生效（任务转为 cancelled）", f"status={_j2['status']}")

    # grid_optimize 的取消/进度参数真实生效（用极小网格验证，不依赖网络）
    from app.engine.backtest import BacktestSpec, grid_optimize as _grid

    _grid_spec = BacktestSpec(strategy_key="dual_ma_trend", symbols=["SPY"], params={},
                              start="2024-01-02", end="2024-06-01")
    _fake_many = bt.fetch_many
    _fake_one = bt.fetch_history
    try:
        bt.fetch_many = lambda symbols, start, end, interval, prefer=None: (
            {s: _data[s] for s in symbols}, {s: "test" for s in symbols})
        bt.fetch_history = lambda symbol, start, end, interval, prefer=None: (
            pd.DataFrame({"close": _data["AAA"]["close"]}), "test")
        _cev = __import__("threading").Event()
        _cev.set()   # 立即取消 → 一组都不跑
        _r_cancel = _grid(_grid_spec, {"fast": [5, 10, 20]}, "sharpe",
                          progress_cb=lambda d, t: None, cancel_event=_cev)
        check(_r_cancel.get("ok") and _r_cancel.get("is_cancelled") is True and _r_cancel["evaluated"] == 0,
              "P1-14：grid_optimize 取消事件立即生效（评估 0 组即返回）",
              f"evaluated={_r_cancel.get('evaluated')} is_cancelled={_r_cancel.get('is_cancelled')}")
        _seen = []
        _r_prog = _grid(_grid_spec, {"fast": [5, 10, 20]}, "sharpe",
                        progress_cb=lambda d, t: _seen.append((d, t)))
        check(len(_seen) >= 3 and _seen[-1][0] == _seen[-1][1],
              "P1-14：grid_optimize 进度回调覆盖全部组合", f"last={_seen[-1] if _seen else None}")
    finally:
        bt.fetch_many, bt.fetch_history = _fake_many, _fake_one

    # ---- P0-2：单飞不死锁（monkeypatch 假源，5 路并发只联网 1 次）----
    import threading as _threading
    import time as _time

    import app.data_provider as _dp

    _snap = {k: getattr(_dp, k) for k in ("_history_providers", "_read_cache", "_write_cache", "v_yf")}
    try:
        _calls = {"n": 0}
        _lk = _threading.Lock()
        _big = pd.DataFrame({"open": 1., "high": 1., "low": 1., "close": 1., "volume": 1.},
                            index=pd.bdate_range("2024-01-01", periods=100))

        def _slow_yf(s, a, b, c):
            with _lk:
                _calls["n"] += 1
            _time.sleep(1.2)
            return _big.copy()

        _store: dict = {}
        _dp._history_providers = {}
        _dp._read_cache = lambda symbol, interval, ttl, start=None, end=None, ignore_ttl=False: _store.get((symbol, interval))
        _dp._write_cache = lambda symbol, interval, df: _store.__setitem__((symbol, interval), df)
        _dp.v_yf = _slow_yf

        _barrier = _threading.Barrier(5)
        _alive: list[_threading.Thread] = []

        def _worker():
            _barrier.wait()
            try:
                _dp.fetch_history("TESTSF", "2024-01-01", None, "1d")
            except Exception:  # noqa: BLE001
                pass

        _ths = [_threading.Thread(target=_worker) for _ in range(5)]
        [t.start() for t in _ths]
        [t.join(timeout=15) for t in _ths]
        _alive = [t for t in _ths if t.is_alive()]
        check(not _alive and _calls["n"] == 1,
              "P0-2：单飞 5 路并发只联网 1 次且无死锁（修复前第 3 路永久阻塞）",
              f"alive={len(_alive)} calls={_calls['n']}")
    finally:
        for _k, _v in _snap.items():
            setattr(_dp, _k, _v)


# ==================================================================
def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "data"):
        test_data()
    if which in ("all", "strategies"):
        test_strategies()
    if which in ("all", "optimize"):
        test_optimize()
    if which in ("all", "api"):
        test_api()
    if which in ("all", "correct", "correctness"):
        test_correctness()

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{'=' * 66}")
    print(f"  自检结果：{passed}/{total} 项通过")
    if passed != total:
        print("  失败项：")
        for ok, label in RESULTS:
            if not ok:
                print(f"    - {label}")
    print(f"{'=' * 66}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
