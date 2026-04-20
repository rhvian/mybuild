"""ORM 模型：User / Role / Permission / 关联表 / 审计日志（最小）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    permissions: Mapped[list[Permission]] = relationship(
        "Permission", secondary=role_permissions, lazy="selectin"
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped[Role | None] = relationship("Role", lazy="selectin")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


# ===== 预警处置（B5b 业务流）=====

class Alert(Base):
    """预警 —— 由系统规则 / 外部告警源 / 人工录入产生的风险信号。"""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    # 类别：quality / compliance / risk / complaint / other
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)  # high/medium/low
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    # 关联实体（可选）
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # enterprise/staff/tender
    entity_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 状态：open / ack（已受理）/ resolved（已处置）/ dismissed（驳回）
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")

    actions: Mapped[list["AlertAction"]] = relationship(
        "AlertAction", back_populates="alert", cascade="all, delete-orphan", lazy="selectin"
    )


class AlertAction(Base):
    """预警操作历史 —— 每次受理 / 处置 / 评论都留痕。"""
    __tablename__ = "alert_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # ack/resolve/dismiss/comment/reopen
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    alert: Mapped[Alert] = relationship("Alert", back_populates="actions")


# ===== 企业认证申诉（B5c-1）=====

class Appeal(Base):
    """企业对信用评价 / 资质裁定 / 黑名单的申诉。"""
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 申诉主体
    enterprise_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enterprise_name: Mapped[str] = mapped_column(String(256), nullable=False)
    appellant_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # 申诉内容
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)  # credit/qualification/blacklist/other
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence_url: Mapped[str] = mapped_column(String(512), default="")
    # 状态：submitted → under_review → approved / rejected / need_more（补充材料）→ resubmitted
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ===== 项目监管（B5c-2）=====

class ProjectMonitor(Base):
    """对建设项目的监管记录 —— 挂到 tender（通过 entity_key），不复制项目基本信息。"""
    __tablename__ = "project_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tender_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tender_name: Mapped[str] = mapped_column(String(256), nullable=False)
    builder_name: Mapped[str] = mapped_column(String(256), default="")
    risk_level: Mapped[str] = mapped_column(String(16), default="normal", index=True)  # high/medium/low/normal
    supervision_level: Mapped[str] = mapped_column(String(16), default="routine")  # routine/key/priority
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active/suspended/closed
    inspection_count: Mapped[int] = mapped_column(Integer, default=0)
    last_inspection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_inspection_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
