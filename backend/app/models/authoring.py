from __future__ import annotations
from datetime import UTC, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field
from backend.app.models.evidence import ChapterSnapshot, EvidenceRef, MetricSpec

class ScenarioCard(BaseModel):
    project_id: str
    topic: str | None = None
    topic_type: Literal['problem_solving', 'innovation'] = 'problem_solving'
    objective_source: Literal['self_defined', 'directive'] = 'self_defined'
    standard_version: str = 'T/CAQ 10201-2020'
    region: str | None = None
    location: str | None = None
    object_name: str | None = None
    environment: str | None = None
    season: str | None = None
    personnel_range: str | None = None
    equipment: str | None = None
    method: str | None = None
    activity_time: str | None = None
    current_problem: str | None = None
    expected_indicators: list[str] = Field(default_factory=list)
    existing_materials: list[str] = Field(default_factory=list)
    constraints: str | None = None
    field_sources: dict[str, Literal['user','documented','web','hypothesis'] | None] = Field(default_factory=dict)
    revision: int = Field(default=0, ge=0)

class TopicCandidate(BaseModel):
    candidate_id: str
    title: str
    applicability: str = ''
    required_materials: list[str] = Field(default_factory=list)
    measurable_indicators: list[str] = Field(default_factory=list)
    assumptions_to_verify: list[str] = Field(default_factory=list)
    origin_kind: str = 'hypothesis'

class ReviewRequest(BaseModel):
    review_state: Literal['pending','approved','changes_requested']
    reviewer_id: str = Field(min_length=1)
    note: str = ''
    expected_revision: int = Field(ge=1)

class EvidenceVerificationRequest(BaseModel):
    evidence_state: Literal['missing','partial','verified','not_applicable']
    reviewer_id: str = Field(min_length=1)
    basis: list[EvidenceRef] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    expected_revision: int = Field(ge=1)

class ChapterUpdate(BaseModel):
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    content_state: Literal['empty','draft','complete'] = 'draft'
    expected_revision: int = Field(ge=0)
    operation_id: str | None = None

class GenerateChapterRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=200)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

class ChangeRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    context: ScenarioCard

class ChangeApplyRequest(ChangeRequest):
    preview_id: str
    chapter_ids: list[str]

class SourceRecord(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    source_kind: Literal['web', 'user', 'simulation']
    origin_kind: Literal['documented', 'user_reported', 'hypothesis', 'simulation', 'pending']
    locator: str = Field(min_length=1)
    text: str
    expected_revision: int = Field(ge=0)

class SearchSource(BaseModel):
    title: str
    url: str
    published_at: str | None = None
    accessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    applicability: str | None = None
    content: str | None = None

class SearchResponse(BaseModel):
    status: Literal['not_configured','failed','empty','success']
    results: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[SearchSource] = Field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None

__all__ = ['ScenarioCard','TopicCandidate','ReviewRequest','EvidenceVerificationRequest','ChapterUpdate','SearchSource','SearchResponse']
