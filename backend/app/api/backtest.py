"""回测与参数寻优接口。"""
from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..engine import BacktestSpec, grid_optimize, run_backtest
from ..engine.metrics import METRIC_LABELS
from ..models import BacktestRun
from ..risk.stops import STOP_TYPES, StopConfig
from ..schemas import BacktestRequest, CompareItem, CompareRequest, FactorICRequest, OptimizeRequest
from .deps import CurrentUser, DbSession

router = APIRouter(prefix="/backtest", tags=["回测"])


def _build_spec(payload: BacktestRequest) -> BacktestSpec:
    risk = payload.risk or {}
    stop = StopConfig(
        stop_type=str(risk.get("stop_type", "none")),
        stop_value=float(risk.get("stop_value", 3.0) or 3.0),
        atr_period=int(risk.get("atr_period", 14) or 14),
        take_profit_r=float(risk.get("take_profit_r", 0.0) or 0.0),
        time_stop_bars=int(risk.get("time_stop_bars", 0) or 0),
        breakeven_at_r=float(risk.get("breakeven_at_r", 0.0) or 0.0),
        trail_start_r=float(risk.get("trail_start_r", 0.0) or 0.0),
        min_stop_pct=float(risk.get("min_stop_pct", 0.0) or 0.0),
        max_stop_pct=float(risk.get("max_stop_pct", 0.25) or 0.25),
    )
    if stop.stop_type not in STOP_TYPES:
        stop.stop_type = "none"
    return BacktestSpec(
        strategy_key=payload.strategy_key,
        symbols=payload.symbols,
        params=payload.params or {},
        rule=payload.rule,
        code=payload.code or "",
        start=payload.start,
        end=payload.end,
        interval=payload.interval,
        initial_capital=payload.initial_capital,
        commission_bps=payload.commission_bps,
        slippage_bps=payload.slippage_bps,
        benchmark=payload.benchmark,
        stop=stop,
        sizing_method=str(risk.get("sizing_method", "weight")),
        risk_per_trade_pct=float(risk.get("risk_per_trade_pct", 1.0) or 1.0),
        max_position_pct=float(risk.get("max_position_pct", 20.0) or 20.0),
        gross_pct=float(risk.get("gross_pct", 100.0) or 100.0),
        data_source=payload.data_source or "auto",
    )


@router.get("/meta")
def meta(user: CurrentUser = None) -> dict:  # noqa: ARG001
    return {
        "metrics": METRIC_LABELS,
        "stop_types": [
            {"key": "none", "label": "不启用止损", "desc": "仅靠策略信号离场"},
            {"key": "fixed_pct", "label": "固定百分比止损", "desc": "自成本价固定百分比，简单直接"},
            {"key": "pct_trailing", "label": "百分比移动止损", "desc": "跟随最高价回撤百分比离场"},
            {"key": "atr_fixed", "label": "ATR 固定止损", "desc": "以 N 倍 ATR 为距离，随波动自适应"},
            {"key": "atr_trailing", "label": "ATR 移动止损", "desc": "最高价 − N×ATR，趋势策略标配"},
            {"key": "chandelier", "label": "吊灯止损", "desc": "取更宽的 ATR 距离，避免过早离场"},
            {"key": "breakeven", "label": "保本止损", "desc": "浮盈达 R 后把止损移到成本价"},
            {"key": "time_stop", "label": "时间止损", "desc": "持满 N 根 bar 仍无表现即离场"},
            {"key": "volatility", "label": "波动率自适应止损", "desc": "ATR 放大时同步放宽，防止被噪声扫出"},
        ],
        "sizing_methods": [
            {"key": "weight", "label": "策略权重直用（回测推荐）", "desc": "直接把目标权重当作权益占比"},
            {"key": "fixed_fraction", "label": "固定比例", "desc": "每笔按权益固定百分比建仓"},
            {"key": "risk_parity_vol", "label": "波动率平价", "desc": "按波动率倒数分配，低波动多配"},
            {"key": "atr_risk", "label": "固定风险(ATR)", "desc": "单笔最大亏损锁定为权益的 N%"},
            {"key": "kelly_capped", "label": "凯利公式(封顶)", "desc": "按胜率与盈亏比推算最优仓位"},
            {"key": "equal_weight", "label": "等权分配", "desc": "所有标的均分仓位"},
        ],
        "objectives": [
            {"key": "sharpe", "label": "夏普比率"}, {"key": "sortino", "label": "索提诺比率"},
            {"key": "calmar", "label": "卡玛比率"}, {"key": "return", "label": "累计收益"},
            {"key": "profit_factor", "label": "盈亏比"},
        ],
    }


