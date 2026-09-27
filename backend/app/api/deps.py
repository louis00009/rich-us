"""API 依赖：认证与限速。"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def client_key(request: Request, username: str = "") -> str:
    """登录限速键。

    P2 安全修复：旧实现把用户名拼进 key —— 攻击者轮换用户名即可绕过
    「8 次失败锁定」。改为**仅按来源 IP 计数**（本地单机应用，NAT 误伤
    可接受；换来的固定性使锁定不可被轮换绕过）。username 参数保留兼容调用方。
    """
    ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"


def require_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供访问令牌", headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期", headers={"WWW-Authenticate": "Bearer"})
    # P2（JWT 撤销）：改密后旧令牌立即失效 —— 比对签发时刻与撤销阈值。
    # AppSetting 单键读，开销可忽略；阈值读取失败不阻塞正常鉴权。
    try:
        from .. import state as appstate

        username = str(payload.get("sub") or "")
        min_iat = float(appstate.get_setting(f"min_iat:{username}", "0") or 0)
        if min_iat and int(payload.get("iat") or 0) < min_iat:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已被撤销（口令已更改），请重新登录")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
DbSession = Annotated[Session, Depends(get_db)]
