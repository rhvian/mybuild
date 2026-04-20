"""Pydantic v2 schemas — request/response shape。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ===== Auth =====

class LoginIn(BaseModel):
    # 登录放宽为 str，避免 .local / .cn 这类 TLD 被 email-validator 拒收
    email: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshIn(BaseModel):
    refresh_token: str


# ===== User =====

class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    name: str
    is_active: bool
    role: Optional[RoleOut] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: EmailStr
    name: str = ""
    password: str = Field(min_length=8, max_length=128)
    role_id: Optional[int] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    role_id: Optional[int] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserListOut(BaseModel):
    total: int
    page: int
    size: int
    pages: int
    items: list[UserOut]


# ===== Role =====

class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    permission_codes: list[str] = Field(default_factory=list)


class RoleDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    permissions: list[str]  # code list


# ===== System =====

class HealthOut(BaseModel):
    status: str
    db: bool
    ts: datetime


# ===== Alert 预警处置 =====

class AlertCreate(BaseModel):
    category: str = Field(default="other", max_length=32)
    severity: str = Field(default="medium", pattern="^(high|medium|low)$")
    title: str = Field(min_length=1, max_length=256)
    detail: str = ""
    entity_type: Optional[str] = Field(default=None, max_length=32)
    entity_key: Optional[str] = Field(default=None, max_length=64)
    entity_name: Optional[str] = Field(default=None, max_length=256)
    source: str = Field(default="manual", max_length=32)


class AlertActionIn(BaseModel):
    action: str = Field(pattern="^(ack|resolve|dismiss|reopen|comment)$")
    note: str = ""


class AlertActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: Optional[int]
    action: str
    note: str
    created_at: datetime


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    category: str
    severity: str
    title: str
    detail: str
    entity_type: Optional[str]
    entity_key: Optional[str]
    entity_name: Optional[str]
    status: str
    assignee_id: Optional[int]
    created_by: Optional[int]
    created_at: datetime
    resolved_at: Optional[datetime]
    resolution_note: str


class AlertDetailOut(AlertOut):
    actions: list[AlertActionOut] = Field(default_factory=list)


class AlertListOut(BaseModel):
    total: int
    page: int
    size: int
    pages: int
    items: list[AlertOut]
    counts_by_status: dict[str, int] = Field(default_factory=dict)


# ===== Appeal 企业认证申诉 =====

class AppealCreate(BaseModel):
    enterprise_key: str = Field(min_length=1, max_length=64)
    enterprise_name: str = Field(min_length=1, max_length=256)
    category: str = Field(default="other", pattern="^(credit|qualification|blacklist|other)$")
    title: str = Field(min_length=1, max_length=256)
    detail: str = ""
    evidence_url: str = ""


class AppealReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|need_more|start_review)$")
    note: str = ""


class AppealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enterprise_key: str
    enterprise_name: str
    appellant_user_id: Optional[int]
    category: str
    title: str
    detail: str
    evidence_url: str
    status: str
    reviewer_id: Optional[int]
    review_note: str
    created_at: datetime
    reviewed_at: Optional[datetime]


class AppealListOut(BaseModel):
    total: int
    page: int
    size: int
    pages: int
    items: list[AppealOut]
    counts_by_status: dict[str, int] = Field(default_factory=dict)


# ===== Project Monitor 项目监管 =====

class ProjectMonitorCreate(BaseModel):
    tender_key: str = Field(min_length=1, max_length=64)
    tender_name: str = Field(min_length=1, max_length=256)
    builder_name: str = ""
    risk_level: str = Field(default="normal", pattern="^(high|medium|low|normal)$")
    supervision_level: str = Field(default="routine", pattern="^(routine|key|priority)$")


class ProjectMonitorUpdate(BaseModel):
    risk_level: Optional[str] = Field(default=None, pattern="^(high|medium|low|normal)$")
    supervision_level: Optional[str] = Field(default=None, pattern="^(routine|key|priority)$")
    status: Optional[str] = Field(default=None, pattern="^(active|suspended|closed)$")


class InspectionIn(BaseModel):
    note: str = Field(min_length=1, max_length=1024)


class ProjectMonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tender_key: str
    tender_name: str
    builder_name: str
    risk_level: str
    supervision_level: str
    status: str
    inspection_count: int
    last_inspection_at: Optional[datetime]
    last_inspection_note: str
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


class ProjectMonitorListOut(BaseModel):
    total: int
    page: int
    size: int
    pages: int
    items: list[ProjectMonitorOut]
    counts_by_risk: dict[str, int] = Field(default_factory=dict)
