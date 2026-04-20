"""FastAPI 入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .bootstrap import bootstrap
from .config import get_settings
from .database import Base, SessionLocal, engine
from .routers import alerts, auth, roles, system, users


logger = logging.getLogger("mybuild.backend")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 首次启动：建表 + bootstrap admin/role/permission
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        bootstrap(db)
    logger.info("backend startup complete")
    yield


_settings = get_settings()

app = FastAPI(
    title="mybuild L2 backend",
    description="用户/角色/权限 + JWT 认证 + 业务 API（与 L1 control_server 并行）。",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(alerts.router)
app.include_router(system.router)


@app.get("/", tags=["meta"])
def root() -> dict[str, object]:
    return {
        "name": "mybuild L2 backend",
        "version": app.version,
        "docs": "/docs",
        "endpoints": sorted(
            r.path for r in app.routes if hasattr(r, "path") and r.path.startswith(("/auth", "/users", "/roles", "/alerts", "/system"))
        ),
    }
