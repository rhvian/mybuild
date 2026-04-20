"""依赖注入：DB session / 当前用户 / 角色权限检查。"""
from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import User
from .security import decode_or_raise


_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DBSession = Annotated[Session, Depends(get_db)]


def _current_user(
    creds: HTTPAuthorizationCredentials | None,
    db: Session,
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing_token")
    try:
        payload = decode_or_raise(creds.credentials, "access")
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e
    user_id = int(payload.get("sub") or 0)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user_not_found")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_inactive")
    return user


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DBSession,
) -> User:
    return _current_user(creds, db)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*names: str):
    def _check(user: CurrentUser) -> User:
        role_name = user.role.name if user.role else None
        if role_name not in names:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"role_required: {', '.join(names)}",
            )
        return user
    return _check


def require_permission(*codes: str):
    def _check(user: CurrentUser) -> User:
        if not user.role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "no_role")
        user_codes = {p.code for p in user.role.permissions}
        missing = [c for c in codes if c not in user_codes]
        if missing:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"permission_required: {', '.join(missing)}",
            )
        return user
    return _check


def client_ip(request: Request) -> str:
    # nginx 反代下先看 X-Forwarded-For
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