@router.post("/run")
async def run(payload: BacktestRequest, user: CurrentUser, db: DbSession) -> dict:
    spec = _build_spec(payload)
    result = await run_in_threadpool(run_backtest, spec)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "回测失败"))

    label = payload.label or f"{result.get('strategy_name', payload.strategy_key)} · {','.join(payload.symbols[:3])}"
    row = BacktestRun(
        label=label, strategy_key=payload.strategy_key,
        strategy_name=result.get("strategy_name", ""),
        params_json=json.dumps(payload.params, ensure_ascii=False),
        risk_json=json.dumps(payload.risk, ensure_ascii=False),
        symbols_json=json.dumps(payload.symbols),
        start_date=payload.start, end_date=payload.end or dt.date.today().isoformat(),
        initial_capital=payload.initial_capital,
        benchmark=payload.benchmark or "SPY",
        commission_bps=float(payload.commission_bps or 0.0),
        slippage_bps=float(payload.slippage_bps or 0.0),
        interval=payload.interval or "1d",
        data_source=payload.data_source or "auto",
        metrics_json=json.dumps(result["metrics"], ensure_ascii=False),
        equity_json=json.dumps(result["curve"][:: max(1, len(result["curve"]) // 400)]),
        trades_json=json.dumps(result["trades"][:300], ensure_ascii=False),
    )
    def _persist_run() -> int:
        # P0-2：含 commit，必须在工作线程执行（否则阻塞事件循环）
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)

    run_id = await run_in_threadpool(_persist_run)

    result["run_id"] = run_id
    result["label"] = label
    await run_in_threadpool(
        appstate.log, "backtest_run", "INFO",
        f"回测 {label} 收益 {result['metrics']['total_return']*100:.2f}% "
        f"夏普 {result['metrics']['sharpe']:.2f}", user.username,
    )
    return result


@router.post("/optimize")
async def optimize(payload: OptimizeRequest, user: CurrentUser) -> dict:
    spec = BacktestSpec(
        strategy_key=payload.strategy_key,
        symbols=payload.symbols,
        params={},
        start=payload.start, end=payload.end, interval=payload.interval,
        initial_capital=payload.initial_capital,
        data_source=payload.data_source or "auto",
    )
    res = await run_in_threadpool(
        grid_optimize, spec, payload.param_grid, payload.objective, payload.max_combos
    )
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "寻优失败"))
    await run_in_threadpool(
        appstate.log, "backtest_optimize", "INFO",
        f"参数寻优 {payload.strategy_key} 评估 {res['evaluated']} 组，目标 {payload.objective}",
        user.username,
    )
    return res


# ==================================================================
# 后台任务（P1-14：网格寻优改为可查询进度 + 可取消）
# ==================================================================
@router.post("/optimize-async")
async def optimize_async(payload: OptimizeRequest, user: CurrentUser) -> dict:
    """启动网格寻优后台任务，立即返回 job_id。

    用 GET /backtest/job/{job_id} 轮询进度（progress/total），取消用
    POST /backtest/job/{job_id}/cancel。旧同步端点 /optimize 保持兼容。
    """
    from ..engine import jobs

    spec = BacktestSpec(
        strategy_key=payload.strategy_key,
        symbols=payload.symbols,
        params={},
        start=payload.start, end=payload.end, interval=payload.interval,
        initial_capital=payload.initial_capital,
        data_source=payload.data_source or "auto",
    )

    def _fn(progress, cancel_event):  # noqa: ANN001
        return grid_optimize(
            spec, payload.param_grid, payload.objective, payload.max_combos,
            progress_cb=progress, cancel_event=cancel_event,
        )

    job_id = jobs.start("optimize", _fn)
    await run_in_threadpool(
        appstate.log, "backtest_optimize_async", "INFO",
        f"后台寻优已启动 {payload.strategy_key}（job {job_id}，≤{payload.max_combos} 组）",
        user.username,
    )
    return {"ok": True, "job_id": job_id}


@router.get("/job/{job_id}")
def get_job(job_id: str, user: CurrentUser) -> dict:  # noqa: ARG001
    """查询后台任务状态：running / done / error / cancelled + progress/total。"""
    from ..engine import jobs

    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"任务 {job_id} 不存在或已过期")
    return {"ok": True, **job}


@router.post("/job/{job_id}/cancel")
def cancel_job(job_id: str, user: CurrentUser) -> dict:
    """协作式取消：当前组合评估完成后立即停止，已评估结果保留可查。"""
    from ..engine import jobs

    if not jobs.cancel(job_id):
        raise HTTPException(404, f"任务 {job_id} 不存在或已结束")
    appstate.log("backtest_job_cancel", "INFO", f"已请求取消任务 {job_id}", actor=user.username)
    return {"ok": True, "job_id": job_id, "message": "已请求取消，当前组合评估完成后停止"}


