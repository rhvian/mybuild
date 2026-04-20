"""/roles: 角色列表（供前端选择）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import DBSession, require_permission
from ..models import Role
from ..schemas import RoleDetail

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleDetail], dependencies=[Depends(require_permission("role:read"))])
def list_roles(db: DBSession) -> list[RoleDetail]:
    roles = db.query(Role).order_by(Role.id.asc()).all()
    return [
        RoleDetail(
            id=r.id,
            name=r.name,
            description=r.description,
            permissions=[p.code for p in r.permissions],
        )
        for r in roles
    ]
