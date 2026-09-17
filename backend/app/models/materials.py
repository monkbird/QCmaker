from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field
from backend.app.models.evidence import EvidenceBlock, EvidenceRef

ParseStatus = Literal['queued','running','partial','succeeded','failed']
Readiness = Literal['unread','partial','readable','needs_review']
UnitStatus = Literal['pending','parsed','failed','verified_blank']

class Region(BaseModel):
    region_id: str; kind: Literal['text','table','image','chart','notes','footnote','header','footer']
    text: str = ''; table_cells: list[list[str]] = Field(default_factory=list)
    bbox: list[float] | None = None; method: str = 'direct'; confidence: float | None = None
    status: Literal['pending','parsed','failed'] = 'parsed'

class ParseUnit(BaseModel):
    unit_id: str; kind: Literal['page','slide','sheet','block']; ordinal: int; locator: str
    expected_regions: list[str] = Field(default_factory=list); regions: list[Region] = Field(default_factory=list)
    status: UnitStatus = 'pending'; issues: list[str] = Field(default_factory=list)

class MaterialVersion(BaseModel):
    project_id: str; material_id: str; version: int = Field(ge=1); parent_version: int | None = None
    original_sha256: str; original_path: str; filename: str; size_bytes: int = Field(ge=0)
    created_at: datetime; parse_status: ParseStatus = 'queued'; readiness: Readiness = 'unread'; review_status: Literal['unreviewed','reviewed'] = 'unreviewed'

class ParseManifest(BaseModel):
    material_id: str; version: int; units_total: int; units_completed: int; units_failed: int; units_pending: int
    coverage_complete: bool; readiness: Readiness; review_status: Literal['unreviewed','reviewed']; units: list[ParseUnit] = Field(default_factory=list); next_cursor: str | None = None

class RecognitionResult(BaseModel):
    regions: list[Region] = Field(default_factory=list); issues: list[str] = Field(default_factory=list); method: str

class CleaningOperation(BaseModel):
    operation_id: str; category: Literal['document','data','evidence']; target_locator: str
    before: Any; after: Any; reason: str; risk: Literal['low','high'] = 'low'; source_refs: list[EvidenceRef] = Field(default_factory=list)
class CleaningPreview(BaseModel):
    preview_id: str; project_id: str; material_id: str; base_version: int; operations: list[CleaningOperation]
    diff_digest: str; expires_at: datetime
class CleaningReceipt(BaseModel):
    version: int; parent_version: int; applied_operation_ids: list[str]; event_id: str
class MaterialChangedEvent(BaseModel):
    event_id: str; project_id: str; material_id: str; old_version: int | None; new_version: int
    changed_locators: list[str]; reason: str

__all__ = ['EvidenceRef','EvidenceBlock','MaterialVersion','ParseUnit','ParseManifest','RecognitionResult','CleaningOperation','CleaningPreview','CleaningReceipt','MaterialChangedEvent']
