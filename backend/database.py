"""数据库引擎 + ORM Base 类。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


_settings = get_settings()

connect_args = {}
if _settings.database_url.startswith("sqlite"):
    # FastAPI 多线程下 SQLite 需要
    connect_args = {"check_same_thread": False}

engine = create_engine(
    _settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass
