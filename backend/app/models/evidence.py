"""Shared, versioned QC evidence and snapshot contracts.

These models deliberately contain only cross-domain fields. Domain-specific
payloads belong in their owning package and are carried as JSON there.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SourceKind = Literal["material", "web", "user", "derived", "simulation"]
OriginKind = Literal["documented", "user_reported", "computed", "hypothesis", "simulation", "pending"]
ContentState = Literal["empty", "draft", "complete"]
ReviewState = Literal["pending", "approved", "changes_requested"]
EvidenceState = Literal["missing", "partial", "verified", "not_applicable"]


class EvidenceRef(BaseModel):
    source_kind: SourceKind
    source_id: str
    source_version: int = Field(ge=1)
    locator: str = Field(min_length=1)
    excerpt: str | None = None
    origin_kind: OriginKind


class EvidenceBlock(BaseModel):
    ref: EvidenceRef
    text: str
    table_position: str | None = None


class ProjectContext(BaseModel):
    project_id: str
    region: str | None = None
    business_context: str | None = None
    personnel_constraints: str | None = None
    equipment_constraints: str | None = None
    activity_start: datetime | None = None
    activity_end: datetime | None = None
    topic_type: str | None = None
    objective_source: str | None = None
    standard_version: str | None = None
    source_notes: str | None = None
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_period(self) -> "ProjectContext":
        if self.activity_start and self.activity_end and self.activity_end < self.activity_start:
            raise ValueError("activity_end must not precede activity_start")
        return self


class MetricSpec(BaseModel):
    metric_id: str
    name: str
    unit: str
    numerator: str | None = None
    denominator: str | None = None
    subject: str
    comparison: str
    sampling_method: str
    time_range: str
    value_kind: Literal["estimated", "measured", "simulated"]
    refs: list[EvidenceRef] = Field(default_factory=list)


class ChapterSnapshot(BaseModel):
    project_id: str
    chapter_id: str
    revision: int = Field(ge=1)
    path_version: str
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    content_state: ContentState = "empty"
    review_state: ReviewState = "pending"
    evidence_state: EvidenceState = "missing"
    upstream_versions: dict[str, int] = Field(default_factory=dict)
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)


class ArtifactSnapshot(BaseModel):
    artifact_id: str
    project_id: str
    content_version: int = Field(ge=1)
    upstream_versions: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime
    artifact_kind: Literal["chart", "export"]
    operation_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)
