"""运行时配置 — 从环境变量读取。"""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "operation.db"
JWT_SECRET_FILE = DATA_DIR / "jwt_secret.key"


def _load_or_create_secret() -> str:
    """首次启动自动生成随机 JWT secret，持久到 backend/data/jwt_secret.key。"""
    if JWT_SECRET_FILE.exists():
        text = JWT_SECRET_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    new = secrets.token_urlsafe(48)
    JWT_SECRET_FILE.write_text(new, encoding="utf-8")
    try:
        JWT_SECRET_FILE.chmod(0o600)
    except Exception:
        pass
    return new


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MYBUILD_", extra="ignore")

    # 数据库
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"

    # JWT
    jwt_secret: str = ""  # 空时 load_or_create_secret 注入
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 7

    # CORS
    cors_origins: list[str] = [
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:8000",
    ]

    # 初始化 bootstrap：首次启动若没有 admin 用户，自动创建
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "build2026"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:
        s.jwt_secret = _load_or_create_secret()
    return s
