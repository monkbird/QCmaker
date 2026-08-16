from fastapi import APIRouter

from backend.app.core.errors import AppException
from backend.app.models.contracts import ChartRecommendation, ChartRecommendRequest, ChartRequest, ChartResponse
from backend.app.repositories import dataset_repository
from backend.app.services.chart import generate

router = APIRouter()

@router.post("/generate", response_model=ChartResponse)
def generate_chart(request: ChartRequest):
    dataset = dataset_repository.get(request.dataset_id)
    if dataset.revision != request.revision or dataset.confirmed_revision != request.revision: raise AppException("DATA_REVISION_CONFLICT", "请先确认当前数据版本", 409)
    return generate(request, dataset.rows)


@router.post("/recommend", response_model=ChartRecommendation)
def recommend(request: ChartRecommendRequest):
    numeric = next((c.name for c in request.columns if c.inferred_type in {"number", "percent"}), None)
    category = next((c.name for c in request.columns if c.name != numeric), None)
    if not numeric or not category: raise AppException("DATA_FORMAT_UNSUPPORTED", "至少需要一个分类列和一个数值列", 422)
    is_time = any(token in category.lower() for token in ("date", "time", "日期", "时间", "月份"))
    return ChartRecommendation(chart_type="line" if is_time else "bar", x_axis=category, y_axis=numeric, reason="检测到时间序列" if is_time else "分类与数值对比适合柱状图")
