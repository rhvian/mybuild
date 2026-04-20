"""数据库引擎 + ORM Base 类。"""
from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


_settings = get_settings()

connect_args = {}
if _settings.database_url.startswith("sqlite"):
    # FastAPI 多线程下 SQLite 需要
    connect_args = {"check_same_thread": False, "timeout": 15}

engine = create_engine(
    _settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)


# SQLite WAL 模式：读写并发（多 reader + 1 writer 不互相阻塞）
# 加上 synchronous=NORMAL 提速（WAL 下仍然 crash-safe）和 busy_timeout 重试
# 仅对 SQLite 生效；PG 走这里自动 no-op
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):  # pragma: no cover
    if engine.dialect.name != "sqlite":
        return
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.execute("PRAGMA cache_size=-20000")  # 20MB 缓存
    finally:
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass
