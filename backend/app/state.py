"""
运行时状态中心
===============
集中管理：审计日志、键值设置、券商设置、风控配置、当前交易模式、实盘解锁状态。
所有写入都落库，重启后保持一致；实盘解锁状态额外保留在内存中作为快速判断。
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .config import settings as app_settings
from .database import session_scope
from .models import AppSetting, AuditLog, RiskConfig
from .security import decrypt, encrypt
from .risk.guardrails import RiskLimits

# ------------------------------------------------------------------
# 审计日志
# ------------------------------------------------------------------
def log(action: str, level: str = "INFO", detail: str = "", actor: str = "system", ip: str = "") -> None:
    try:
        with session_scope() as s:
            s.add(AuditLog(actor=actor, action=action, level=level, detail=detail[:4000], ip=ip))
    except Exception:  # noqa: BLE001
        # 审计失败不能阻塞主流程，但要打到控制台便于排查
        print(f"[audit-fail] {action} {level} {detail}")


# ------------------------------------------------------------------
# 键值设置
# ------------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    with session_scope() as s:
        row = s.get(AppSetting, key)
        return row.value if row and row.value else default


def set_setting(key: str, value: str, is_secret: bool = False) -> None:
    with session_scope() as s:
        row = s.get(AppSetting, key)
        if row:
            row.value = value
            row.is_secret = is_secret
        else:
            s.add(AppSetting(key=key, value=value, is_secret=is_secret))


def set_secret(key: str, plaintext: str) -> None:
    set_setting(key, encrypt(plaintext), is_secret=True)


def get_secret(key: str, default: str = "") -> str:
    raw = get_setting(key, "")
    return decrypt(raw) if raw else default


# ------------------------------------------------------------------
# 券商设置
# ------------------------------------------------------------------
BROKER_KEY = "broker_settings"

DEFAULT_BROKER: dict[str, Any] = {
    "provider": "simulated",
    "host": "127.0.0.1",
    "port": app_settings.ibkr_paper_tws_port,
    "client_id": app_settings.ibkr_client_id,
    "account": "",
    "connection_type": "tws",
    "readonly": True,
    "market_data_type": int(app_settings.ibkr_market_data_type),
    "use_rth": True,
}


def get_broker_settings() -> dict[str, Any]:
    raw = get_setting(BROKER_KEY, "")
    if not raw:
        return dict(DEFAULT_BROKER)
    try:
        data = json.loads(raw)
        return {**DEFAULT_BROKER, **data}
    except json.JSONDecodeError:
        return dict(DEFAULT_BROKER)


def set_broker_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    cur = get_broker_settings()
    merged = {**cur, **{k: v for k, v in cfg.items() if v is not None}}
    set_setting(BROKER_KEY, json.dumps(merged))
    return merged


# ------------------------------------------------------------------
# 风控配置
# ------------------------------------------------------------------
RISK_COLUMNS = [    "max_position_pct", "max_gross_exposure_pct", "max_open_positions", "min_order_notional",
    "max_order_notional", "max_daily_loss_pct", "max_drawdown_pct", "stop_type", "stop_value",
    "take_profit_r", "time_stop_bars", "sizing_method", "risk_per_trade_pct",
    "trading_hours_only", "whitelist", "blacklist",
    "kill_switch",          # 必须在此白名单内，否则启用熔断会被静默丢弃
    "allow_short",          # T-113：做空开关（false 时裸卖/卖超持仓直接拒绝）
    "allow_extended_hours",  # T-114：盘前盘后
    "hk_max_gross_exposure_pct",
    "max_daily_orders", "max_orders_per_minute",
]


def get_risk_row() -> RiskConfig:
    with session_scope() as s:
        row = s.get(RiskConfig, 1)
        if row is None:
            row = RiskConfig(id=1)
            s.add(row)
            s.flush()
        s.expunge(row)
        return row


def update_risk_config(payload: dict[str, Any]) -> RiskConfig:
    with session_scope() as s:
        row = s.get(RiskConfig, 1)
        if row is None:
            row = RiskConfig(id=1)
            s.add(row)
        for k, v in payload.items():
            if k in RISK_COLUMNS and v is not None:
                setattr(row, k, v)
        s.flush()
        s.expunge(row)
        return row


def risk_limits() -> RiskLimits:
    return RiskLimits.from_config(get_risk_row())


# ------------------------------------------------------------------
# 护栏上下文构造（P0-5：计数器接入 + P1-5：币种折算）
# ------------------------------------------------------------------
def build_guard_context(
    acc: Any,
    positions: list[Any],
    now: dt.datetime | None = None,
) -> "GuardContext":
    """从账户快照 + 持仓列表构造 GuardContext，供全部 4 处下单链路复用。

    修复的两个静默缺陷：
      1. (P0-5) 旧实现 4 处构造点均未给 market_exposure / orders_today /
         orders_last_minute 赋值 → 港股敞口上限、日内笔数、每分钟笔数三条风控
         永不生效（其中 max_orders_per_minute 是防 IBKR 限流封号的关键保护）。
         这里从订单表统计真实计数。
      2. (P1-5) 旧实现把持仓 market_value（原币，港股为 HKD）与 equity（USD base）
         直接相加比较 —— 港股敞口被虚增约 7.8 倍。这里按持仓币种折算到账户基准币种。
    """
    from sqlalchemy import func, select

    from .markets import fx
    from .models import Order
    from .risk.guardrails import GuardContext

    base = str(getattr(acc, "base_currency", "") or getattr(acc, "currency", "") or "USD").upper()
    open_map: dict[str, float] = {}
    market_exp: dict[str, float] = {}
    gross = 0.0
    for p in positions or []:
        sym = str(getattr(p, "symbol", "") or "").upper()
        if not sym:
            continue
        mv = float(getattr(p, "market_value", 0.0) or 0.0)
        ccy = str(getattr(p, "currency", "") or "").upper()
        mv_base = mv
        try:
            if ccy and base and ccy != base:
                mv_base = fx.to_base(mv, ccy, base)
        except Exception:  # noqa: BLE001 —— 汇率不可得时按原值计（宁可高估不可低估敞口）
            mv_base = mv
        open_map[sym] = mv_base
        gross += abs(mv_base)
        mk = str(getattr(p, "market", "") or "").upper()
        if mk not in ("US", "HK"):
            mk = "HK" if sym.endswith(".HK") else "US"
        market_exp[mk] = market_exp.get(mk, 0.0) + abs(mv_base)

    now = now or dt.datetime.now(dt.timezone.utc)
    minute_ago = now - dt.timedelta(seconds=60)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    orders_today = 0
    orders_last_minute = 0
    try:
        with session_scope() as s:
            orders_today = int(
                s.execute(select(func.count()).select_from(Order).where(Order.created_at >= day_start)).scalar() or 0
            )
            orders_last_minute = int(
                s.execute(
                    select(func.count()).select_from(Order).where(Order.created_at >= minute_ago)
                ).scalar() or 0
            )
    except Exception:  # noqa: BLE001 —— 计数失败不阻塞下单，但绝不虚报为 0 以外的数
        pass

    return GuardContext(
        equity=float(getattr(acc, "equity", 0.0) or 0.0),
        day_start_equity=float(getattr(acc, "equity", 0.0) or 0.0) - float(getattr(acc, "day_pnl", 0.0) or 0.0),
        peak_equity=max(
            float(getattr(acc, "equity", 0.0) or 0.0),
            float(getattr(acc, "equity", 0.0) or 0.0) - float(getattr(acc, "day_pnl", 0.0) or 0.0),
        ),
        open_positions=open_map,
        gross_exposure=gross,
        market_exposure=market_exp,
        orders_today=orders_today,
        orders_last_minute=orders_last_minute,
        now=now,
        is_live=(effective_mode() == "live"),
    )


# ------------------------------------------------------------------
# 模式与实盘解锁
# ------------------------------------------------------------------
_mode: str = "paper"                 # paper | live
_live_unlocked: bool = False
_live_loaded: bool = False


def current_mode() -> str:
    return _mode


def effective_mode() -> str:
    """实际下单通道模式 = UI 模式开关 ∧ 券商端口（P1-9 统一数据源）。

    旧实现里 UI 显示的 mode 来自 current_mode()（重启恒回 paper），
    而下单通道由券商端口推导 —— 端口 7496 时界面显示「模拟盘」却真实下单。
    现在约定：UI 模式开关是权威路由（paper 状态下强制走模拟券商），
    本函数返回值与真实下单通道严格一致，所有展示与口令门控都应使用它。
    """
    if _mode != "live":
        return "paper"
    try:
        cfg = get_broker_settings()
        if str(cfg.get("provider", "")) != "ibkr":
            return "paper"
        return "live" if int(cfg.get("port", 7497)) in (7496, 4001) else "paper"
    except Exception:  # noqa: BLE001
        return "paper"


def set_current_mode(mode: str) -> None:
    global _mode
    if mode not in ("paper", "live"):
        raise ValueError("mode 只能是 paper 或 live")
    _mode = mode
    if mode == "paper":
        set_live_unlocked(False)


def _ensure_live_loaded() -> None:
    """首次访问时从数据库恢复实盘解锁状态。

    否则重启后内存标志为 False，而接口返回的 DB 值可能仍为 True，
    同一次响应里两个字段互相矛盾。
    注意：仅恢复解锁标志，运行模式一律回到 paper（重启默认最安全）。
    """
    global _live_unlocked, _live_loaded
    if _live_loaded:
        return
    _live_loaded = True
    try:
        with session_scope() as s:
            row = s.get(RiskConfig, 1)
            if row is not None:
                _live_unlocked = bool(row.live_unlocked)
    except Exception:  # noqa: BLE001
        _live_unlocked = False


def live_unlocked() -> bool:
    _ensure_live_loaded()
    return bool(_live_unlocked)


def set_live_unlocked(flag: bool) -> None:
    global _live_unlocked
    _live_unlocked = bool(flag)
    try:
        with session_scope() as s:
            row = s.get(RiskConfig, 1)
            if row:
                row.live_unlocked = bool(flag)
    except Exception:  # noqa: BLE001
        pass


def live_trading_available() -> tuple[bool, str]:
    """返回 (是否可实盘, 说明)。"""
    if not app_settings.allow_live_trading:
        return False, "环境变量 QD_ALLOW_LIVE_TRADING 未开启（第一道锁）"
    if not live_unlocked():
        return False, "实盘未解锁（需输入确认短语与账户口令，第二道锁）"
    cfg = get_broker_settings()
    if cfg.get("provider") != "ibkr":
        return False, "当前券商为模拟盘，请先在设置中切换到 IBKR"
    if int(cfg.get("port", 7497)) not in (7496, 4001):
        return False, "当前端口不是实盘端口（TWS 7496 / Gateway 4001）"
    return True, "实盘通道已就绪"


# ------------------------------------------------------------------
# 概览
# ------------------------------------------------------------------
def system_status() -> dict[str, Any]:
    from .strategies import registry_size

    cfg = get_broker_settings()
    row = get_risk_row()
    ok_live, live_reason = live_trading_available()
    return {
        "app": app_settings.app_name,
        "version": app_settings.version,
        "mode": effective_mode(),          # 实际下单通道（P1-9：与口令门控同源）
        "ui_mode": current_mode(),          # UI 模式开关本身
        "broker": cfg.get("provider"),
        "broker_host": f"{cfg.get('host')}:{cfg.get('port')}",
        "readonly": bool(cfg.get("readonly", True)),
        "strategies": registry_size(),
        "kill_switch": bool(row.kill_switch),
        "live_env_gate": bool(app_settings.allow_live_trading),
        "live_unlocked": live_unlocked(),
        "live_ready": ok_live,
        "live_reason": live_reason,
        "ai_configured": bool(app_settings.ai_api_key and app_settings.ai_base_url),
        "server_time": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ==================================================================
# 慢请求监控（T-137）：中间件写入，/api/system/latency 读取
# ==================================================================
from collections import deque as _deque  # noqa: E402

_slow_requests: "deque" = _deque(maxlen=50)


def record_slow_request(path: str, ms: int, at: str) -> None:
    _slow_requests.append({"path": path, "ms": ms, "at": at})


def slow_requests(limit: int = 20) -> list[dict]:
    return list(_slow_requests)[-limit:][::-1]
