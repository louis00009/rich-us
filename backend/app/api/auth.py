"""认证接口。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Request, status

from .. import state as appstate
from ..database import session_scope
from ..models import User
from ..schemas import ChangePasswordRequest, LoginRequest, SetupRequest, TokenResponse
from ..security import (
    clear_failures,
    create_access_token,
    hash_password,
    is_locked,
    password_strength,
    register_failure,
    verify_password,
)
from .deps import CurrentUser, client_key

router = APIRouter(prefix="/auth", tags=["认证"])


@router.get("/status")
def auth_status() -> dict:
    from ..database import SessionLocal

    with SessionLocal() as s:
        initialized = s.query(User).count() > 0
    return {"initialized": initialized}


@router.post("/setup", response_model=TokenResponse)
def setup(payload: SetupRequest, request: Request) -> TokenResponse:
    from ..database import SessionLocal

    with SessionLocal() as s:
        if s.query(User).count() > 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "系统已初始化，请直接登录")
    ok, msg = password_strength(payload.password)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)

    with session_scope() as s:
        s.add(User(username=payload.username.strip(), password_hash=hash_password(payload.password)))
    appstate.log("user_setup", "INFO", f"创建管理员账户 {payload.username}",
                 actor=payload.username, ip=request.client.host if request.client else "")

    token, exp = create_access_token(payload.username)
    return TokenResponse(access_token=token, expires_at=exp.isoformat(), username=payload.username)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    key = client_key(request, payload.username)
    locked, remain = is_locked(key)
    if locked:
        appstate.log("login_locked", "WARN", f"登录锁定中，剩余 {remain}s", actor=payload.username)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"尝试次数过多，请 {remain} 秒后再试")

    from ..database import SessionLocal

    with SessionLocal() as s:
        user = s.query(User).filter(User.username == payload.username.strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        register_failure(key)
        appstate.log("login_failed", "WARN", "登录失败（用户名或口令错误）",
                     actor=payload.username, ip=request.client.host if request.client else "")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或口令错误")

    clear_failures(key)
    with session_scope() as s:
        u = s.query(User).filter(User.id == user.id).first()
        if u:
            u.last_login = dt.datetime.now(dt.timezone.utc)
    appstate.log("login_ok", "INFO", "登录成功", actor=user.username,
                 ip=request.client.host if request.client else "")
    token, exp = create_access_token(user.username)
    return TokenResponse(access_token=token, expires_at=exp.isoformat(), username=user.username)


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {
        "username": user.username,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


@router.post("/logout")
def logout(user: CurrentUser) -> dict:
    appstate.log("logout", "INFO", "用户登出", actor=user.username)
    return {"ok": True, "message": "请在前端清除本地令牌"}


@router.post("/password")
def change_password(payload: ChangePasswordRequest, request: Request, user: CurrentUser) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        appstate.log("password_change_failed", "WARN", "旧口令校验失败", actor=user.username)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前口令不正确")
    ok, msg = password_strength(payload.new_password)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)
    with session_scope() as s:
        u = s.query(User).filter(User.id == user.id).first()
        if u:
            u.password_hash = hash_password(payload.new_password)
    # P2（JWT 撤销）：改密后撤销该用户已签发的所有旧令牌 ——
    # 旧实现旧 JWT 仍可用到 12h TTL 期满。require_user 会对比 iat 与该阈值。
    import time as _t

    appstate.set_setting(f"min_iat:{user.username}", str(int(_t.time())))
    appstate.log("password_changed", "INFO", "口令已更新（旧令牌已全部撤销）", actor=user.username)
    return {"ok": True, "message": "口令已更新，旧登录已失效，请重新登录"}
