"""/users: 用户 CRUD（仅 admin 或带 user:* 权限）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ..deps import DBSession, CurrentUser, client_ip, require_permission
from ..models import AuditLog, Role, User
from ..schemas import UserCreate, UserListOut, UserOut, UserUpdate
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListOut, dependencies=[Depends(require_permission("user:read"))])
def list_users(
    db: DBSession,
    q: str = Query("", description="按 email 或 name 模糊"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> UserListOut:
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.email.ilike(like)) | (User.name.ilike(like)))
    total = query.count()
    rows = query.order_by(User.id.desc()).offset((page - 1) * size).limit(size).all()
    return UserListOut(
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size if size else 1,
        items=[UserOut.model_validate(u) for u in rows],
    )


@router.post("", response_model=UserOut, status_code=201, dependencies=[Depends(require_permission("user:write"))])
def create_user(
    body: UserCreate,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> User:
    if db.query(User).filter(User.email == body.email).one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "email_exists")
    role = None
    if body.role_id is not None:
        role = db.get(Role, body.role_id)
        if not role:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_role_id")
    user = User(
        email=body.email,
        name=body.name or "",
        hashed_password=hash_password(body.password),
        is_active=True,
        role_id=body.role_id,
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(
        user_id=current.id,
        action="user_create",
        resource=f"user:{user.id}",
        ip=client_ip(request),
        detail=body.email,
    ))
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut, dependencies=[Depends(require_permission("user:read"))])
def get_user(user_id: int, db: DBSession) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    return user


@router.patch("/{user_id}", response_model=UserOut, dependencies=[Depends(require_permission("user:write"))])
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    if body.name is not None:
        user.name = body.name
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role_id is not None:
        if body.role_id == 0:
            user.role_id = None
        else:
            role = db.get(Role, body.role_id)
            if not role:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_role_id")
            user.role_id = body.role_id
    if body.password:
        user.hashed_password = hash_password(body.password)
    db.add(AuditLog(
        user_id=current.id,
        action="user_update",
        resource=f"user:{user_id}",
        ip=client_ip(request),
    ))
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204, dependencies=[Depends(require_permission("user:delete"))])
def delete_user(
    user_id: int,
    request: Request,
    db: DBSession,
    current: CurrentUser,
) -> None:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    if user.id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot_delete_self")
    db.delete(user)
    db.add(AuditLog(
        user_id=current.id,
        action="user_delete",
        resource=f"user:{user_id}",
        ip=client_ip(request),
    ))
    db.commit()
