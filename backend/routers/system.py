"""/system: 健康 / 版本。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from ..deps import DBSession
from ..schemas import HealthOut

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthOut)
def health(db: DBSession) -> HealthOut:
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return HealthOut(
        status="ok" if db_ok else "degraded",
        db=db_ok,
        ts=datetime.now(timezone.utc),
    )
