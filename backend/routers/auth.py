"""/auth: 登录 / 登出 / 刷新 / 获取当前用户。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..deps import CurrentUser, DBSession, client_ip
from ..models import AuditLog, User
from ..schemas import LoginIn, RefreshIn, TokenOut, UserOut
from ..security import (
    decode_or_raise,
    issue_access_token,
    issue_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# 内存限流：同 IP 10min 5 次失败锁 15min
import time

_FAIL_STATE: dict[str, tuple[float, int, float]] = {}


def _check_rate(ip: str) -> int | None:
    now = time.time()
    state = _FAIL_STATE.get(ip)
    if state:
        locked_until, _count, _win = state
        if locked_until and locked_until > now:
            return int(locked_until - now)
    return None


def _record_fail(ip: str) -> None:
    now = time.time()
    prev = _FAIL_STATE.get(ip)
    if not prev or now - prev[2] > 600:
        _FAIL_STATE[ip] = (0.0, 1, now)
        return
    new_count = prev[1] + 1
    if new_count >= 5:
        _FAIL_STATE[ip] = (now + 900, new_count, prev[2])
    else:
        _FAIL_STATE[ip] = (0.0, new_count, prev[2])


def _clear_fail(ip: str) -> None:
    _FAIL_STATE.pop(ip, None)


def _issue_tokens(user: User) -> TokenOut:
    role_name = user.role.name if user.role else None
    perms = [p.code for p in user.role.permissions] if user.role else []
    access, ttl = issue_access_token(user.id, role_name, perms)
    refresh, _ = issue_refresh_token(user.id)
    return TokenOut(access_token=access, refresh_token=refresh, expires_in=ttl)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: DBSession) -> TokenOut:
    ip = client_ip(request)
    wait = _check_rate(ip)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "retry_after_sec": wait},
        )
    user = db.query(User).filter(User.email == body.email).one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        _record_fail(ip)
        db.add(AuditLog(
            user_id=user.id if user else None,
            action="login_failed",
            resource=body.email,
            ip=ip,
        ))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_inactive")
    _clear_fail(ip)
    user.last_login_at = datetime.now(timezone.utc)
    db.add(AuditLog(user_id=user.id, action="login", ip=ip))
    db.commit()
    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: DBSession) -> TokenOut:
    try:
        payload = decode_or_raise(body.refresh_token, "refresh")
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e
    uid = int(payload.get("sub") or 0)
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_user")
    return _issue_tokens(user)


@router.post("/logout")
def logout(current: CurrentUser, request: Request, db: DBSession) -> dict[str, object]:
    db.add(AuditLog(user_id=current.id, action="logout", ip=client_ip(request)))
    db.commit()
    # JWT 无状态，服务端无法真正失效；客户端应丢弃 token
    return {"ok": True, "note": "client should discard token"}


@router.get("/me", response_model=UserOut)
def me(current: CurrentUser) -> User:
    return current
