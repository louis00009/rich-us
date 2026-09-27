"""ORM 模型。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    last_login: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    totp_secret_enc: Mapped[str] = mapped_column(Text, default="")


class AppSetting(Base):
    """键值设置表；value 为 Text，敏感值由 security.encrypt 加密后存入。"""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class StrategyConfig(Base):
    """用户自定义策略（参数化内置策略 / 规则 DSL / 代码策略）。"""
    __tablename__ = "strategy_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))          # builtin | rule | code
    strategy_key: Mapped[str] = mapped_column(String(80))   # 内置策略 key，或 custom_rule / custom_code
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    rule_json: Mapped[str] = mapped_column(Text, default="")   # kind=rule 时使用
    code: Mapped[str] = mapped_column(Text, default="")        # kind=code 时使用
    symbols_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_json: Mapped[str] = mapped_column(Text, default="{}")  # 该策略专属风控/止损覆盖
    notes: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(160), default="")
    strategy_key: Mapped[str] = mapped_column(String(80), index=True)
    strategy_name: Mapped[str] = mapped_column(String(120), default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_json: Mapped[str] = mapped_column(Text, default="{}")
    symbols_json: Mapped[str] = mapped_column(Text, default="[]")
    start_date: Mapped[str] = mapped_column(String(12), default="")
    end_date: Mapped[str] = mapped_column(String(12), default="")
    initial_capital: Mapped[float] = mapped_column(Float, default=100_000.0)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    equity_json: Mapped[str] = mapped_column(Text, default="[]")
    trades_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    broker_order_id: Mapped[str] = mapped_column(String(64), default="")
    mode: Mapped[str] = mapped_column(String(10), default="paper", index=True)   # paper | live
    broker: Mapped[str] = mapped_column(String(16), default="simulated")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    sec_type: Mapped[str] = mapped_column(String(10), default="STK")
    side: Mapped[str] = mapped_column(String(8))                     # BUY | SELL
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    order_type: Mapped[str] = mapped_column(String(16), default="MKT")  # MKT|LMT|STP|STP_LMT
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")   # T-112：计价币种 USD/HKD
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_configs.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"
    __table_args__ = (UniqueConstraint("mode", "symbol", name="uq_pos_mode_symbol"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), default="paper")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_configs.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class RiskConfig(Base):
    """全局风控与止损默认值（单行，id=1）。"""
    __tablename__ = "risk_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # 仓位与集中度
    max_position_pct: Mapped[float] = mapped_column(Float, default=20.0)        # 单标的占权益上限 %
    max_gross_exposure_pct: Mapped[float] = mapped_column(Float, default=100.0)  # 总敞口上限 %
    max_open_positions: Mapped[int] = mapped_column(Integer, default=10)
    min_order_notional: Mapped[float] = mapped_column(Float, default=200.0)
    # 亏损保护
    max_order_notional: Mapped[float] = mapped_column(Float, default=50_000.0)   # 单笔上限 $
    max_daily_loss_pct: Mapped[float] = mapped_column(Float, default=3.0)        # 日亏上限 %
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=15.0)         # 回撤熔断 %
    # 默认止损
    stop_type: Mapped[str] = mapped_column(String(24), default="atr_trailing")
    stop_value: Mapped[float] = mapped_column(Float, default=3.0)                # ATR 倍数 / 百分比
    take_profit_r: Mapped[float] = mapped_column(Float, default=2.0)             # R 倍数止盈，0=关闭
    time_stop_bars: Mapped[int] = mapped_column(Integer, default=0)              # 0=关闭
    # 仓位算法
    sizing_method: Mapped[str] = mapped_column(String(24), default="atr_risk")
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0)        # 每笔风险 %
    # 交易时段
    trading_hours_only: Mapped[bool] = mapped_column(Boolean, default=True)
    # 市场感知（C1/T-113/T-114）
    allow_short: Mapped[bool] = mapped_column(Boolean, default=False)          # 做空开关
    allow_extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)  # 盘前盘后
    hk_max_gross_exposure_pct: Mapped[float] = mapped_column(Float, default=100.0)
    max_daily_orders: Mapped[int] = mapped_column(Integer, default=0)
    max_orders_per_minute: Mapped[int] = mapped_column(Integer, default=0)
    # 白/黑名单（逗号分隔）
    whitelist: Mapped[str] = mapped_column(Text, default="")
    blacklist: Mapped[str] = mapped_column(Text, default="")
    # 熔断
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    live_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(12), default="INFO")   # INFO|WARN|CRITICAL
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class EngineRun(Base):
    """实盘/模拟引擎的一次运行记录。"""
    __tablename__ = "engine_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategy_configs.id"), index=True)
    mode: Mapped[str] = mapped_column(String(10), default="paper", index=True)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING", index=True)  # RUNNING|STOPPED|ERROR
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    stopped_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_tick: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")

    strategy: Mapped[StrategyConfig] = relationship()


class NewsCache(Base):
    """新闻缓存：跨 provider 去重落库，网络失败时可回读最近抓取结果。"""
    __tablename__ = "news_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(24), index=True)   # finnhub | yahoo-rss | ibkr | hkex
    category: Mapped[str] = mapped_column(String(16), default="company")  # company | market | announcement
    symbol: Mapped[str] = mapped_column(String(32), default="", index=True)
    market: Mapped[str] = mapped_column(String(8), default="US")
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)


class WatchlistItem(Base):
    """关注列表（本机单用户）。"""
    __tablename__ = "watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    market: Mapped[str] = mapped_column(String(8), default="US")
    note: Mapped[str] = mapped_column(Text, default="")
    held: Mapped[bool] = mapped_column(Boolean, default=False)   # 是否来自持仓一键关注
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class AlertEvent(Base):
    """智能提示：新闻关键词 / 技术信号 触发的一次事件（按 dedup_key 去重）。"""
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)    # news | high_52w | low_52w | volume_spike | gap | rsi | swing
    level: Mapped[str] = mapped_column(String(8), default="info")  # info | hot | warn
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(8), default="US")
    title: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class DecisionLog(Base):
    """决策日志：每一次引擎/AI 的交易决策都可回溯。

    设计目标（AI 可接管）：任何模型接手时，能从 context_json 还原
    「当时看到什么因子 → 为什么这么决定 → 最终下了什么单」的完整链条。
    """
    __tablename__ = "decision_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(48), default="engine", index=True)  # engine:<策略id> | ai:<model> | user:<名字>
    symbol: Mapped[str] = mapped_column(String(32), default="", index=True)
    market: Mapped[str] = mapped_column(String(8), default="US")
    action: Mapped[str] = mapped_column(String(24), index=True)  # BUY | SELL | HOLD | SKIP:<原因> | ANALYZE | ALERT
    decision: Mapped[str] = mapped_column(Text, default="")      # 人话结论（一句话）
    reasoning: Mapped[str] = mapped_column(Text, default="")     # 推理过程 / 依据摘要
    context_json: Mapped[str] = mapped_column(Text, default="{}")  # 因子快照（行情/指标/信号/风控）
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    engine_run_id: Mapped[int | None] = mapped_column(ForeignKey("engine_runs.id"), nullable=True)


class AiProposal(Base):
    """AI 交易提案（T-107）：AI 出建议单 → 人工批准 → 走正常下单链。

    硬边界：status 非 approved 绝不产生任何订单；AI 永远只有建议权。
    """
    __tablename__ = "ai_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(8))                    # BUY | SELL | CLOSE
    size_pct: Mapped[float] = mapped_column(Float, default=0.0)       # 建议仓位（占权益 %）
    entry: Mapped[float] = mapped_column(Float, default=0.0)          # 建议入场参考价
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")          # AI 理由
    factors_json: Mapped[str] = mapped_column(Text, default="{}")     # 因子快照
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)  # proposed|approved|executed|rejected|expired
    created_by: Mapped[str] = mapped_column(String(48), default="ai")
    reviewed_by: Mapped[str] = mapped_column(String(48), default="")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)


class CompanyProfile(Base):
    """公司档案缓存（英文名 + 英文介绍 + 关键信息 + 中文名）。"""
    __tablename__ = "company_profiles"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, default="")
    name_cn: Mapped[str] = mapped_column(Text, default="")   # 中文名（腾讯行情）
    industry: Mapped[str] = mapped_column(Text, default="")
    sector: Mapped[str] = mapped_column(Text, default="")
    country: Mapped[str] = mapped_column(String(48), default="")
    website: Mapped[str] = mapped_column(Text, default="")
    ipo_date: Mapped[str] = mapped_column(String(16), default="")
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ==================================================================
# AI 情报中心（Intel Center）
# 设计要点：
#   · 外部 AI Agent（WorkBuddy / Claude Code / Codex）通过 Bridge API
#     用独立 token（X-Intel-Token）领任务、提交事件与建议 —— 与交易账户完全隔离；
#   · 事件按 dedupe_key 唯一约束去重（symbol + 类别 + 标题归一化）；
#   · 一次「开启 → 截止」是一个 Run，截止时自动落盘 Markdown 报告。
# ==================================================================
class IntelCompany(Base):
    """情报观察标的：美股核心公司。"""
    __tablename__ = "intel_companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[str] = mapped_column(Text, default="")     # 关注主题，如 AI 算力 / 自动驾驶 / 云
    focus: Mapped[str] = mapped_column(Text, default="")     # 关注要点提示（会注入 Agent 任务简报）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_scrape_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class IntelEvent(Base):
    """情报事件节点：模型发布 / 产品发布 / 合作 / 财报 / 监管 等里程碑。"""
    __tablename__ = "intel_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    occurred_on: Mapped[str] = mapped_column(String(10), default="")  # 事件发生日 YYYY-MM-DD（允许空=未知）
    category: Mapped[str] = mapped_column(String(24), default="other", index=True)
    # model_release | product_launch | partnership | earnings | regulatory | personnel | macro | other
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[int] = mapped_column(Integer, default=3)          # 1~5 星
    sentiment: Mapped[str] = mapped_column(String(8), default="neutral")  # positive | neutral | negative
    source_name: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    # 前瞻管道阶段（经营可见性）：confirmed=已敲定（签 约/落地）、negotiating=在谈、
    # rumor=传闻、空=普通事件。财报滞后，用合同管道前瞻未来 3-6 个月经营。
    stage: Mapped[str] = mapped_column(String(16), default="", index=True)
    dedupe_key: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    agent: Mapped[str] = mapped_column(String(48), default="", index=True)   # 提交方：workbuddy / claude-code / codex / local-llm
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)


class IntelAnalysis(Base):
    """AI 买入建议：基于事件面 + 量化快照给出。"""
    __tablename__ = "intel_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    recommendation: Mapped[str] = mapped_column(String(16), index=True)
    # strong_buy | buy | hold | reduce | avoid
    confidence: Mapped[float] = mapped_column(Float, default=50.0)   # 0~100
    thesis: Mapped[str] = mapped_column(Text, default="")            # 核心论点
    catalysts: Mapped[str] = mapped_column(Text, default="")         # 催化剂（分号分隔或换行）
    risks: Mapped[str] = mapped_column(Text, default="")             # 风险
    position_pct: Mapped[float] = mapped_column(Float, default=0.0)  # 建议仓位 %
    invalidation: Mapped[str] = mapped_column(Text, default="")      # 失效条件（什么情况判断作废）
    price_at_analysis: Mapped[float] = mapped_column(Float, default=0.0)
    horizon: Mapped[str] = mapped_column(String(16), default="swing")  # intraday | swing | position
    based_on_events: Mapped[str] = mapped_column(Text, default="[]")   # JSON：依据的事件 id 列表（可溯源）
    event_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 事件面评分 -100~100（近期信息加权）
    outcome_window_days: Mapped[int] = mapped_column(Integer, default=7)     # 验证窗口（天）
    outcome_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)  # 验证时间
    outcome_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 验证时价格
    outcome_return: Mapped[float | None] = mapped_column(Float, nullable=True)  # 窗口收益 %（验证价/分析价-1）
    outcome_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)    # 方向是否正确（hold 不验证）
    agent: Mapped[str] = mapped_column(String(48), default="", index=True)
    engine: Mapped[str] = mapped_column(String(16), default="agent")   # agent | llm | local
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)


class IntelRun(Base):
    """一次「一键开启 → 截止」的监控批次。"""
    __tablename__ = "intel_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running | finished | stopped
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    auto_analyze: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    last_tick_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    events_found: Mapped[int] = mapped_column(Integer, default=0)
    analyses_done: Mapped[int] = mapped_column(Integer, default=0)
    agents_seen: Mapped[str] = mapped_column(Text, default="[]")     # JSON 数组：参与 agent 名单
    note: Mapped[str] = mapped_column(Text, default="")
    report_path: Mapped[str] = mapped_column(Text, default="")       # 截止后落盘的报告路径


class IntelBridgeLog(Base):
    """Bridge 活动日志：外部 Agent 的每次领任务/提交记录（可追溯）。"""
    __tablename__ = "intel_bridge_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    agent: Mapped[str] = mapped_column(String(48), default="unknown")
    action: Mapped[str] = mapped_column(String(24), index=True)      # poll | brief | submit_events | submit_analysis | done
    detail: Mapped[str] = mapped_column(Text, default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)


class IntelSetting(Base):
    """情报中心全局设置（单行，id=1）。monitor_enabled 持久化以便服务重启后自恢复。"""
    __tablename__ = "intel_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)       # 恒为 1
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    auto_analyze: Mapped[bool] = mapped_column(Boolean, default=True)
    bridge_token: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
