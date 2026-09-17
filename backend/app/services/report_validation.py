"""Deterministic calculations and consistency checks; never verify authenticity."""
import math
from collections import OrderedDict

from backend.app.core.errors import AppException
from backend.app.models.evidence import ChapterSnapshot, EvidenceRef
from backend.app.models.reporting import ChartSpec
from backend.app.services.authoring import resolve_sources

NATURE = {'estimated': '估测', 'measured': '实测（来源待核对）', 'simulated': '模拟'}


def _ref_key(ref):
    return (ref.source_kind, ref.source_id, ref.source_version, ref.locator, ref.origin_kind)


def _source_exists(project_id, ref):
    """Check that a persisted reference still resolves in its owning project."""
    try:
        resolve_sources(project_id, [ref])
        return True
    except Exception:
        return False


def validate_sources(chapter: ChapterSnapshot) -> list[str]:
    """Return missing reference descriptions, including refs used only by metrics/nodes."""
    declared = {_ref_key(ref) for ref in chapter.evidence_refs}
    missing = []
    refs = list(chapter.evidence_refs)
    for metric in chapter.metrics:
        refs.extend(metric.refs)
    for block in chapter.content_blocks:
        if block.get('kind') != 'cause_tree':
            continue
        def visit(nodes):
            for node in nodes or []:
                for raw in node.get('evidence_refs', []):
                    try:
                        refs.append(raw if hasattr(raw, 'source_id') else EvidenceRef.model_validate(raw))
                    except Exception:
                        missing.append('原因树引用格式无效')
                visit(node.get('children', []))
        visit(block.get('nodes', []))
    seen = set()
    for ref in refs:
        key = _ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        if key not in declared:
            missing.append(f'{ref.source_id} v{ref.source_version}（未登记于章节来源）')
        elif not _source_exists(chapter.project_id, ref):
            missing.append(f'{ref.source_id} v{ref.source_version} · {ref.locator}')
    return missing


def _confirmed_node(node, declared):
    """A ref alone is provenance; confirmation also needs a recorded method/result."""
    raw_refs = node.get('evidence_refs') or []
    refs = []
    for raw in raw_refs:
        try:
            refs.append(raw if hasattr(raw, 'source_id') else EvidenceRef.model_validate(raw))
        except Exception:
            return False
    confirmation = node.get('confirmation')
    required = {'method', 'object', 'time', 'criterion', 'result'}
    return bool(node.get('confirmed')) and bool(refs) and all(_ref_key(ref) in declared for ref in refs) and isinstance(confirmation, dict) and all(isinstance(confirmation.get(key), str) and confirmation[key].strip() for key in required)


def number(value) -> float:
    if isinstance(value, bool):
        raise AppException('CHART_NUMBER_INVALID', '布尔值不能作为图表数值', 422)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AppException('CHART_NUMBER_INVALID', '图表存在缺测或非数字项，请核对来源', 422) from exc
    if not math.isfinite(result):
        raise AppException('CHART_NUMBER_INVALID', '图表数值必须有限', 422)
    return result


def percentage_change(before, after) -> float:
    baseline, result = number(before), number(after)
    if baseline == 0:
        raise AppException('ZERO_BASELINE', '零基线不能计算增幅', 422)
    return (result - baseline) / baseline * 100


