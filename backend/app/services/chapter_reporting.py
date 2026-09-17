"""Version-pinned chapter reports, with protected downloads and replayable operations."""
import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pptx import Presentation

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException
from backend.app.models.reporting import ChapterChartRequest, ChapterExportRequest
from backend.app.repositories import artifact_repository as artifacts
from backend.app.repositories.database import connect, transaction
from backend.app.services import ppt
from backend.app.services.report_validation import build_chart, preflight

_operation_lock = threading.RLock()


def _hash(request) -> str:
    return hashlib.sha256(json.dumps(request.model_dump(mode='json'), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _context(project_id):
    db = connect()
    try:
        row = db.execute('SELECT context_json FROM project_contexts WHERE project_id=?', (project_id,)).fetchone()
    finally:
        db.close()
    return json.loads(row[0]) if row else {}


def load_chapters(project_id, revisions):
    if not revisions:
        raise AppException('CHAPTERS_REQUIRED', '请选择至少一个已保存章节', 422)
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in revisions.values()):
        raise AppException('REVISION_INVALID', '章节版本必须为正整数', 422)
    return [artifacts.chapter_snapshot(project_id, key, version) for key, version in revisions.items()]


def outline(project_id, chapters):
    from backend.app.services.qc_paths import chapter_path
    context = _context(project_id)
    version = context.get('standard_version') or (chapters[0].path_version if chapters else 'T/CAQ 10201-2020')
    path = chapter_path(context.get('topic_type') or 'problem_solving', context.get('objective_source') or 'self_defined', version)
    return {item.chapter_id: item.title for item in path}


def preview(project_id, chapter_revisions, chart_revisions=None):
    chapters = load_chapters(project_id, chapter_revisions)
    titles = outline(project_id, chapters)
    report = preflight(chapters, list(titles))
    for issue in report['issues']:
        if issue['code']=='MISSING_CHAPTER':
            issue['message']='缺少章节：'+titles.get(issue['chapter_id'],issue['chapter_id'])
    for artifact_id, revision in (chart_revisions or {}).items():
        artifact = artifacts.get_artifact(project_id, artifact_id)
        if artifact.artifact_kind != 'chart' or artifact.content_version != revision:
            raise AppException('CHART_VERSION_INVALID', '图表版本不存在', 404)
        if any(chapter_revisions.get(key[8:]) != value for key, value in artifact.upstream_versions.items() if key.startswith('chapter:')):
            report['issues'].append({'code': 'CHART_INPUT_CONFLICT', 'message': '图表与选中章节版本不一致', 'severity': 'error', 'chapter_id': None})
            report['blocked'] = True
        if artifact.stale:
            report['issues'].append({'code': 'STALE_CHART', 'message': '图表依赖已变化，导出将保留提示', 'severity': 'warning', 'chapter_id': None})
    report['issues'].append({'code': 'STANDARD_UNCONFIRMED', 'message': '按所标注参考版本组织，正式适用标准及申报要求尚需核定', 'severity': 'warning', 'chapter_id': None})
    return report


def generate_chart(request: ChapterChartRequest):
    digest = _hash(request)
    with _operation_lock:
        prior = artifacts.by_operation(request.spec.project_id, request.operation_id, digest)
        if prior: return prior
        chapter = artifacts.chapter_snapshot(request.spec.project_id, request.spec.chapter_id, request.spec.revision)
        payload = build_chart(request.spec, chapter)
        payload['request_hash'] = digest
        upstream = {f'chapter:{chapter.chapter_id}': chapter.revision}
        upstream.update({f'material:{r.source_id}': r.source_version for r in chapter.evidence_refs if r.source_kind == 'material'})
        return artifacts.save(request.spec.project_id, 'chart', request.operation_id, upstream, payload)


def _chapter_lines(chapter, include_structured=True):
    state = f'内容：{chapter.content_state}；作者审核：{chapter.review_state}；证据：{chapter.evidence_state}'
    lines = [state, '事实核实与写法审核分别记录。']
    if chapter.evidence_state not in {'verified', 'not_applicable'}: lines.append('【待核实】本章存在待补证据。')
    if chapter.stale: lines.append('【待复核】' + '；'.join(chapter.stale_reasons))
    for block in chapter.content_blocks:
        nature = block.get('origin_kind', '')
        marker = {'simulation': '【模拟】', 'hypothesis': '【假设】', 'pending': '【待核实】'}.get(nature, '')
        if block.get('kind') == 'table' and include_structured:
            lines.append(marker + str(block.get('title', '指标数据')))
            rows = block.get('rows', [])
            columns = block.get('columns') or list(dict.fromkeys(key for row in rows if isinstance(row, dict) for key in row))
            lines.append(' | '.join(str(c) for c in columns))
            for row in rows:
                lines.append(' | '.join(str(row.get(c, '待补')) for c in columns) if isinstance(row, dict) else str(row))
        elif block.get('kind') == 'chart' and include_structured:
            lines.append(marker + str(block.get('title', '章节图表')) + f"（{block.get('chart_type', 'bar')}，单位：{block.get('unit', '')}）")
            rows = block.get('rows', [])
            if block.get('chart_type') == 'pareto':
                rows = sorted((row for row in rows if isinstance(row, dict)), key=lambda row: (-row.get('value', 0), str(row.get('label', ''))))
            for row in rows:
                if isinstance(row, dict):
                    lines.append(f"{row.get('label', '待补')}：{row.get('value', '待补')}")
        elif block.get('kind') == 'cause_tree':
            def visit(nodes, level=0):
                for node in nodes:
                    from backend.app.services.report_validation import _confirmed_node, _ref_key
                    confirmed = _confirmed_node(node, {_ref_key(ref) for ref in chapter.evidence_refs})
                    lines.append('  ' * level + str(node.get('name', '')) + ('【已确认】' if confirmed else '【假设/待确认】'))
                    if level < 20: visit(node.get('children', []), level + 1)
            visit(block.get('nodes', []))
        else:
            lines.append(marker + str(block.get('text', '')))
    for metric in chapter.metrics:
        nature = {'estimated': '估测', 'measured': '实测（来源待核对）', 'simulated': '模拟'}[metric.value_kind]
        lines.append(f'指标：{metric.name}；{metric.unit}；{metric.subject}；{metric.comparison}；{nature}；{metric.time_range}')
    for ref in chapter.evidence_refs:
        lines.append(f'来源：{ref.source_id} v{ref.source_version} · {ref.locator} · {ref.origin_kind}')
    return lines


def export_chapters(request: ChapterExportRequest):
    digest = _hash(request)
    with _operation_lock:
        prior = artifacts.by_operation(request.project_id, request.operation_id, digest)
        if prior: return prior
        chapters = load_chapters(request.project_id, request.chapter_revisions)
        report = preview(request.project_id, request.chapter_revisions, request.chart_revisions)
        if report['blocked']:
            raise AppException('REPORT_BLOCKED', '版本或项目冲突，不能导出', 422, report)
        if request.mode == 'confirmed' and any(c.review_state != 'approved' or c.stale for c in chapters):
            raise AppException('REPORT_REVIEW_REQUIRED', '确认稿要求选中章节均已审核且无失效项，可先导出草稿', 422, report)
        titles = outline(request.project_id, chapters)
        order = list(titles)
        chapters.sort(key=lambda c: order.index(c.chapter_id) if c.chapter_id in order else len(order))
        templates = {p.stem: p for p in ppt.TEMPLATE_DIR.glob('*.pptx')} if ppt.TEMPLATE_DIR.exists() else {}
        if request.template_id and request.template_id not in templates:
            raise AppException('TEMPLATE_NOT_FOUND', '模板不存在', 404)
        template = templates.get(request.template_id) if request.template_id else None
        prs = Presentation(template) if template else Presentation()
        title = str(_context(request.project_id).get('topic') or _context(request.project_id).get('current_problem') or 'QC成果')
        ppt._add_bullets(prs, 'QC成果 · ' + ('草稿' if request.mode == 'draft' else '作者确认稿'), [title, '作者认可写法不等于事实已核实；模拟与待核实标识保留。'])
        ppt._add_bullets(prs, '导出预检', [i['message'] for i in report['issues']] or ['本次预检未发现缺项，仍需人工核对。'])
        upstream = {}
        for chapter in chapters:
            upstream[f'chapter:{chapter.chapter_id}'] = chapter.revision
            upstream.update({f'material:{r.source_id}': r.source_version for r in chapter.evidence_refs if r.source_kind == 'material'})
            status_chapter = chapter.model_copy(update={'content_blocks': []})
            ppt._add_bullets(prs, f'{titles.get(chapter.chapter_id, chapter.chapter_id)} · v{chapter.revision}', _chapter_lines(status_chapter))
            _add_chapter_content_slides(prs, chapter)
        for artifact_id, revision in request.chart_revisions.items():
            chart = artifacts.get_artifact(request.project_id, artifact_id)
            upstream[f'chart:{artifact_id}'] = revision
            upstream.update(chart.upstream_versions)
            _add_chart_slide(prs, chart)
        file_id = str(uuid4())
        safe_title = re.sub(r'[^\w\u4e00-\u9fff-]+', '_', title).strip('_')[:50] or 'QC成果'
        display_name = f'{safe_title}_{"草稿" if request.mode == "draft" else "作者确认稿"}.pptx'
        ppt.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        final_path = (ppt.OUTPUT_DIR / f'{file_id}.pptx').resolve()
        temporary = ppt.OUTPUT_DIR / f'.{file_id}.tmp.pptx'
        now = datetime.now(UTC)
        expires = now + timedelta(days=get_settings().PPT_TTL_DAYS)
        payload = {'request_hash': digest, 'file': {'file_id': file_id, 'display_name': display_name, 'expires_at': expires.isoformat()},
                   'preflight': report, 'mode': request.mode, 'snapshots': [c.model_dump(mode='json') for c in chapters]}
        with ppt._temp_lock: ppt._active_temps.add(temporary)
        try:
            prs.save(temporary)
            os.replace(temporary, final_path)
            with transaction(immediate=True) as db:
                db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (file_id, display_name, str(final_path), now.isoformat(), expires.isoformat()))
                artifact = artifacts.save(request.project_id, 'export', request.operation_id, upstream, payload, db=db)
            return artifact
        except Exception:
            final_path.unlink(missing_ok=True)
            raise
        finally:
            with ppt._temp_lock:
                temporary.unlink(missing_ok=True)
                ppt._active_temps.discard(temporary)


