"""Pydantic 请求/响应模型 —— 所有外部输入在此强校验。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ------------------------------------------------------------------
# 认证
# ------------------------------------------------------------------
class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=256)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


# ------------------------------------------------------------------
# 行情
# ------------------------------------------------------------------
class HistoryRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)
    start: str = "2020-01-01"
    end: str | None = None
    interval: Literal["1d", "1wk", "1h", "30m", "15m", "5m"] = "1d"

    @field_validator("symbols")
    @classmethod
    def _norm(cls, v: list[str]) -> list[str]:
        out, seen = [], set()
        for s in v:
            t = s.strip().upper()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out


# ------------------------------------------------------------------
# 策略
# ------------------------------------------------------------------
class StrategyInfo(BaseModel):
    key: str
    name: str
    category: str
    description: str
    multi_symbol: bool
    min_bars: int
    tags: list[str] = []
    params: list[dict[str, Any]] = []


class StrategyConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["builtin", "rule", "code"] = "builtin"
    strategy_key: str = ""
    params: dict[str, Any] = {}
    rule: dict[str, Any] | None = None
    code: str = ""
    symbols: list[str] = []
    risk: dict[str, Any] = {}
    notes: str = ""
    tags: list[str] = []


class StrategyConfigOut(BaseModel):
    id: int
    name: str
    kind: str
    strategy_key: str
    params: dict[str, Any]
    rule: dict[str, Any] | None
    code: str
    symbols: list[str]
    risk: dict[str, Any]
    notes: str
    tags: list[str]
    is_active: bool
    created_at: str
    updated_at: str


class ValidateCodeRequest(BaseModel):
    code: str


# ------------------------------------------------------------------
# 风控 / 止损
# ------------------------------------------------------------------
class RiskConfigIn(BaseModel):
    max_position_pct: float = Field(20.0, ge=0.1, le=100)
    max_gross_exposure_pct: float = Field(100.0, ge=1, le=400)
    max_open_positions: int = Field(10, ge=1, le=200)
    min_order_notional: float = Field(200.0, ge=0)
    max_order_notional: float = Field(50_000.0, gt=0)
    max_daily_loss_pct: float = Field(3.0, gt=0, le=100)
    max_drawdown_pct: float = Field(15.0, gt=0, le=100)
    stop_type: Literal[
        "none", "fixed_pct", "pct_trailing", "atr_fixed", "atr_trailing",
        "breakeven", "time_stop", "volatility", "chandelier",
    ] = "atr_trailing"
    stop_value: float = Field(3.0, ge=0)
    take_profit_r: float = Field(2.0, ge=0)
    time_stop_bars: int = Field(0, ge=0)
    sizing_method: Literal[
        "weight", "fixed_fraction", "risk_parity_vol", "atr_risk", "kelly_capped", "equal_weight",
    ] = "atr_risk"
    risk_per_trade_pct: float = Field(1.0, gt=0, le=20)
    trading_hours_only: bool = True
    whitelist: str = ""
    blacklist: str = ""
    # 市场感知（T-113/T-114）
    allow_short: bool = False                    # 做空开关（false 时裸卖/卖超持仓直接拒绝）
    allow_extended_hours: bool = False           # 盘前/盘后下单
    hk_max_gross_exposure_pct: float = Field(100.0, ge=1, le=400)
    max_daily_orders: int = Field(0, ge=0, le=2000)      # 0 = 不限制
    max_orders_per_minute: int = Field(0, ge=0, le=60)   # 0 = 不限制；IBKR 硬限 50 msg/s


class KillSwitchRequest(BaseModel):
    engaged: bool
    nonce: str = ""
    password: str = ""


class LiveUnlockRequest(BaseModel):
    confirm_phrase: str
    password: str
    enable: bool = True


# ------------------------------------------------------------------
# 回测
# ------------------------------------------------------------------
class BacktestRequest(BaseModel):
    strategy_key: str
    params: dict[str, Any] = {}
    rule: dict[str, Any] | None = None
    code: str = ""
    symbols: list[str] = Field(min_length=1, max_length=30)
    start: str = "2019-01-01"
    end: str | None = None
    interval: Literal["1d", "1wk", "1h", "30m", "15m", "5m"] = "1d"
    initial_capital: float = Field(100_000.0, gt=0)
    commission_bps: float = Field(1.0, ge=0, le=100)     # 单边万分之
    slippage_bps: float = Field(2.0, ge=0, le=100)
    fee_model: Literal["bps", "market"] = "bps"          # market = 分项真实费用（US SEC/TAF、HK 印花税…）
    benchmark: str = "SPY"
    risk: dict[str, Any] = {}
    label: str = ""
    data_source: str = "auto"                            # auto | ibkr

    @field_validator("symbols")
    @classmethod
    def _norm(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]


class OptimizeRequest(BaseModel):
    strategy_key: str
    param_grid: dict[str, list[Any]]
    symbols: list[str] = Field(min_length=1, max_length=10)
    start: str = "2019-01-01"
    end: str | None = None
    interval: Literal["1d", "1wk", "1h", "30m", "15m", "5m"] = "1d"
    initial_capital: float = Field(100_000.0, gt=0)
    objective: Literal["sharpe", "calmar", "return", "profit_factor", "sortino"] = "sharpe"
    max_combos: int = Field(200, ge=1, le=2000)
    data_source: str = "auto"


class CompareItem(BaseModel):
    label: str = ""
    strategy_key: str
    params: dict[str, Any] = {}
    rule: dict[str, Any] | None = None
    code: str = ""
    symbols: list[str] = Field(min_length=1, max_length=20)
    risk: dict[str, Any] = {}


class CompareRequest(BaseModel):
    items: list[CompareItem] = Field(min_length=2, max_length=8)
    start: str = "2019-01-01"
    end: str | None = None
    interval: Literal["1d", "1wk", "1h", "30m", "15m", "5m"] = "1d"
    initial_capital: float = Field(100_000.0, gt=0)
    commission_bps: float = Field(1.0, ge=0, le=100)
    slippage_bps: float = Field(2.0, ge=0, le=100)
    fee_model: Literal["bps", "market"] = "bps"
    benchmark: str = "SPY"
    data_source: str = "auto"


class FactorICRequest(BaseModel):
    """因子 IC 诊断请求（离线研究工具，允许使用未来收益对账）。"""
    strategy_key: str = "multi_factor_score"
    symbols: list[str] = Field(min_length=2, max_length=50)
    start: str = ""
    end: str | None = None
    interval: Literal["1d", "1wk", "1h", "30m", "15m", "5m"] = "1d"
    params: dict[str, Any] = {}
    horizon: int = Field(21, ge=1, le=252)
    min_names: int = Field(4, ge=2, le=20)


# ------------------------------------------------------------------
# 组合优化（均值方差 / 风险平价）
# ------------------------------------------------------------------
class PortfolioOptimizeRequest(BaseModel):
    """组合优化请求。与参数寻优（OptimizeRequest）不同，这里求的是权重，不是策略参数。"""

    symbols: list[str] = Field(min_length=2, max_length=30)
    start: str = "2019-01-01"
    end: str | None = None
    interval: Literal["1d", "1wk"] = "1d"
    objective: Literal[
        "max_sharpe", "min_variance", "max_return", "risk_parity",
        "inverse_vol", "equal_weight",
    ] = "max_sharpe"
    cov_method: Literal["ledoit_wolf", "sample", "ewma"] = "ledoit_wolf"
    return_method: Literal["shrunk", "mean", "ewma"] = "shrunk"
    risk_free_rate: float = Field(0.0, ge=-0.5, le=1.0)
    periods_per_year: int = Field(252, ge=1, le=8760)
    max_weight: float = Field(0.35, gt=0, le=1.0)
    min_weight: float = Field(0.0, ge=0, le=1.0)
    max_gross: float = Field(1.0, gt=0, le=4.0)
    long_only: bool = True
    corr_threshold: float = Field(0.85, ge=0.0, le=1.0)
    max_cluster_weight: float = Field(0.5, gt=0, le=1.0)
    risk_budget: dict[str, float] = {}
    include_frontier: bool = True
    data_source: str = "auto"

    @field_validator("symbols")
    @classmethod
    def _norm(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for s in v:
            u = s.strip().upper()
            if u and u not in out:
                out.append(u)
        return out


class OptimizeSaveRequest(BaseModel):
    """把一次优化结果落成策略配置（kind=code 的权重再平衡策略）。"""

    name: str = Field(min_length=1, max_length=120)
    symbols: list[str] = []
    weights: dict[str, float]
    objective: str = "max_sharpe"
    notes: str = ""


# ------------------------------------------------------------------
# 交易
# ------------------------------------------------------------------
class OrderRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    order_type: Literal["MKT", "LMT", "STP", "STP_LMT"] = "MKT"
    limit_price: float | None = None
    stop_price: float | None = None
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    tif: Literal["DAY", "GTC", "IOC", "FOK"] = "DAY"
    reason: str = ""
    confirm: bool = False


class ModeSwitchRequest(BaseModel):
    mode: Literal["paper", "live", "simulated"]
    password: str = ""


class EngineStartRequest(BaseModel):
    strategy_id: int
    mode: Literal["paper", "simulated", "live"] = "paper"
    # 信号层周期（秒）：重算目标权重的频率。允许 1 秒级，不再强制 ≥10s。
    interval_sec: float = Field(60, ge=1, le=3600)
    # 执行层周期（秒）：读内存行情/跑风控/下单的频率。允许亚秒级。
    exec_interval_sec: float = Field(
        1.0, ge=0.05, le=60,
        description="执行层轮询周期；exec_mode=event 时作为无行情时的兜底重评间隔",
    )
    # event：有新 tick 就立即执行（毫秒级响应）；poll：按 exec_interval_sec 固定节奏
    exec_mode: Literal["event", "poll"] = "event"
    place_protective: bool = True    # 实盘时为持仓挂交易所侧保护性止损/止盈单


# ------------------------------------------------------------------
# 券商设置
# ------------------------------------------------------------------
class BrokerSettingsIn(BaseModel):
    provider: Literal["simulated", "ibkr"] = "simulated"
    host: str = Field("127.0.0.1", max_length=64)
    port: int = Field(7497, ge=1, le=65535)
    client_id: int = Field(17, ge=0, le=9999)
    account: str = Field("", max_length=64)
    connection_type: Literal["tws", "gateway"] = "tws"
    readonly: bool = True
    # 1=实时 2=冻结 3=延迟 4=延迟冻结；无实时行情订阅时用 3
    market_data_type: Literal[1, 2, 3, 4] = 3
    # 仅使用常规交易时段数据（做日内策略建议保持 True）
    use_rth: bool = True

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        """P2-4：券商地址只允许本机回环。

        IBKR 的 TWS / Gateway 只在本机运行，而 /broker/test 会真的去连接这个
        地址 —— 旧实现允许任意 host，等于给了一个 SSRF 跳板（把连接指向任意
        主机/端口，用于探测内网）。这里收敛到回环地址。
        """
        h = (v or "").strip()
        allowed = {"127.0.0.1", "localhost", "::1"}
        if h not in allowed:
            raise ValueError(
                f"券商地址仅允许本机回环（{' / '.join(sorted(allowed))}），收到：{h!r}"
            )
        return h


# ------------------------------------------------------------------
# AI
# ------------------------------------------------------------------
class AISettingsIn(BaseModel):
    """设置页「AI 分析」卡片的全局配置（state.ai_settings 运行时持久化）。"""
    model: str = Field(..., min_length=1, max_length=120)
    base_url: str | None = Field(None, max_length=300)
    api_key: str | None = Field(None, max_length=300)  # 空/None = 保持现有密钥

    @field_validator("base_url")
    @classmethod
    def _loopback_only(cls, v: str | None) -> str | None:
        """与券商设置同口径：AI 网关地址只允许本机回环（防 SSRF 跳板）。

        WorkBuddy Manager 网关本来就跑在 127.0.0.1；若确有远程网关需求，
        应通过环境变量 QD_AI_BASE_URL 配置并自行承担风险。
        """
        if v is None:
            return v
        h = (v or "").strip()
        if not h:
            return None
        from urllib.parse import urlparse
        host = (urlparse(h if "//" in h else f"http://{h}").hostname or "").lower()
        allowed = {"127.0.0.1", "localhost", "::1"}
        if host not in allowed:
            raise ValueError(
                f"AI 网关地址仅允许本机回环（{' / '.join(sorted(allowed))}），收到主机：{host!r}"
            )
        return h.rstrip("/")


class AnalyzeRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=12)
    horizon: Literal["intraday", "swing", "position"] = "swing"
    question: str = ""
    use_llm: bool = False
    use_intraday: bool = False   # 附带当日分钟级结构（5m VWAP / 开盘区间 / 分钟 RSI）
    model: str = ""              # T-109：多模型名称（QD_AI_EXTRA_MODELS 中定义；空 = 默认）


class ChatRequest(BaseModel):
    message: str
    context_symbols: list[str] = []
    history: list[dict[str, str]] = []
    model: str = ""


class AiAssistRequest(BaseModel):
    """统一 AI 助手请求（AI Task Hub）。

    一个入口覆盖全平台所有 AI 接入点：`task` 选任务，`payload` 传该任务
    需要的原始数据（由前端把**页面上真实的数据**原样带过来，后端只做裁剪与
    校验，避免二次取数导致前后端看到的数据不一致）。
    """

    task: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    model: str = ""            # 空 = 跟随「设置 → AI 分析」的全局模型
    force_local: bool = False  # true = 跳过 LLM，只用规则化兜底（用于「纯本地模式」对照）
