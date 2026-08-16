from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AppError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ConfigView(BaseModel):
    llm_provider: str = "openai"
    openai_base_url: str
    openai_model: str
    use_local_llm: bool
    local_llm_url: str
    local_llm_model: str
    max_budget_usd: float
    has_openai_key: bool
    has_tavily_key: bool
    status: Literal["ready", "missing", "degraded"]
    config_revision: int


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    use_local_llm: bool | None = None
    local_llm_url: str | None = None
    local_llm_model: str | None = None
    tavily_api_key: str | None = None
    max_budget_usd: float | None = Field(default=None, ge=0)


class ConnectivityCheck(BaseModel):
    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ModelListRequest(BaseModel):
    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None


class ModelListResponse(BaseModel):
    models: list[str]
    source: Literal["remote"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TopicChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)


class TopicChatResponse(BaseModel):
    response: str


JsonScalar = str | int | float | bool | None


class DataRow(BaseModel):
    row_id: str
    values: dict[str, JsonScalar]


class ColumnInfo(BaseModel):
    name: str
    inferred_type: Literal["string", "number", "percent", "date", "boolean"]
    missing_count: int
    outlier_count: int
    display_format: Literal["plain", "percent", "date", "datetime"] = "plain"


class CleaningRule(BaseModel):
    action: Literal["keep", "drop_rows", "median", "forward_fill", "convert_number", "convert_percent"]
    column: str | None = None
    row_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self) -> "CleaningRule":
        if self.action == "drop_rows" and not self.row_ids:
            raise ValueError("drop_rows 必须提供 row_ids")
        if self.action in {"median", "forward_fill", "convert_number", "convert_percent"} and not self.column:
            raise ValueError(f"{self.action} 必须提供 column")
        return self


class CleaningIssue(BaseModel):
    issue_type: Literal["empty_row", "total_row", "missing", "outlier", "type_conversion"]
    column: str | None = None
    row_ids: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class CleaningReport(BaseModel):
    mode: Literal["detected", "applied", "undone"]
    issues: list[CleaningIssue] = Field(default_factory=list)
    applied_rules: list[CleaningRule] = Field(default_factory=list)
    removed_rows: int = 0
    filled_cells: int = 0
    outliers_detected: int = 0
    type_conversions: int = 0


class DatasetResponse(BaseModel):
    dataset_id: str
    revision: int
    confirmed_revision: int | None = None
    restored_from_revision: int | None = None
    filename: str
    columns: list[ColumnInfo]
    rows: list[DataRow]
    report: CleaningReport


class CleaningApplyRequest(BaseModel):
    dataset_id: str
    base_revision: int
    rules: list[CleaningRule]


class CleaningPreviewResponse(BaseModel):
    dataset_id: str
    base_revision: int
    preview_rows: list[DataRow]
    report: CleaningReport


class RevisionRequest(BaseModel):
    dataset_id: str
    base_revision: int


class ConfirmRequest(BaseModel):
    dataset_id: str
    revision: int


class ChartRequest(BaseModel):
    chart_type: Literal["bar", "line", "pie"]
    dataset_id: str
    revision: int
    x_axis: str
    y_axis: str
    aggregation: Literal["none", "sum", "mean", "count"] | None = None


class ChartProcessing(BaseModel):
    aggregation: Literal["none", "sum", "mean", "count"]
    converted_row_ids: list[str] = Field(default_factory=list)
    grouped_categories: int = 0
    warnings: list[str] = Field(default_factory=list)


class ChartResponse(BaseModel):
    option: dict[str, Any]
    processing: ChartProcessing


class ChartRecommendRequest(BaseModel):
    columns: list[ColumnInfo]
    sample_rows: list[DataRow] = Field(default_factory=list, max_length=100)


class ChartRecommendation(BaseModel):
    chart_type: Literal["bar", "line", "pie"]
    x_axis: str
    y_axis: str
    reason: str


class DiscussionSummary(BaseModel):
    problem: str
    root_causes: list[str]
    countermeasures: list[str]
    summary: str


class PPTRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=80)
    topic: str
    data_summary: str
    discussion_summary: DiscussionSummary
    chart_images: list[str] = Field(default_factory=list, max_length=5)


class PPTResult(BaseModel):
    file_id: UUID
    display_name: str
    expires_at: datetime


class ModelUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    known_cost_usd: Decimal


class UsageView(BaseModel):
    budget_usd: Decimal
    reserved_usd: Decimal
    known_cost_usd: Decimal
    remaining_usd: Decimal
    unknown_cost: bool
    usage_by_model: list[ModelUsage]