def _add_chart_slide(prs, artifact):
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    payload = artifact.payload
    calc = payload.get('calculation')
    title = payload.get('option', {}).get('title', {}).get('text', '章节图表')
    marker = payload.get('option', {}).get('title', {}).get('subtext', '待核实')
    if not calc:
        ppt._add_bullets(prs, title, [marker, json.dumps(payload.get('option', {}).get('series', []), ensure_ascii=False)])
        return
    labels, values = calc['labels'], calc['values']
    # Charts are paginated to keep category labels legible.
    for start in range(0, len(labels), 12):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        ppt._set_title_text(slide, title + ('（续）' if start else ''))
        data = CategoryChartData()
        data.categories = labels[start:start+12]
        data.add_series(title, values[start:start+12])
        kind = payload.get('spec', {}).get('chart_type')
        chart_type = XL_CHART_TYPE.PIE if kind == 'pie' else XL_CHART_TYPE.LINE if kind == 'line' else XL_CHART_TYPE.COLUMN_CLUSTERED
        slide.shapes.add_chart(chart_type, Inches(.6), Inches(1.4), prs.slide_width-Inches(1.2), prs.slide_height-Inches(2.2), data)
        note = slide.shapes.add_textbox(Inches(.6), prs.slide_height-Inches(.7), prs.slide_width-Inches(1.2), Inches(.5))
        note.text_frame.text = marker + (' · 待复核' if artifact.stale else '')
    if payload.get('spec', {}).get('chart_type') == 'pareto':
        cumulative = payload['option']['series'][1]['data']
        ppt._add_bullets(prs, title + ' · 累计占比', [f'{label}：{value:g}%；频数{frequency:g}' for label, value, frequency in zip(labels, cumulative, values)])


