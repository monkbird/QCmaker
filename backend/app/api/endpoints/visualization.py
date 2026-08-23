import json
import logging
from collections import Counter

import pandas as pd
from fastapi import APIRouter, Depends

from backend.app.core.errors import AppException
from backend.app.core.llm_gateway import chat
from backend.app.core.security import verify_access_token
from backend.app.models.contracts import ChartInsightRequest, ChartInsightResponse, ChartRecommendation, ChartRecommendRequest, ChartRequest, ChartResponse
from backend.app.repositories import dataset_repository
from backend.app.services.chart import generate

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_access_token)])

ADVISOR_PROMPT = """你是QC图表顾问。根据数据画像选择最能支撑论证的图表，并给出业务解读。
只输出合法 JSON：{"chart_type":"bar|line|pie","x_axis":"分类列名","y_axis":"数值列名","aggregation":"none|sum|mean|count","reason":"选型理由","insight":"基于统计分布的业务解读（150字内）","caveats":["注意事项"]}。
约束：x_axis 必须来自分类列、y_axis 必须来自数值列；时间/顺序类分类优先 line。不要 Markdown。"""


@router.post("/generate", response_model=ChartResponse)
def generate_chart(request: ChartRequest):
    dataset = dataset_repository.get(request.dataset_id)
    if dataset.revision != request.revision or dataset.confirmed_revision != request.revision: raise AppException("DATA_REVISION_CONFLICT", "请先确认当前数据版本", 409)
    return generate(request, dataset.rows)


def _rule_recommend(columns) -> tuple[ChartRecommendation, str | None]:
    numeric = next((c.name for c in columns if c.inferred_type in {"number", "percent"}), None)
    category = next((c.name for c in columns if c.inferred_type in {"string", "date", "boolean"}), None)
    if category is None:
        category = next((c.name for c in columns if c.name != numeric and c.inferred_type not in {"number", "percent"}), None)
    if category is None:
        category = next((c.name for c in columns if c.name != numeric), None)
    if not numeric or not category: raise AppException("DATA_FORMAT_UNSUPPORTED", "至少需要一个分类列和一个数值列", 422)
    is_time = any(token in category.lower() for token in ("date", "time", "日期", "时间", "月份"))
    return ChartRecommendation(chart_type="line" if is_time else "bar", x_axis=category, y_axis=numeric, reason="检测到时间序列" if is_time else "分类与数值对比适合柱状图"), None


@router.post("/recommend", response_model=ChartRecommendation)
def recommend(request: ChartRecommendRequest):
    recommendation, _ = _rule_recommend(request.columns)
    return recommendation


def build_profile(dataset) -> dict:
    names = [column.name for column in dataset.columns]
    profile_columns = []
    for column in dataset.columns:
        values = [row.values.get(column.name) for row in dataset.rows]
        entry = {"name": column.name, "type": column.inferred_type, "missing": column.missing_count, "outliers": column.outlier_count}
        nonempty = [value for value in values if value not in (None, "")]
        if column.inferred_type in {"number", "percent"} and nonempty:
            numeric = pd.to_numeric(pd.Series([str(value).replace(",", "").removesuffix("%") for value in nonempty]), errors="coerce").dropna()
            if len(numeric):
                entry.update(minimum=round(float(numeric.min()), 4), maximum=round(float(numeric.max()), 4), mean=round(float(numeric.mean()), 4))
        elif nonempty:
            counts = Counter(str(value) for value in nonempty)
            entry["top_values"] = [{"value": key, "count": count} for key, count in counts.most_common(8)]
        profile_columns.append(entry)
    return {"rows": len(dataset.rows), "columns": profile_columns, "column_names": names}


def _validate_recommendation(payload: dict, dataset) -> ChartRecommendation:
    column_names = {column.name for column in dataset.columns}
    numeric_names = {column.name for column in dataset.columns if column.inferred_type in {"number", "percent"}}
    chart_type = str(payload.get("chart_type", ""))
    x_axis = str(payload.get("x_axis", ""))
    y_axis = str(payload.get("y_axis", ""))
    aggregation = str(payload.get("aggregation", "sum"))
    if chart_type not in {"bar", "line", "pie"}: raise ValueError(f"bad chart_type {chart_type}")
    if x_axis not in column_names or y_axis not in numeric_names: raise ValueError("axis not in dataset")
    if aggregation not in {"none", "sum", "mean", "count"}: aggregation = "sum" if chart_type in {"bar", "pie"} else "none"
    reason = str(payload.get("reason", ""))[:400] or "AI 顾问推荐"
    return ChartRecommendation(chart_type=chart_type, x_axis=x_axis, y_axis=y_axis, reason=reason)


@router.post("/insight", response_model=ChartInsightResponse)
async def chart_insight(request: ChartInsightRequest):
    dataset = dataset_repository.get(request.dataset_id)
    if dataset.revision != request.revision or dataset.confirmed_revision != request.revision: raise AppException("DATA_REVISION_CONFLICT", "请先确认当前数据版本", 409)
    fallback_recommendation, fallback_note = _rule_recommend(dataset.columns)
    focus = f"\n用户关注点：{request.focus}" if request.focus.strip() else ""
    prompt = "数据画像：" + json.dumps(build_profile(dataset), ensure_ascii=False) + focus
    try:
        raw = await chat([{"role": "system", "content": ADVISOR_PROMPT}, {"role": "user", "content": prompt}], role="chart")
        payload = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        recommendation = _validate_recommendation(payload, dataset)
        caveats = [str(item)[:200] for item in payload.get("caveats", [])][:6]
        insight = str(payload.get("insight", ""))[:600]
        from backend.app.services.model_roles import describe_target
        return ChartInsightResponse(recommendation=recommendation, insight=insight, caveats=caveats, model=describe_target("chart"), source="ai")
    except AppException:
        raise
    except Exception as exc:
        logger.warning("chart insight falling back to rules: %s", exc)
        note = fallback_note or "AI 顾问暂不可用或返回异常，已回退到规则推荐。"
        return ChartInsightResponse(recommendation=fallback_recommendation, insight="", caveats=[note], model="rules", source="rules")
