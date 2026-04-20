"""首次启动 bootstrap：创建默认角色 + 权限 + admin 用户。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Permission, Role, User
from .security import hash_password


DEFAULT_PERMISSIONS: list[tuple[str, str]] = [
    ("user:read", "查看用户"),
    ("user:write", "创建/修改用户"),
    ("user:delete", "删除用户"),
    ("role:read", "查看角色"),
    ("role:write", "创建/修改角色"),
    ("alert:read", "查看预警"),
    ("alert:write", "处置预警"),
    ("ticket:read", "查看工单"),
    ("ticket:write", "创建/审批/关闭工单"),
    ("audit:read", "查看审计日志"),
    ("collect:read", "查看采集状态"),
    ("collect:write", "启停采集"),
]


DEFAULT_ROLES: dict[str, list[str]] = {
    "admin": [code for code, _ in DEFAULT_PERMISSIONS],
    "auditor": ["user:read", "alert:read", "alert:write", "ticket:read", "ticket:write", "audit:read", "collect:read"],
    "gov": ["alert:read", "ticket:read", "collect:read"],
    "business": ["user:read"],
    "guest": [],
}


def ensure_permissions(db: Session) -> dict[str, Permission]:
    existing = {p.code: p for p in db.query(Permission).all()}
    for code, desc in DEFAULT_PERMISSIONS:
        if code not in existing:
            p = Permission(code=code, description=desc)
            db.add(p)
            existing[code] = p
    db.flush()
    return existing


def ensure_roles(db: Session, perms: dict[str, Permission]) -> dict[str, Role]:
    existing = {r.name: r for r in db.query(Role).all()}
    for name, codes in DEFAULT_ROLES.items():
        if name not in existing:
            r = Role(name=name, description=f"系统内置: {name}")
            r.permissions = [perms[c] for c in codes if c in perms]
            db.add(r)
            existing[name] = r
        else:
            # 补齐缺失权限（已有的不动）
            current_codes = {p.code for p in existing[name].permissions}
            need = [perms[c] for c in codes if c in perms and c not in current_codes]
            if need:
                existing[name].permissions = list(existing[name].permissions) + need
    db.flush()
    return existing


def ensure_admin(db: Session, roles: dict[str, Role]) -> None:
    s = get_settings()
    admin_role = roles.get("admin")
    user = db.query(User).filter(User.email == s.bootstrap_admin_email).one_or_none()
    if user:
        return
    user = User(
        email=s.bootstrap_admin_email,
        name="平台管理员",
        hashed_password=hash_password(s.bootstrap_admin_password),
        is_active=True,
        role_id=admin_role.id if admin_role else None,
    )
    db.add(user)
    db.flush()


def bootstrap(db: Session) -> None:
    perms = ensure_permissions(db)
    roles = ensure_roles(db, perms)
    ensure_admin(db, roles)
    db.commit()