def _block_marker(block):
    return {'simulation': '【模拟】', 'hypothesis': '【假设】', 'pending': '【待核实】'}.get(block.get('origin_kind', ''), '')


def _add_chapter_content_slides(prs, chapter):
    """Render structured chapter blocks as native PPT shapes/charts.

    Text is still emitted by ``_chapter_lines``. These slides add readable native
    tables and charts without disturbing the legacy external chart artifact path.
    """
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches, Pt

    for block in chapter.content_blocks:
        kind = block.get('kind')
        if kind == 'text':
            ppt._add_bullets(prs, _block_marker(block) + '章节正文', [str(block.get('text', ''))])
        elif kind == 'table':
            rows = [row for row in block.get('rows', []) if isinstance(row, dict)]
            columns = block.get('columns') or list(dict.fromkeys(k for row in rows for k in row))
            if not columns:
                continue
            # Estimate row height from text length so wide multi-column QC tables
            # remain readable; long rows consume more page capacity.
            page_rows, pages, used = [], [], 0
            for row in rows or [{}]:
                row_chars = max((len(str(row.get(column, '待补'))) for column in columns), default=1)
                row_units = max(1, (row_chars + 24) // 25)
                capacity = 6 if len(columns) >= 7 else 12
                if page_rows and used + row_units > capacity:
                    pages.append(page_rows)
                    page_rows, used = [], 0
                page_rows.append(row)
                used += row_units
            if page_rows:
                pages.append(page_rows)
            for page_index, page_rows in enumerate(pages):
                slide = prs.slides.add_slide(prs.slide_layouts[5])
                ppt._set_title_text(slide, _block_marker(block) + str(block.get('title', '章节表格')) + ('（续）' if page_index else ''))
                table = slide.shapes.add_table(len(page_rows) + 1, len(columns), Inches(.45), Inches(1.35), prs.slide_width - Inches(.9), prs.slide_height - Inches(2.0)).table
                table.rows[0].height = Inches(.4)
                for col, name in enumerate(columns):
                    table.cell(0, col).text = str(name)
                for row_idx, row in enumerate(page_rows, 1):
                    for col, name in enumerate(columns):
                        table.cell(row_idx, col).text = str(row.get(name, '待补'))
                heights = []
                for row_idx, row in enumerate(page_rows, 1):
                    row_chars = max((len(str(row.get(column, '待补'))) for column in columns), default=1)
                    heights.append(min(1.15, max(.38, .30 + row_chars / 90)))
                scale = min(1, 6.15 / sum(heights)) if heights else 1
                for row_idx, height in enumerate(heights, 1):
                    table.rows[row_idx].height = Inches(height * scale)
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.text_frame.paragraphs:
                            for run in paragraph.runs:
                                run.font.size = Pt(10 if len(paragraph.text) > 45 else 12)
        elif kind == 'chart':
            rows = [row for row in block.get('rows', []) if isinstance(row, dict)]
            if block.get('chart_type') == 'pareto':
                rows = sorted(rows, key=lambda row: (-row.get('value', 0), str(row.get('label', ''))))
            labels = [str(row.get('label', '待补')) for row in rows]
            values = [row.get('value') for row in rows]
            if not labels or any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values):
                continue
            chart_type = block.get('chart_type', 'bar')
            for start in range(0, len(labels), 12):
                slide = prs.slides.add_slide(prs.slide_layouts[5])
                ppt._set_title_text(slide, _block_marker(block) + str(block.get('title', '章节图表')) + ('（续）' if start else ''))
                data = CategoryChartData()
                data.categories = labels[start:start + 12]
                data.add_series(str(block.get('unit', '数值')), values[start:start + 12])
                native_type = XL_CHART_TYPE.LINE if chart_type == 'line' else XL_CHART_TYPE.COLUMN_CLUSTERED
                slide.shapes.add_chart(native_type, Inches(.65), Inches(1.35), prs.slide_width - Inches(1.3), prs.slide_height - Inches(2.15), data)
            if chart_type == 'pareto':
                total = sum(values)
                cumulative = []
                running = 0
                for label, value in zip(labels, values):
                    running += value
                    cumulative.append(f'{label}：{running / total * 100:.2f}%（{value:g}）' if total > 0 else f'{label}：累计占比不可计算（{value:g}）')
                ppt._add_bullets(prs, _block_marker(block) + str(block.get('title', '排列图')) + ' · 累计占比', ['柱形图按数值降序展示；累计占比以表格列示。'] + cumulative)
