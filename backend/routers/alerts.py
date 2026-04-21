"""/alerts: 预警处置业务流（B5b）。

状态机：
  open -> ack -> resolved | dismissed
  resolved/dismissed -> reopen -> ack
comment 不改变 status。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func

from ..deps import CurrentUser, DBSession, client_ip, require_permission
from ..models import Alert, AlertAction, AuditLog
from ..schemas import AlertActionIn, AlertCreate, AlertDetailOut, AlertListOut, AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


ALLOWED_CATEGORIES = {"quality", "compliance", "risk", "complaint", "other"}
ALLOWED_STATUS = {"open", "ack", "resolved", "dismissed"}

# 状态机：当前 status -> 允许的动作
_TRANSITIONS: dict[str, set[str]] = {
    "open": {"ack", "resolve", "dismiss", "comment"},
    "ack": {"resolve", "dismiss", "comment"},
    "resolved": {"reopen", "comment"},
    "dismissed": {"reopen", "comment"},
}


@router.get("", response_model=AlertListOut, dependencies=[Depends(require_permission("alert:read"))])
def list_alerts(
    db: DBSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = None,
    category: str | None = None,
    q: str = "",
) -> AlertListOut:
    query = db.query(Alert)
    if status_filter:
        if status_filter not in ALLOWED_STATUS:
            raise HTTPException(400, "invalid_status")
        query = query.filter(Alert.status == status_filter)
    if severity:
        query = query.filter(Alert.severity == severity)
    if category:
        query = query.filter(Alert.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Alert.title.ilike(like))
            | (Alert.entity_name.ilike(like))
            | (Alert.entity_key.ilike(like))
        )

    total = query.count()
    rows = (
        query.order_by(Alert.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    # 各状态计数（不受 status 过滤影响）
    counts_by_status = dict(
        db.query(Alert.status, func.count(Alert.id)).group_by(Alert.status).all()
    )
    for s in ALLOWED_STATUS:
        counts_by_status.setdefault(s, 0)

    return AlertListOut(
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size if size else 1,
        items=[AlertOut.model_validate(a) for a in rows],
        counts_by_status={k: int(v) for k, v in counts_by_status.items()},
    )


@router.post("", response_model=AlertDetailOut, status_code=201, dependencies=[Depends(require_permission("alert:write"))])
def create_alert(
    body: AlertCreate,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> Alert:
    if body.category not in ALLOWED_CATEGORIES:
        raise HTTPException(400, f"invalid_category: {body.category}")
    alert = Alert(
        source=body.source,
        category=body.category,
        severity=body.severity,
        title=body.title,
        detail=body.detail,
        entity_type=body.entity_type,
        entity_key=body.entity_key,
        entity_name=body.entity_name,
        status="open",
        created_by=current.id,
    )
    db.add(alert)
    db.flush()
    db.add(AlertAction(
        alert_id=alert.id,
        actor_id=current.id,
        action="create",
        note=f"manually created ({body.source})",
    ))
    db.add(AuditLog(
        user_id=current.id,
        action="alert_create",
        resource=f"alert:{alert.id}",
        ip=client_ip(request),
    ))
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/{alert_id}", response_model=AlertDetailOut, dependencies=[Depends(require_permission("alert:read"))])
def get_alert(alert_id: int, db: DBSession) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "alert_not_found")
    return alert


@router.post("/{alert_id}/action", response_model=AlertDetailOut, dependencies=[Depends(require_permission("alert:write"))])
def post_action(
    alert_id: int,
    body: AlertActionIn,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "alert_not_found")

    allowed = _TRANSITIONS.get(alert.status, set())
    if body.action not in allowed:
        raise HTTPException(
            409,
            detail={
                "error": "invalid_transition",
                "current_status": alert.status,
                "allowed_actions": sorted(allowed),
            },
        )

    now = datetime.now(timezone.utc)
    if body.action == "ack":
        alert.status = "ack"
        alert.assignee_id = current.id
    elif body.action == "resolve":
        alert.status = "resolved"
        alert.resolved_at = now
        alert.resolution_note = body.note
        if not alert.assignee_id:
            alert.assignee_id = current.id
    elif body.action == "dismiss":
        alert.status = "dismissed"
        alert.resolved_at = now
        alert.resolution_note = body.note
        if not alert.assignee_id:
            alert.assignee_id = current.id
    elif body.action == "reopen":
        alert.status = "open"
        alert.resolved_at = None
        alert.resolution_note = ""
    # comment: 不改状态

    db.add(AlertAction(
        alert_id=alert.id,
        actor_id=current.id,
        action=body.action,
        note=body.note,
    ))
    db.add(AuditLog(
        user_id=current.id,
        action=f"alert_{body.action}",
        resource=f"alert:{alert.id}",
        ip=client_ip(request),
    ))
    db.commit()
    db.refresh(alert)
    return alert
