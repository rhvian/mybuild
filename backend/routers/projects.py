"""/projects: 项目监管（B5c-2）。

核心理念：ProjectMonitor 不复制 tender 基本信息，只挂扣一个 tender_key，
记录监管等级 / 风险 / 巡检次数 + 最近一次巡检备注。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func

from ..deps import CurrentUser, DBSession, client_ip, require_permission
from ..models import AuditLog, ProjectMonitor
from ..schemas import (
    InspectionIn,
    ProjectMonitorCreate,
    ProjectMonitorListOut,
    ProjectMonitorOut,
    ProjectMonitorUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectMonitorListOut, dependencies=[Depends(require_permission("project:read"))])
def list_projects(
    db: DBSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    risk: str | None = None,
    supervision: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    q: str = "",
) -> ProjectMonitorListOut:
    query = db.query(ProjectMonitor)
    if risk:
        query = query.filter(ProjectMonitor.risk_level == risk)
    if supervision:
        query = query.filter(ProjectMonitor.supervision_level == supervision)
    if status_filter:
        query = query.filter(ProjectMonitor.status == status_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (ProjectMonitor.tender_name.ilike(like))
            | (ProjectMonitor.tender_key.ilike(like))
            | (ProjectMonitor.builder_name.ilike(like))
        )
    total = query.count()
    rows = query.order_by(ProjectMonitor.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    counts = dict(db.query(ProjectMonitor.risk_level, func.count(ProjectMonitor.id)).group_by(ProjectMonitor.risk_level).all())
    for r in ("high", "medium", "low", "normal"):
        counts.setdefault(r, 0)
    return ProjectMonitorListOut(
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size if size else 1,
        items=[ProjectMonitorOut.model_validate(p) for p in rows],
        counts_by_risk={k: int(v) for k, v in counts.items()},
    )


@router.post("", response_model=ProjectMonitorOut, status_code=201, dependencies=[Depends(require_permission("project:write"))])
def create_project(
    body: ProjectMonitorCreate,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> ProjectMonitor:
    # 同一 tender_key 只允许一条监管记录
    exist = db.query(ProjectMonitor).filter(ProjectMonitor.tender_key == body.tender_key).one_or_none()
    if exist:
        raise HTTPException(409, {"error": "already_exists", "id": exist.id})
    p = ProjectMonitor(
        tender_key=body.tender_key,
        tender_name=body.tender_name,
        builder_name=body.builder_name,
        risk_level=body.risk_level,
        supervision_level=body.supervision_level,
        created_by=current.id,
    )
    db.add(p)
    db.flush()
    db.add(AuditLog(user_id=current.id, action="project_monitor_create", resource=f"project:{p.id}", ip=client_ip(request)))
    db.commit()
    db.refresh(p)
    return p


@router.get("/{pid}", response_model=ProjectMonitorOut, dependencies=[Depends(require_permission("project:read"))])
def get_project(pid: int, db: DBSession) -> ProjectMonitor:
    p = db.get(ProjectMonitor, pid)
    if not p:
        raise HTTPException(404, "project_not_found")
    return p


@router.patch("/{pid}", response_model=ProjectMonitorOut, dependencies=[Depends(require_permission("project:write"))])
def update_project(
    pid: int,
    body: ProjectMonitorUpdate,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> ProjectMonitor:
    p = db.get(ProjectMonitor, pid)
    if not p:
        raise HTTPException(404, "project_not_found")
    if body.risk_level is not None:
        p.risk_level = body.risk_level
    if body.supervision_level is not None:
        p.supervision_level = body.supervision_level
    if body.status is not None:
        p.status = body.status
    db.add(AuditLog(user_id=current.id, action="project_monitor_update", resource=f"project:{pid}", ip=client_ip(request)))
    db.commit()
    db.refresh(p)
    return p


@router.post("/{pid}/inspection", response_model=ProjectMonitorOut, dependencies=[Depends(require_permission("project:write"))])
def add_inspection(
    pid: int,
    body: InspectionIn,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> ProjectMonitor:
    p = db.get(ProjectMonitor, pid)
    if not p:
        raise HTTPException(404, "project_not_found")
    p.inspection_count += 1
    p.last_inspection_at = datetime.now(timezone.utc)
    p.last_inspection_note = body.note
    db.add(AuditLog(user_id=current.id, action="project_inspection", resource=f"project:{pid}", ip=client_ip(request), detail=body.note[:200]))
    db.commit()
    db.refresh(p)
    return p