# ==================================================================
# 多策略对比
# ==================================================================
@router.post("/compare")
async def compare(payload: CompareRequest, user: CurrentUser) -> dict:
    """并行回测多个策略，返回对齐后的净值曲线与指标对照表。"""
    from ..engine.backtest import build_strategy  # noqa: F401

    def _one(item: CompareItem) -> dict:
        risk = item.risk or {}
        stop = StopConfig(
            stop_type=str(risk.get("stop_type", "none")),
            stop_value=float(risk.get("stop_value", 3.0) or 3.0),
            take_profit_r=float(risk.get("take_profit_r", 0.0) or 0.0),
            time_stop_bars=int(risk.get("time_stop_bars", 0) or 0),
        )
        if stop.stop_type not in STOP_TYPES:
            stop.stop_type = "none"
        spec = BacktestSpec(
            strategy_key=item.strategy_key,
            symbols=item.symbols,
            params=item.params or {},
            rule=item.rule,
            code=item.code or "",
            start=payload.start,
            end=payload.end,
            interval=payload.interval,
            initial_capital=payload.initial_capital,
            commission_bps=payload.commission_bps,
            slippage_bps=payload.slippage_bps,
            benchmark=payload.benchmark,
            stop=stop,
            sizing_method=str(risk.get("sizing_method", "weight")),
            risk_per_trade_pct=float(risk.get("risk_per_trade_pct", 1.0) or 1.0),
            max_position_pct=float(risk.get("max_position_pct", 20.0) or 20.0),
            data_source=payload.data_source or "auto",
        )
        label = item.label or f"{item.strategy_key} · {','.join(item.symbols[:2])}"
        try:
            r = run_backtest(spec)
        except Exception as exc:  # noqa: BLE001
            return {"label": label, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        if not r.get("ok"):
            return {"label": label, "ok": False, "error": r.get("error", "失败")}
        return {
            "label": label,
            "ok": True,
            "strategy_name": r["strategy_name"],
            "metrics": r["metrics"],
            "curve": r["curve"],
            "monthly": r["monthly"],
            "bars": r["bars"],
            "date_range": r["date_range"],
        }

    results = await run_in_threadpool(lambda: [_one(it) for it in payload.items])

    # 对齐所有曲线到统一日期轴，便于前端叠加绘图
    ok_items = [r for r in results if r.get("ok")]
    aligned: list[dict] = []
    if ok_items:
        dates: list[str] = []
        seen: set[str] = set()
        for r in ok_items:
            for p in r["curve"]:
                d = p["date"]
                if d not in seen:
                    seen.add(d)
                    dates.append(d)
        dates.sort()
        series: dict[str, dict[str, float | None]] = {}
        for r in ok_items:
            map_ = {p["date"]: p["equity"] for p in r["curve"]}
            base = next((v for v in map_.values() if v), None)
            series[r["label"]] = {
                d: (round(map_[d] / base * payload.initial_capital, 2) if d in map_ and base else None)
                for d in dates
            }
        step = max(1, len(dates) // 1200)
        aligned = [
            {"date": d, **{k: v[d] for k, v in series.items()}}
            for d in dates[::step]
        ]

    await run_in_threadpool(appstate.log, "backtest_compare", "INFO",
                            f"多策略对比 {len(payload.items)} 个策略，成功 {len(ok_items)} 个",
                            user.username)
    return {"ok": True, "results": results, "aligned": aligned, "labels": [r["label"] for r in ok_items]}


# ==================================================================
# 因子 IC 诊断（多因子策略的因子质量评估，纯离线研究工具）
# ==================================================================
@router.post("/factor-ic")
async def factor_ic(payload: FactorICRequest, user: CurrentUser) -> dict:
    """各启用因子与未来 N 日收益的横截面 Spearman 相关（IC）统计。

    注意：IC 分析天然使用未来收益做对账，**只用于评估因子质量**，
    不进入任何交易信号路径（与回测的无未来函数铁律互不冲突）。
    """
    from ..data_provider import fetch_many
    from ..engine.factor_analysis import factor_ic_report
    from ..strategies import SignalContext, create_strategy

    try:
        strategy = create_strategy(payload.strategy_key, payload.params or {})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"无法创建策略 {payload.strategy_key}：{exc}") from exc
    if not hasattr(strategy, "_active_factors"):
        raise HTTPException(400, "该策略不提供因子诊断（仅多因子打分策略支持）")

    end = payload.end or dt.date.today().isoformat()

    def _run() -> dict:
        data, _sources = fetch_many(payload.symbols, payload.start, end, payload.interval)
        symbols = [s for s in payload.symbols if s in data and len(data[s])]
        if len(symbols) < payload.min_names:
            raise ValueError(f"有效标的数据不足（{len(symbols)} < {payload.min_names}），请检查区间与数据源")
        ctx = SignalContext(data=data, symbols=symbols)
        return factor_ic_report(strategy, ctx, horizon=payload.horizon, min_names=payload.min_names)

    try:
        res = await run_in_threadpool(_run)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"因子诊断失败：{type(exc).__name__}: {exc}"[:200]) from exc
    await run_in_threadpool(
        appstate.log, "backtest_factor_ic", "INFO",
        f"因子诊断 {payload.strategy_key} horizon={payload.horizon} 标的 {len(payload.symbols)}",
        user.username,
    )
    return res


