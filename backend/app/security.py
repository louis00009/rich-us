"""
安全模块
=========
- 口令哈希：bcrypt（自适应 cost）
- 会话令牌：JWT (HS256)，无 Cookie → 天然免疫 CSRF
- 敏感字段：Fernet (AES-128-CBC + HMAC) 加密后落库
- 登录限速：内存计数 + 锁定窗口
"""
from __future__ import annotations

import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import FERNET_KEY, JWT_ALGORITHM, JWT_SECRET, settings

_fernet = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)


# ------------------------------------------------------------------
# 口令
# ------------------------------------------------------------------
_BCRYPT_MAX_BYTES = 72    # bcrypt 算法硬上限


def _bcrypt_pw(password: str) -> bytes:
    """显式截断到 bcrypt 的 72 字节上限，hash 与 verify 使用同一口径。

    P0-4：不截断时，口令超过 72 字节（如 25 个中文 ≈ 75 字节）会让
    bcrypt.hashpw 抛 ValueError → 注册/改密直接 500；
    旧版 bcrypt 静默截断生成的哈希在 verify 时又抛异常被吞成 False → 永远登录失败。
    """
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_pw(password), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_pw(password), hashed.encode())
    except (ValueError, TypeError):
        return False


def password_strength(pw: str) -> tuple[bool, str]:
    """最小口令策略：>=10 位，且至少 3 类字符（口令按前 72 字节生效）。"""
    if len(pw) < 10:
        return False, "口令至少需要 10 个字符"
    classes = sum(
        [
            any(c.islower() for c in pw),
            any(c.isupper() for c in pw),
            any(c.isdigit() for c in pw),
            any(not c.isalnum() for c in pw),
        ]
    )
    if classes < 3:
        return False, "口令需包含大写字母、小写字母、数字、符号中的至少三类"
    if len(pw.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        # 不阻止设置，但明确告知生效范围（超过部分会被截断）
        return True, "ok（提示：口令按前 72 字节生效，超出部分不参与校验）"
    return True, "ok"


# ------------------------------------------------------------------
# 凭据加密
# ------------------------------------------------------------------
def encrypt(plain: str) -> str:
    if not plain:
        return ""
    return _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask(secret: str, keep: int = 4) -> str:
    if not secret:
        return ""
    if len(secret) <= keep:
        return "*" * len(secret)
    return "*" * (len(secret) - keep) + secret[-keep:]


# ------------------------------------------------------------------
# JWT
# ------------------------------------------------------------------
def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.access_token_ttl_min)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": "quantdesk",
        **(extra or {}),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), exp


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer="quantdesk")
    except jwt.PyJWTError:
        return None


# ------------------------------------------------------------------
# 登录限速
# ------------------------------------------------------------------
_attempts: dict[str, list[float]] = {}
_ATTEMPT_MAX_KEYS = 4096    # P2：字典有界，防止长期运行/恶意刷 key 撑爆内存


def register_failure(key: str) -> None:
    now = time.time()
    window = now - settings.login_lockout_sec
    if len(_attempts) >= _ATTEMPT_MAX_KEYS:
        # 先清过期键；仍超限则整体重置（本地单机应用，重置代价可接受）
        stale = [k for k, v in _attempts.items() if not v or v[-1] <= window]
        for k in stale:
            _attempts.pop(k, None)
        if len(_attempts) >= _ATTEMPT_MAX_KEYS:
            _attempts.clear()
    hits = [t for t in _attempts.get(key, []) if t > window]
    hits.append(now)
    _attempts[key] = hits


def is_locked(key: str) -> tuple[bool, int]:
    window = time.time() - settings.login_lockout_sec
    hits = [t for t in _attempts.get(key, []) if t > window]
    _attempts[key] = hits
    if len(hits) >= settings.login_max_attempts:
        return True, int(settings.login_lockout_sec - (time.time() - hits[0]))
    return False, 0


def clear_failures(key: str) -> None:
    _attempts.pop(key, None)


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
