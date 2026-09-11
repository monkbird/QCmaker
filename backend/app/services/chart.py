import math
from collections import OrderedDict

from backend.app.core.errors import AppException
from backend.app.models.contracts import ChartProcessing, ChartRequest, ChartResponse, DataRow


def generate(request: ChartRequest, rows: list[DataRow]) -> ChartResponse:
    names = set(rows[0].values) if rows else set()
    if request.x_axis not in names or request.y_axis not in names:
        raise AppException("DATA_AXIS_INVALID", "指定的图表轴不存在", 422)
    aggregation = request.aggregation or ("sum" if request.chart_type in {"bar", "pie"} else "none")
    invalid: list[str] = []; converted: list[str] = []; points: list[tuple[str, float]] = []
    for row in rows:
        raw = row.values.get(request.y_axis)
        try:
            if isinstance(raw, bool) and aggregation != "count": raise ValueError("boolean")
            value = 1.0 if aggregation == "count" else float(str(raw).replace(",", ""))
            if not math.isfinite(value): raise ValueError("non-finite number")
        except (TypeError, ValueError): invalid.append(row.row_id); continue
        if aggregation != "count" and not isinstance(raw, bool) and not isinstance(raw, (int, float)): converted.append(row.row_id)
        category = row.values.get(request.x_axis)
        points.append(("" if category is None else str(category), value))
    if invalid: raise AppException("DATA_Y_NOT_NUMERIC", "Y 轴包含无法转换的值", 422, {"row_ids": invalid, "suggestion": "请先应用 convert_number 清洗规则"})
    aggregation = request.aggregation or ("sum" if request.chart_type in {"bar", "pie"} else "none")
    if aggregation == "none": x_data = [x for x, _ in points]; y_data = [y for _, y in points]; grouped = 0
    else:
        groups: OrderedDict[str, list[float]] = OrderedDict()
        for x, y in points: groups.setdefault(x, []).append(y)
        x_data = list(groups); grouped = sum(len(values) > 1 for values in groups.values())
        y_data = [sum(values) if aggregation == "sum" else sum(values) / len(values) if aggregation == "mean" else len(values) for values in groups.values()]
    if request.chart_type == "pie" and (any(y < 0 for y in y_data) or sum(y_data) <= 0):
        raise AppException("DATA_PIE_INVALID", "饼图数值必须非负且合计大于零", 422)
    if request.chart_type == "pie": option = {"title": {"text": f"{request.y_axis} 占比分布"}, "tooltip": {"trigger": "item"}, "series": [{"name": request.y_axis, "type": "pie", "radius": "50%", "data": [{"name": x, "value": y} for x, y in zip(x_data, y_data)]}]}
    else: option = {"title": {"text": f"{request.y_axis} 按 {request.x_axis} 分布"}, "tooltip": {"trigger": "axis"}, "xAxis": {"type": "category", "data": x_data}, "yAxis": {"type": "value"}, "series": [{"name": request.y_axis, "type": request.chart_type, "data": y_data}]}
    return ChartResponse(option=option, processing=ChartProcessing(aggregation=aggregation, converted_row_ids=converted, grouped_categories=grouped, warnings=["count 按分类统计行数，包含 Y 轴为空的行"] if aggregation == "count" else []))
