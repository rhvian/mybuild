"""/appeals: 企业认证申诉（B5c-1）。

状态机：
  submitted → under_review（审核员 start_review 后）
  under_review → approved | rejected | need_more
  need_more → under_review（重新提交补充材料）
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func

from ..deps import CurrentUser, DBSession, client_ip, require_permission
from ..models import Appeal, AuditLog
from ..schemas import AppealCreate, AppealListOut, AppealOut, AppealReviewIn

router = APIRouter(prefix="/appeals", tags=["appeals"])


_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"start_review"},
    "under_review": {"approve", "reject", "need_more"},
    "need_more": {"start_review"},
    "approved": set(),
    "rejected": set(),
}


@router.get("", response_model=AppealListOut, dependencies=[Depends(require_permission("appeal:review"))])
def list_appeals(
    db: DBSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = None,
    q: str = "",
) -> AppealListOut:
    query = db.query(Appeal)
    if status_filter:
        query = query.filter(Appeal.status == status_filter)
    if category:
        query = query.filter(Appeal.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Appeal.title.ilike(like))
            | (Appeal.enterprise_name.ilike(like))
            | (Appeal.enterprise_key.ilike(like))
        )
    total = query.count()
    rows = query.order_by(Appeal.created_at.desc()).offset((page - 1) * size).limit(size).all()
    counts = dict(db.query(Appeal.status, func.count(Appeal.id)).group_by(Appeal.status).all())
    for s in ("submitted", "under_review", "need_more", "approved", "rejected"):
        counts.setdefault(s, 0)
    return AppealListOut(
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size if size else 1,
        items=[AppealOut.model_validate(a) for a in rows],
        counts_by_status={k: int(v) for k, v in counts.items()},
    )


@router.post("", response_model=AppealOut, status_code=201, dependencies=[Depends(require_permission("appeal:submit"))])
def submit_appeal(
    body: AppealCreate,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> Appeal:
    appeal = Appeal(
        enterprise_key=body.enterprise_key,
        enterprise_name=body.enterprise_name,
        appellant_user_id=current.id,
        category=body.category,
        title=body.title,
        detail=body.detail,
        evidence_url=body.evidence_url,
        status="submitted",
    )
    db.add(appeal)
    db.flush()
    db.add(AuditLog(
        user_id=current.id,
        action="appeal_submit",
        resource=f"appeal:{appeal.id}",
        ip=client_ip(request),
    ))
    db.commit()
    db.refresh(appeal)
    return appeal


@router.get("/{appeal_id}", response_model=AppealOut)
def get_appeal(appeal_id: int, db: DBSession, current: CurrentUser) -> Appeal:
    appeal = db.get(Appeal, appeal_id)
    if not appeal:
        raise HTTPException(404, "appeal_not_found")
    # 申诉人本人可看自己的；否则要 appeal:review
    if appeal.appellant_user_id != current.id:
        role_perms = {p.code for p in current.role.permissions} if current.role else set()
        if "appeal:review" not in role_perms:
            raise HTTPException(403, "not_your_appeal_or_no_review_permission")
    return appeal


@router.post("/{appeal_id}/review", response_model=AppealOut, dependencies=[Depends(require_permission("appeal:review"))])
def review_appeal(
    appeal_id: int,
    body: AppealReviewIn,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> Appeal:
    appeal = db.get(Appeal, appeal_id)
    if not appeal:
        raise HTTPException(404, "appeal_not_found")
    allowed = _TRANSITIONS.get(appeal.status, set())
    if body.decision not in allowed:
        raise HTTPException(
            409,
            detail={"error": "invalid_transition", "current_status": appeal.status, "allowed": sorted(allowed)},
        )
    now = datetime.now(timezone.utc)
    if body.decision == "start_review":
        appeal.status = "under_review"
        appeal.reviewer_id = current.id
    elif body.decision == "approve":
        appeal.status = "approved"
        appeal.reviewed_at = now
        appeal.review_note = body.note
    elif body.decision == "reject":
        appeal.status = "rejected"
        appeal.reviewed_at = now
        appeal.review_note = body.note
    elif body.decision == "need_more":
        appeal.status = "need_more"
        appeal.review_note = body.note
    db.add(AuditLog(
        user_id=current.id,
        action=f"appeal_{body.decision}",
        resource=f"appeal:{appeal_id}",
        ip=client_ip(request),
    ))
    db.commit()
    db.refresh(appeal)
    return appeal


@router.post("/{appeal_id}/resubmit", response_model=AppealOut, dependencies=[Depends(require_permission("appeal:submit"))])
def resubmit_appeal(
    appeal_id: int,
    body: AppealCreate,  # 复用：允许重新填写 detail + evidence_url
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> Appeal:
    appeal = db.get(Appeal, appeal_id)
    if not appeal:
        raise HTTPException(404, "appeal_not_found")
    if appeal.appellant_user_id != current.id:
        raise HTTPException(403, "not_your_appeal")
    if appeal.status != "need_more":
        raise HTTPException(409, f"invalid_transition_from_{appeal.status}")
    appeal.detail = body.detail
    appeal.evidence_url = body.evidence_url
    appeal.status = "under_review"
    db.add(AuditLog(user_id=current.id, action="appeal_resubmit", resource=f"appeal:{appeal_id}", ip=client_ip(request)))
    db.commit()
    db.refresh(appeal)
    return appeal