def build_chart(spec: ChartSpec, chapter: ChapterSnapshot) -> dict:
    if (spec.project_id, spec.chapter_id, spec.revision) != (chapter.project_id, chapter.chapter_id, chapter.revision):
        raise AppException('CHAPTER_NOT_FOUND', '章节版本不存在', 404)
    if spec.chart_type == 'cause_tree':
        blocks = [b for b in chapter.content_blocks if b.get('kind') == 'cause_tree']
        if not blocks:
            raise AppException('CAUSE_TREE_MISSING', '本章尚无结构化原因树', 422)
        if validate_sources(chapter):
            raise AppException('EVIDENCE_NOT_FOUND', '原因树引用的来源不存在或未登记于本章节', 404)

        declared = {_ref_key(ref) for ref in chapter.evidence_refs}
        def label_node(node, depth=0):
            if depth > 20:
                raise AppException('CAUSE_TREE_DEPTH', '原因树层级过深', 422)
            return {'name': f"{node.get('name', '')}（{'已确认' if _confirmed_node(node, declared) else '假设/待确认'}）",
                    'children': [label_node(child, depth + 1) for child in node.get('children', [])]}

        return {'spec': spec.model_dump(), 'value_kind': 'hypothesis', 'refs': [r.model_dump() for r in chapter.evidence_refs],
                'option': {'title': {'text': '原因分析', 'subtext': '假设与确认状态分别显示'},
                           'series': [{'type': 'tree', 'data': [label_node(node) for b in blocks for node in b.get('nodes', [])], 'label': {'fontSize': 12}}]}}
    metric = next((m for m in chapter.metrics if m.metric_id == spec.metric_id), None)
    if metric is None:
        raise AppException('METRIC_NOT_FOUND', '该章节版本中不存在指定指标', 404)
    if validate_sources(chapter):
        raise AppException('EVIDENCE_NOT_FOUND', '指标引用的来源不存在或未登记于本章节', 404)
    rows = [row for block in chapter.content_blocks if block.get('kind') == 'table' and block.get('metric_id') == spec.metric_id for row in block.get('rows', [])]
    if not rows:
        raise AppException('METRIC_DATA_MISSING', '指标缺少结构化数据，不能从正文猜测数值', 422)
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for row in rows:
        for field, expected in [('unit', metric.unit), ('subject', metric.subject), ('value_kind', metric.value_kind), ('comparison', metric.comparison)]:
            if row.get(field) is not None and row[field] != expected:
                raise AppException('METRIC_SCOPE_CONFLICT', f'数据行{field}与指标定义不一致', 422)
        groups.setdefault(str(row.get('label', '')), []).append(row)
    if spec.aggregation == 'weighted_rate':
        values = []
        for members in groups.values():
            if any(row.get('denominator') is None or row.get('numerator') is None for row in members):
                raise AppException('DENOMINATOR_REQUIRED', '合并比例需要逐项分子与分母，不能简单平均', 422)
            denominators = [number(row['denominator']) for row in members]
            if any(x <= 0 for x in denominators):
                raise AppException('DENOMINATOR_INVALID', '分母必须大于零', 422)
            values.append(sum(number(row['numerator']) for row in members) / sum(denominators) * 100)
        labels = list(groups)
    elif spec.aggregation == 'sum':
        if metric.unit in {'%', '％', '百分比'}:
            raise AppException('RATE_AGGREGATION_INVALID', '比例不能求和，请使用含分母的加权比例', 422)
        labels = list(groups)
        values = [sum(number(row.get('value')) for row in group) for group in groups.values()]
    else:
        labels = [str(row.get('label', '')) for row in rows]
        values = [number(row.get('value')) for row in rows]
    option = {'title': {'text': metric.name, 'subtext': f'{NATURE[metric.value_kind]} · {metric.comparison} · 章节版本 {chapter.revision}'},
              'tooltip': {'trigger': 'axis'}, 'xAxis': {'type': 'category', 'data': labels},
              'yAxis': {'type': 'value', 'name': metric.unit, 'min': min(0, min(values))},
              'series': [{'type': spec.chart_type, 'name': metric.name, 'data': values}]}
    if spec.chart_type in {'pie', 'pareto'}:
        if min(values) < 0 or sum(values) <= 0:
            raise AppException('CHART_TOTAL_INVALID', '占比/排列图需要非负数且合计大于零', 422)
        if spec.chart_type == 'pie':
            option.pop('xAxis'); option.pop('yAxis')
            option['series'] = [{'type': 'pie', 'data': [{'name': label, 'value': value} for label, value in zip(labels, values)]}]
        else:
            pairs = sorted(zip(labels, values), key=lambda item: item[1], reverse=True)
            labels, values = map(list, zip(*pairs))
            total, cumulative, percentages = sum(values), 0, []
            for value in values:
                cumulative += value
                percentages.append(round(cumulative / total * 100, 6))
            option['xAxis']['data'] = labels
            option['yAxis'] = [{'type': 'value', 'name': metric.unit, 'min': 0}, {'type': 'value', 'name': '累计占比%', 'min': 0, 'max': 100}]
            option['series'] = [{'type': 'bar', 'name': metric.name, 'data': values}, {'type': 'line', 'name': '累计占比', 'yAxisIndex': 1, 'data': percentages}]
    return {'spec': spec.model_dump(), 'option': option, 'value_kind': metric.value_kind, 'metric': metric.model_dump(),
            'refs': [ref.model_dump() for ref in metric.refs], 'calculation': {'labels': labels, 'values': values, 'aggregation': spec.aggregation}}


