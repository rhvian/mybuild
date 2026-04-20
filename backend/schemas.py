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
