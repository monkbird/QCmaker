"""Public request/response contracts for the management API.

The admin API deliberately keeps these models separate from the business
contracts.  In particular, none of the models here contain a password,
session secret, API token, or raw business payload.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdminUserView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    username: str
    is_active: bool = True


class AdminSessionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    user_id: str
    ip: str | None = None
    user_agent_hash: str | None = None
    created_at: datetime
    last_activity_at: datetime
    last_request_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    is_current: bool = False


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)

    @field_validator("username")
    @classmethod
    def username_is_single_line(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("用户名格式不合法")
        return value


class AdminChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=512)
    reason: str = Field(default="", max_length=500)


class AdminActivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminReauthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=512)


class AdminSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: AdminUserView
    session: AdminSessionView
    csrf_token: str
    server_time: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


class AdminMeResponse(AdminSessionResponse):
    pass


class AdminActivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_time: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


class AdminLogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoked: bool = True


class AdminChangePasswordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relogin_required: bool = True


class AdminReauthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reauthenticated: bool = True
    reauthenticated_at: datetime


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] | None = None


class AdminOperationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    actor_id: str | None = None
    kind: str
    scope: str
    idempotency_key: str | None = None
    state: Literal["pending", "running", "succeeded", "partial", "failed", "cancelled"]
    attempt_count: int = 0
    intended: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_code: str | None = None
    retryable: bool = False
    created_at: datetime
    updated_at: datetime


class AuditLogView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    actor_id: str | None = None
    actor_name: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    request_id: str
    operation_id: str | None = None
    result: Literal["REQUESTED", "SUCCEEDED", "PARTIAL", "FAILED", "DENIED"]
    error_code: str | None = None
    reason: str | None = None
    before_summary: dict[str, Any] | None = None
    after_summary: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    ip: str | None = None
    user_agent_hash: str | None = None
    created_at: datetime


class PagedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[Any]
    total: int
    limit: int
    offset: int
    total_is_estimate: bool = False


class UsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_usd: Decimal = Decimal("0")
    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    request_count: int = 0
    unknown_cost: Decimal = Decimal("0")
    provider_overrun: Decimal = Decimal("0")
