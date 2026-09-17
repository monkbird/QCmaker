from typing import Literal

from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    project_id: str = Field(min_length=1)
    chapter_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    metric_id: str = Field(min_length=1)
    chart_type: Literal['bar', 'line', 'pie', 'pareto', 'cause_tree'] = 'bar'
    aggregation: Literal['none', 'sum', 'weighted_rate'] = 'none'


class ChapterChartRequest(BaseModel):
    spec: ChartSpec
    operation_id: str = Field(min_length=1, max_length=200)


class ChapterExportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    chapter_revisions: dict[str, int]
    chart_revisions: dict[str, int] = Field(default_factory=dict)
    template_id: str | None = None
    mode: Literal['draft', 'confirmed'] = 'draft'
    operation_id: str = Field(min_length=1, max_length=200)


class ExportPreviewRequest(BaseModel):
    project_id: str = Field(min_length=1)
    chapter_revisions: dict[str, int]
    chart_revisions: dict[str, int] = Field(default_factory=dict)
