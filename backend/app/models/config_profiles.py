from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

RoleId = Literal["moderator", "researcher", "analyst", "critic", "writer", "topic", "data", "chart"]


class ModelBinding(BaseModel):
    service_id: str = Field(min_length=1)
    model: str = Field(min_length=1)


class ServiceDraft(BaseModel):
    service_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    credential_id: str | None = None
    api_key: SecretStr | None = None


class SearchBinding(BaseModel):
    provider: Literal["tavily"] = "tavily"
    credential_id: str | None = None
    api_key: SecretStr | None = None


class ConfigDraft(BaseModel):
    name: str = Field(min_length=1)
    default_model: ModelBinding | None = None
    roles: dict[RoleId, ModelBinding | None] = Field(default_factory=dict)
    services: list[ServiceDraft] = Field(default_factory=list)
    search: SearchBinding | None = None

    @model_validator(mode="after")
    def validate_services(self) -> "ConfigDraft":
        ids = [s.service_id for s in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("service_id must be unique")
        known = set(ids)
        for binding in [self.default_model, *self.roles.values()]:
            if binding is not None and binding.service_id not in known:
                raise ValueError(f"unknown service_id: {binding.service_id}")
        return self


class ProfileSaveRequest(BaseModel):
    profile_id: str | None = None
    expected_revision: int = Field(ge=0)
    draft: ConfigDraft


class ProbeRequest(BaseModel):
    draft: ConfigDraft
    draft_version: int = Field(ge=1)
    expected_revision: int = Field(ge=0)


class CapabilityIssue(BaseModel):
    role: str
    code: str
    message: str


class ProbeRow(BaseModel):
    role: str
    service_id: str | None
    provider: str | None
    base_url: str | None
    model: str | None
    status: Literal["passed", "failed", "missing"]
    code: str | None = None
    message: str
    latency_ms: int | None = None


class ProbeReport(BaseModel):
    draft_version: int
    config_revision: int
    passed: bool
    rows: list[ProbeRow]


class ProfileView(BaseModel):
    profile_id: str
    config_revision: int
    active: bool
    draft: ConfigDraft
    credential_configured: dict[str, bool] = Field(default_factory=dict)


class RuntimeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    config_revision: int
    draft: ConfigDraft

    def clone(self) -> "RuntimeSnapshot":
        return RuntimeSnapshot(config_revision=self.config_revision, draft=deepcopy(self.draft))