# ==================================================================
# 导出
# ==================================================================
@router.get("/{rid}/export")
def export_run(rid: int, db: DbSession, user: CurrentUser, kind: str = "trades") -> Response:  # noqa: ARG001
    """把回测结果导出为 CSV：kind = trades | equity | monthly"""
    r = db.get(BacktestRun, rid)
    if not r:
        raise HTTPException(404, "回测记录不存在")

    def _j(s: str, d):  # noqa: ANN001
        try:
            return json.loads(s) if s else d
        except json.JSONDecodeError:
            return d

    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (r.label or f"run{rid}"))[:60]
    if kind == "equity":
        rows = _j(r.equity_json, [])
        cols = ["date", "equity", "benchmark", "drawdown", "exposure"]
        header = "date,equity,benchmark,drawdown,exposure"
    elif kind == "monthly":
        metrics = _j(r.metrics_json, {})
        rows = [{"metric": k, "value": v} for k, v in metrics.items()]
        cols = ["metric", "value"]
        header = "metric,value"
    else:
        rows = _j(r.trades_json, [])
        cols = ["symbol", "side", "entry_time", "entry_price", "exit_time", "exit_price",
                "qty", "pnl", "return_pct", "bars_held", "exit_reason"]
        header = ",".join(cols)

    import csv
    import io as _io
    from urllib.parse import quote

    def _csv_safe(v: object) -> object:
        """P2：CSV 公式注入防护 —— 以 =/+/-/@ 开头的文本前置单引号，
        防止 Excel/LibreOffice 打开导出文件时把单元格当公式执行。"""
        if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
            return "'" + v
        return v

    buf = _io.StringIO()
    buf.write(header + "\n")
    w = csv.writer(buf, lineterminator="\n")
    for row in rows:
        w.writerow([_csv_safe(row.get(c, "")) for c in cols])

    # HTTP 头只能是 latin-1：ASCII 回退名 + RFC 5987 的 UTF-8 名
    fname = f"quantdesk_{safe}_{kind}.csv"
    ascii_name = f"quantdesk_run{rid}_{kind}.csv"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(fname, safe='')}"
    )
    return Response(
        content="\ufeff" + buf.getvalue(),      # BOM 让 Excel 正确识别中文
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.get("/history")
def history(db: DbSession, user: CurrentUser, limit: int = 50) -> dict:  # noqa: ARG001
    rows = db.execute(
        select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(min(limit, 200))
    ).scalars().all()
    items = []
    for r in rows:
        try:
            m = json.loads(r.metrics_json or "{}")
        except json.JSONDecodeError:
            m = {}
        items.append({
            "id": r.id, "label": r.label, "strategy_key": r.strategy_key,
            "strategy_name": r.strategy_name,
            "symbols": json.loads(r.symbols_json or "[]"),
            "start": r.start_date, "end": r.end_date,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "metrics": {
                k: m.get(k) for k in
                ("total_return", "cagr", "sharpe", "sortino", "calmar", "max_drawdown",
                 "win_rate", "profit_factor", "trades", "volatility")
            },
        })
    return {"items": items}


@router.get("/{rid}")
def detail(rid: int, db: DbSession, user: CurrentUser) -> dict:  # noqa: ARG001
    r = db.get(BacktestRun, rid)
    if not r:
        raise HTTPException(404, "回测记录不存在")
    def _j(s: str, d):  # noqa: ANN001
        try:
            return json.loads(s) if s else d
        except json.JSONDecodeError:
            return d
    return {
        "id": r.id, "label": r.label, "strategy_key": r.strategy_key,
        "strategy_name": r.strategy_name, "symbols": _j(r.symbols_json, []),
        "params": _j(r.params_json, {}), "risk": _j(r.risk_json, {}),
        "start": r.start_date, "end": r.end_date,
        "initial_capital": r.initial_capital,
        "benchmark": getattr(r, "benchmark", "") or "SPY",
        "commission_bps": float(getattr(r, "commission_bps", 0.0) or 0.0),
        "slippage_bps": float(getattr(r, "slippage_bps", 0.0) or 0.0),
        "interval": getattr(r, "interval", "1d") or "1d",
        "data_source": getattr(r, "data_source", "") or "auto",
        "metrics": _j(r.metrics_json, {}),
        "curve": _j(r.equity_json, []),
        "trades": _j(r.trades_json, []),
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


@router.delete("/{rid}")
def remove(rid: int, db: DbSession, user: CurrentUser) -> dict:
    r = db.get(BacktestRun, rid)
    if not r:
        raise HTTPException(404, "回测记录不存在")
    db.delete(r)
    db.commit()
    appstate.log("backtest_delete", "INFO", f"删除回测记录 #{rid}", actor=user.username)
    return {"ok": True}