def preflight(chapters: list[ChapterSnapshot], expected_chapters: list[str]) -> dict:
    issues = []

    def issue(code, message, chapter_id=None, severity='warning'):
        issues.append({'code': code, 'message': message, 'chapter_id': chapter_id, 'severity': severity})

    if len({c.project_id for c in chapters}) > 1:
        issue('PROJECT_CONFLICT', '章节来自不同项目', severity='error')
    if len({c.path_version for c in chapters}) > 1:
        issue('PATH_CONFLICT', '章节使用的标准参考路径不同', severity='error')
    for missing in set(expected_chapters) - {c.chapter_id for c in chapters}:
        issue('MISSING_CHAPTER', f'缺少章节：{missing}', missing)
    definitions = {}
    for chapter in chapters:
        for missing_ref in validate_sources(chapter):
            issue('EVIDENCE_NOT_FOUND', '来源不存在或未登记：' + missing_ref, chapter.chapter_id, 'error')
        if chapter.content_state != 'complete': issue('CONTENT_PENDING', '内容尚未完整', chapter.chapter_id)
        if chapter.review_state != 'approved': issue('REVIEW_PENDING', '本版尚未获得作者认可', chapter.chapter_id)
        if chapter.evidence_state not in {'verified', 'not_applicable'}: issue('EVIDENCE_PENDING', '证据尚待核实', chapter.chapter_id)
        if chapter.stale: issue('STALE_SOURCE', '上游已变化：' + '；'.join(chapter.stale_reasons), chapter.chapter_id)
        if any(r.origin_kind in {'simulation', 'hypothesis'} for r in chapter.evidence_refs) or any(m.value_kind == 'simulated' for m in chapter.metrics) or any(b.get('origin_kind') in {'simulation', 'hypothesis'} for b in chapter.content_blocks):
            issue('SIMULATION', '含模拟或假设，导出将保留标识', chapter.chapter_id)
        for metric in chapter.metrics:
            definition = (metric.unit, metric.subject, metric.comparison, metric.value_kind, metric.denominator)
            if metric.metric_id in definitions and definitions[metric.metric_id] != definition:
                issue('METRIC_CONFLICT', f'指标{metric.name}在不同章节口径不一致', chapter.chapter_id)
            definitions[metric.metric_id] = definition
        for block in chapter.content_blocks:
            if {'before', 'after', 'growth_percent'} <= block.keys():
                try:
                    expected = percentage_change(block['before'], block['after'])
                    if abs(expected - number(block['growth_percent'])) > .01:
                        issue('CALCULATION_CONFLICT', f'增幅应为{expected:.2f}%，与填报值不同', chapter.chapter_id)
                except AppException as exc:
                    issue(exc.code, exc.message, chapter.chapter_id)
    return {'blocked': any(x['severity'] == 'error' for x in issues), 'issues': issues}
