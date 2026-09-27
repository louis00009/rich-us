"""
QuantDesk for IBKR — 全局配置
================================
设计原则:
  1. 默认只绑定 127.0.0.1，绝不对外暴露。
  2. 所有密钥落盘在 runtime/.secret (0600)，绝不进代码库。
  3. 实盘交易需要「环境变量 + 运行时解锁」双重开关，缺一不可。
"""
from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ------------------------------------------------------------------
# 路径
# ------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent          # backend/
APP_DIR = BACKEND_DIR / "app"
RUNTIME_DIR = Path(os.environ.get("QD_HOME", BACKEND_DIR / "runtime")).resolve()
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = RUNTIME_DIR / "quantdesk.db"
SECRET_PATH = RUNTIME_DIR / ".secret"
CACHE_DIR = RUNTIME_DIR / "cache"
LOG_DIR = RUNTIME_DIR / "logs"
STRATEGY_DIR = RUNTIME_DIR / "strategies"
for _d in (CACHE_DIR, LOG_DIR, STRATEGY_DIR):
    _d.mkdir(parents=True, exist_ok=True)

FRONTEND_DIST = (BACKEND_DIR.parent / "frontend" / "dist").resolve()


def _load_dotenv() -> None:
    """极简 .env 加载器（避免额外依赖）。已存在的环境变量优先。"""
    for candidate in (RUNTIME_DIR / ".env", BACKEND_DIR / ".env"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("'\"")
            os.environ.setdefault(key, val)


_load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on", "y"}


# ------------------------------------------------------------------
# 不可变设置
# ------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    app_name: str = "QuantDesk for IBKR"
    version: str = "1.0.0"
    api_prefix: str = "/api"

    # 网络 —— 默认仅本机
    host: str = os.environ.get("QD_HOST", "127.0.0.1")
    port: int = int(os.environ.get("QD_PORT", "8787"))
    cors_origins: tuple[str, ...] = tuple(
        o.strip()
        for o in os.environ.get(
            "QD_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8787,http://127.0.0.1:8787",
        ).split(",")
        if o.strip()
    )

    # 认证
    access_token_ttl_min: int = int(os.environ.get("QD_TOKEN_TTL_MIN", "720"))   # 12h
    login_max_attempts: int = int(os.environ.get("QD_LOGIN_MAX_ATTEMPTS", "8"))
    login_lockout_sec: int = int(os.environ.get("QD_LOGIN_LOCKOUT_SEC", "300"))

    # 实盘资金安全 —— 第一道锁：环境变量
    allow_live_trading: bool = field(default_factory=lambda: _env_bool("QD_ALLOW_LIVE_TRADING", False))

    # IBKR 默认端口 (TWS 7497/7496, Gateway 4002/4001)
    ibkr_paper_tws_port: int = int(os.environ.get("QD_IBKR_PAPER_TWS", "7497"))
    ibkr_live_tws_port: int = int(os.environ.get("QD_IBKR_LIVE_TWS", "7496"))
    ibkr_paper_gw_port: int = int(os.environ.get("QD_IBKR_PAPER_GW", "4002"))
    ibkr_live_gw_port: int = int(os.environ.get("QD_IBKR_LIVE_GW", "4001"))
    ibkr_default_host: str = os.environ.get("QD_IBKR_HOST", "127.0.0.1")
    ibkr_client_id: int = int(os.environ.get("QD_IBKR_CLIENT_ID", "17"))
    # 行情类型：1=实时 2=冻结 3=延迟 4=延迟冻结（无实时订阅时用 3）
    ibkr_market_data_type: int = int(os.environ.get("QD_IBKR_MD_TYPE", "3"))

    # 市场数据
    data_timeout_sec: int = int(os.environ.get("QD_DATA_TIMEOUT", "20"))
    cache_ttl_sec: int = int(os.environ.get("QD_CACHE_TTL", "900"))

    # AI 分析师（可选，未配置则使用内置本地量化引擎）
    ai_base_url: str = os.environ.get("QD_AI_BASE_URL", "")
    ai_api_key: str = os.environ.get("QD_AI_API_KEY", "")
    ai_model: str = os.environ.get("QD_AI_MODEL", "gpt-4o-mini")
    # T-109 多模型：格式 "name|base_url|api_key|model;name2|..."（分号分隔多组）
    ai_extra_models: str = os.environ.get("QD_AI_EXTRA_MODELS", "")

    # 新闻与数据源扩展
    finnhub_api_key: str = os.environ.get("FINNHUB_API_KEY", "")
    news_ttl_sec: int = int(os.environ.get("QD_NEWS_TTL", "300"))          # 新闻抓取间隔
    news_scan_symbols: int = int(os.environ.get("QD_NEWS_SCAN_SYMBOLS", "12"))  # 单轮扫描标的上限
    rankings_ttl_sec: int = int(os.environ.get("QD_RANKINGS_TTL", "600"))  # 榜单行情缓存
    alert_scan_cooldown_sec: int = int(os.environ.get("QD_ALERT_COOLDOWN", "90"))

    # 引擎
    engine_tick_sec: int = int(os.environ.get("QD_ENGINE_TICK", "30"))


settings = Settings()


# ------------------------------------------------------------------
# 密钥材料：Fernet key + JWT secret，首次启动自动生成
# ------------------------------------------------------------------
def _load_or_create_secret() -> dict[str, str]:
    if SECRET_PATH.exists():
        data: dict[str, str] = {}
        for line in SECRET_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip()
        if data.get("fernet_key") and data.get("jwt_secret"):
            return data

    from cryptography.fernet import Fernet

    data = {
        "fernet_key": Fernet.generate_key().decode(),
        "jwt_secret": secrets.token_urlsafe(64),
    }
    SECRET_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in data.items()) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(SECRET_PATH, 0o600)          # POSIX
    except OSError:
        pass
    if sys.platform == "win32":
        try:                                   # Windows: 仅当前用户可读
            import subprocess

            subprocess.run(
                ["icacls", str(SECRET_PATH), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME')}:F"],
                capture_output=True, check=False, shell=False,
            )
        except Exception:
            pass
    return data


SECRETS = _load_or_create_secret()
FERNET_KEY = SECRETS["fernet_key"]
JWT_SECRET = SECRETS["jwt_secret"]
JWT_ALGORITHM = "HS256"

# 实盘确认短语 —— 解锁时必须逐字输入
LIVE_CONFIRM_PHRASE = "I UNDERSTAND THE RISK"
