"""系统接口：状态、券商设置与连通性测试、审计概览。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from .. import state as appstate
from ..brokers import get_broker
from ..config import FRONTEND_DIST, RUNTIME_DIR, settings
from ..schemas import AISettingsIn, BrokerSettingsIn
from .deps import CurrentUser

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/status")
def status(user: CurrentUser) -> dict:  # noqa: ARG001
    base = appstate.system_status()
    base["runtime_dir"] = str(RUNTIME_DIR)
    base["frontend_built"] = (FRONTEND_DIST / "index.html").exists()
    base["engine_tick_sec"] = settings.engine_tick_sec
    return base


@router.get("/latency")
def latency(user: CurrentUser) -> dict:  # noqa: ARG001
    """交易路径分段延迟（p50/p95/p99 + 预算健康度）+ 最近慢请求（T-137 延迟面板）。"""
    from ..engine.latency import get_latency

    out = get_latency().summary()
    out["slow_requests"] = appstate.slow_requests()
    return out


@router.get("/broker")
def get_broker_settings(user: CurrentUser) -> dict:  # noqa: ARG001
    cfg = appstate.get_broker_settings()
    return {
        "config": cfg,
        "presets": [
            {"key": "simulated", "label": "模拟盘（内置，零风险）", "host": "-", "port": 0},
            {"key": "tws-paper", "label": "TWS 纸面", "host": "127.0.0.1", "port": settings.ibkr_paper_tws_port},
            {"key": "tws-live", "label": "TWS 实盘", "host": "127.0.0.1", "port": settings.ibkr_live_tws_port},
            {"key": "gw-paper", "label": "IB Gateway 纸面", "host": "127.0.0.1", "port": settings.ibkr_paper_gw_port},
            {"key": "gw-live", "label": "IB Gateway 实盘", "host": "127.0.0.1", "port": settings.ibkr_live_gw_port},
        ],
        "setup_guide": [
            "1. 安装并登录 TWS（或 IB Gateway），使用纸面账户登录",
            "2. TWS → 文件 → 全局配置 → API → 设置：勾选「启用 ActiveX 和 Socket 客户端」",
            "3. 取消勾选「只读 API」才能下单；如需本工具只读监控则保持勾选",
            "4. 端口：TWS 纸面 7497 / 实盘 7496；Gateway 纸面 4002 / 实盘 4001",
            "5. 在「已信任的 IP 地址」中添加 127.0.0.1（或取消「仅接受本地连接」时填本机 IP）",
            "6. 若同一时间有多个客户端连接，请为每个客户端分配不同的 client_id",
            "7. 回到本页保存并点击「测试连接」",
        ],
    }


@router.put("/broker")
def put_broker_settings(payload: BrokerSettingsIn, user: CurrentUser) -> dict:
    cfg = appstate.set_broker_settings(payload.model_dump())
    port = int(cfg.get("port", 0))
    is_live_port = port in (7496, 4001)
    appstate.log("broker_settings_update", "WARN" if is_live_port else "INFO",
                 f"券商设置更新：provider={cfg.get('provider')} {cfg.get('host')}:{port} "
                 f"readonly={cfg.get('readonly')}", actor=user.username)
    warn = ""
    if is_live_port:
        warn = "⚠️ 当前端口为实盘端口。实盘下单仍受「环境变量 + 运行时解锁 + 逐笔护栏」三道锁保护。"
    return {"ok": True, "config": cfg, "warning": warn}


@router.post("/broker/test")
async def test_broker(user: CurrentUser) -> dict:  # noqa: ARG001
    # P0-2：get_broker_settings / log 均为同步查库，走线程池避免阻塞事件循环
    cfg = await run_in_threadpool(appstate.get_broker_settings)
    broker, mode = get_broker(cfg)
    try:
        ok, msg = await run_in_threadpool(broker.connect)
    except Exception as exc:  # noqa: BLE001
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    detail = {}
    if ok:
        try:
            acc = await run_in_threadpool(broker.account)
            detail = acc.dict()
        except Exception as exc:  # noqa: BLE001
            detail = {"error": str(exc)}
    await run_in_threadpool(appstate.log, "broker_test", "INFO" if ok else "WARN",
                            f"券商连通性测试：{msg}", user.username)
    return {"ok": ok, "message": msg, "mode": mode, "provider": cfg.get("provider"), "account": detail}


@router.post("/broker/disconnect")
async def disconnect_broker(user: CurrentUser) -> dict:
    cfg = await run_in_threadpool(appstate.get_broker_settings)
    broker, _ = get_broker(cfg)
    try:
        await run_in_threadpool(broker.disconnect)
        await run_in_threadpool(appstate.log, "broker_disconnect", "INFO",
                                "已断开券商连接", user.username)
        return {"ok": True, "message": "已断开"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.get("/audit-summary")
def audit_summary(user: CurrentUser) -> dict:  # noqa: ARG001
    from sqlalchemy import func, select

    from ..database import SessionLocal
    from ..models import AuditLog, BacktestRun, Order, StrategyConfig

    with SessionLocal() as s:
        by_level = dict(s.execute(select(AuditLog.level, func.count()).group_by(AuditLog.level)).all())
        total_audit = s.query(AuditLog).count()
        orders = s.query(Order).count()
        live_orders = s.query(Order).filter(Order.mode == "live").count()
        backtests = s.query(BacktestRun).count()
        strategies = s.query(StrategyConfig).count()
    return {
        "audit_total": total_audit,
        "audit_by_level": by_level,
        "orders_total": orders,
        "live_orders": live_orders,
        "backtests": backtests,
        "custom_strategies": strategies,
    }


# ------------------------------------------------------------------
# AI（LLM）全局设置 —— 对接 WorkBuddy Manager 网关 / 任意 OpenAI 兼容端点
# ------------------------------------------------------------------
def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:3] + "****"
    return f"{key[:6]}****{key[-4:]}"


def _fetch_gateway_models(base_url: str, api_key: str) -> dict:
    """实时拉网关 /v1/models，按 `global:` 前缀分组为国内/国际两栏。

    网关按密钥的版本归属过滤清单：国内版密钥只见 `cn:` 条目。若 global 栏
    为空，多半是密钥在面板「密钥」页绑定了国内版 —— 改为「不限定」即可。
    模块级缓存 60s，避免设置页每次打开都打一发请求。
    """
    import time as _time

    from urllib.parse import urlparse

    global _MODEL_CACHE  # noqa: PLW0603
    now = _time.time()
    cache_key = f"{base_url}|{api_key}"
    if _MODEL_CACHE.get("key") == cache_key and now - _MODEL_CACHE.get("ts", 0) < 60:
        return _MODEL_CACHE["data"]
    out: dict = {"ok": False, "cn": [], "global": [], "error": ""}
    try:
        import httpx

        host = (urlparse(base_url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(f"仅允许本机回环网关，收到：{host!r}")
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{base_url.rstrip('/')}/v1/models",
                      headers={"Authorization": f"Bearer {api_key}"})
            r.raise_for_status()
            ids = [str(m.get("id")) for m in r.json().get("data", []) if m.get("id")]
        out["ok"] = True
        out["cn"] = sorted(x for x in ids if not x.lower().startswith("global:"))
        out["global"] = sorted(x for x in ids if x.lower().startswith("global:"))
    except Exception as exc:  # noqa: BLE001 —— 设置页要如实显示失败原因
        out["error"] = f"{type(exc).__name__}: {exc}"
    _MODEL_CACHE = {"key": cache_key, "ts": now, "data": out}
    return out


_MODEL_CACHE: dict = {}


def _model_cache_clear() -> None:
    """丢弃网关模型缓存 —— 「重试连接」要拿**当下**的可达性，不能拿 60s 前的结论。"""
    global _MODEL_CACHE  # noqa: PLW0603
    _MODEL_CACHE = {}


@router.get("/links")
async def links(refresh: bool = False, user: CurrentUser = None) -> dict:  # noqa: ARG001
    """
    顶部「连接状态」组件用：券商（TWS / IB Gateway）与 AI 网关的可用性 + 失败原因。

    **只读探活，不主动发起连接** —— 真正连 TWS 是 `POST /system/broker/test` 的事，
    （TWS 握手会占用 client_id 并可能弹窗，不能让顶栏轮询顺手触发）。
    `refresh=1` 会跳过 60s 的网关模型缓存，重新打一次 /v1/models。

    state 三态：`ok` 绿 / `error` 红 / `na` 灰（不适用：内置模拟券商、AI 未配置）。
    """
    from datetime import datetime, timezone

    cfg = await run_in_threadpool(appstate.get_broker_settings)
    ai_cfg = await run_in_threadpool(appstate.get_ai_settings)

    # ---------------- 券商 / TWS ----------------
    provider = str(cfg.get("provider", "simulated") or "simulated")
    host = str(cfg.get("host", "") or "")
    try:
        port = int(cfg.get("port", 0) or 0)
    except (TypeError, ValueError):
        port = 0

    broker_info: dict = {
        "provider": provider,
        "host": host,
        "port": port,
        "label": "内置模拟券商",
        "mode": "paper",
        "state": "na",
        "connected": False,
        "account": "",
        "client_id": None,
        "market_data_label": "",
        "detail": "当前未启用 IBKR：下单与行情都走内置模拟券商（零资金风险）",
        "error": "",
    }

    if provider == "ibkr":
        broker_info["label"] = f"IBKR {host}:{port}"
        try:
            broker, mode = get_broker(cfg)
            connected = bool(getattr(broker, "connected", False))
            st: dict = {}
            try:
                st = broker.status() or {}
            except Exception as exc:  # noqa: BLE001 —— 状态读取失败不该让顶栏 500
                st = {"error": f"{type(exc).__name__}: {exc}"}
            broker_info.update(
                {
                    "mode": mode,
                    "connected": connected,
                    "state": "ok" if connected else "error",
                    "account": st.get("account") or "",
                    "client_id": st.get("client_id"),
                    "market_data_label": st.get("market_data_label") or "",
                    "detail": (
                        f"已连接 · 账户 {st.get('account') or '—'} · {st.get('market_data_label') or '延迟'}行情"
                        if connected
                        else "未连接：TWS / Gateway 未就绪，或 API 端口与「启用 Socket 客户端」未打开"
                    ),
                    "error": "" if connected else (st.get("error") or ""),
                }
            )
        except Exception as exc:  # noqa: BLE001
            broker_info.update(
                {
                    "state": "error",
                    "connected": False,
                    "detail": f"读取券商状态失败：{type(exc).__name__}: {exc}",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    # ---------------- AI 网关 ----------------
    base_url = str(ai_cfg.get("base_url") or settings.ai_base_url or "")
    api_key = str(ai_cfg.get("api_key") or settings.ai_api_key or "")
    model = str(ai_cfg.get("model") or settings.ai_model or "")
    ai_info: dict = {
        "configured": bool(base_url and api_key),
        "model": model,
        "base_url": base_url,
        "models": 0,
        "state": "na",
        "detail": "未配置 AI 网关：所有 AI 功能退回本地确定性规则兜底（不报错、不编造）",
        "error": "",
    }
    if ai_info["configured"]:
        if refresh:
            _model_cache_clear()
        data = await run_in_threadpool(_fetch_gateway_models, base_url, api_key)
        n = len(data.get("cn") or []) + len(data.get("global") or [])
        if data.get("ok"):
            ai_info.update(
                {"state": "ok", "models": n, "detail": f"网关可达 · 当前模型 {model or '—'} · 共 {n} 个可选"}
            )
        else:
            err = data.get("error") or "网关不可达"
            ai_info.update(
                {
                    "state": "error",
                    "models": 0,
                    "error": err,
                    "detail": f"{err} —— 请确认已运行 IBKR 目录下的 aistart.bat",
                }
            )

    return {
        "broker": broker_info,
        "ai": ai_info,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ai")
def get_ai_settings_route(user: CurrentUser) -> dict:  # noqa: ARG001
    cfg = appstate.get_ai_settings()
    models = _fetch_gateway_models(cfg.get("base_url", ""), cfg.get("api_key", ""))
    return {
        "config": {**cfg, "api_key": _mask_key(cfg.get("api_key", ""))},
        "has_key": bool(cfg.get("api_key")),
        "models": models,
        "env_fallback": {
            "configured": bool(settings.ai_base_url and settings.ai_api_key),
            "model": settings.ai_model,
        },
    }


@router.put("/ai")
def put_ai_settings_route(payload: AISettingsIn, user: CurrentUser) -> dict:
    data = payload.model_dump(exclude_none=True)
    if not data.get("api_key"):
        data.pop("api_key", None)  # 空 = 保持现有密钥（前端只回显掩码）
    cfg = appstate.set_ai_settings(data)
    appstate.log("ai_settings_update", "INFO",
                 f"AI 全局配置更新：model={cfg.get('model')} base_url={cfg.get('base_url')}",
                 actor=user.username)
    return {"ok": True, "config": {**cfg, "api_key": _mask_key(cfg.get("api_key", ""))}}


@router.post("/ai/test")
async def test_ai(user: CurrentUser) -> dict:  # noqa: ARG001
    """用当前全局配置发一次最小真实调用，验证网关/密钥/模型三者都通。"""
    from ..ai_analyst import _llm_call

    try:
        text = await run_in_threadpool(
            _llm_call,
            [{"role": "user", "content": "回复「连接正常」四个字，不要输出其他内容。"}],
            0.0,
            800,
            "",
        )
        head = (text or "").strip()[:60]
        return {"ok": True, "message": f"AI 连通正常：{head}"}
    except Exception as exc:  # noqa: BLE001
        await run_in_threadpool(appstate.log, "ai_test", "WARN",
                                f"AI 连通性测试失败：{exc}", user.username)
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
