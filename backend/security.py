"""bcrypt 密码 + JWT 工具。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import get_settings

_settings = get_settings()
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


def _issue_jwt(sub: str, scopes: list[str], ttl_seconds: int, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "type": token_type,
        "scopes": scopes,
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def issue_access_token(user_id: int, role: str | None, permissions: list[str]) -> tuple[str, int]:
    ttl = _settings.access_token_ttl_min * 60
    scopes = [role] if role else []
    scopes += [f"perm:{p}" for p in permissions]
    return _issue_jwt(str(user_id), scopes, ttl, "access"), ttl


def issue_refresh_token(user_id: int) -> tuple[str, int]:
    ttl = _settings.refresh_token_ttl_days * 86400
    return _issue_jwt(str(user_id), [], ttl, "refresh"), ttl


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])


def decode_or_raise(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = decode_token(token)
    except JWTError as e:
        raise ValueError(f"invalid_token: {e}") from e
    if payload.get("type") != expected_type:
        raise ValueError(f"wrong_token_type: expect {expected_type}, got {payload.get('type')}")
    return payload
