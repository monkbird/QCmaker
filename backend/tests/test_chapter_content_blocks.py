from pptx import Presentation

from backend.app.models.evidence import ChapterSnapshot
from backend.app.models.reporting import ChapterExportRequest
from backend.app.repositories import database
from backend.app.services import chapter_reporting, ppt


def _chapter():
    return ChapterSnapshot(
        project_id='p', chapter_id='c1', revision=1,
        path_version='T/CAQ 10201-2020', content_state='complete',
        review_state='approved', evidence_state='not_applicable',
        content_blocks=[
            {'kind': 'text', 'text': '正文'},
            {'kind': 'table', 'title': '产量表', 'columns': ['区域', '产量'], 'rows': [{'区域': '甲', '产量': 12}]},
            {'kind': 'chart', 'title': '产量趋势', 'chart_type': 'line', 'unit': '公斤/亩',
             'rows': [{'label': '前', 'value': 10}, {'label': '后', 'value': 12}], 'origin_kind': 'simulation'},
        ],
    )


def test_chapter_lines_keeps_table_and_chart_markers():
    lines = chapter_reporting._chapter_lines(_chapter())
    joined = '\n'.join(lines)
    assert '产量表' in joined and '区域 | 产量' in joined and '甲 | 12' in joined
    assert '【模拟】产量趋势' in joined and '前：10' in joined


def test_pareto_lines_are_deterministically_descending_and_zero_safe():
    chapter = _chapter().model_copy(update={'content_blocks': [
        {'kind': 'chart', 'title': '排列', 'chart_type': 'pareto', 'rows': [
            {'label': '乙', 'value': 2}, {'label': '甲', 'value': 5}, {'label': '丙', 'value': 0}
        ]}
    ]})
    lines = chapter_reporting._chapter_lines(chapter)
    assert lines.index('甲：5') < lines.index('乙：2') < lines.index('丙：0')
    zero = chapter.model_copy(update={'content_blocks': [
        {'kind': 'chart', 'title': '零值', 'chart_type': 'pareto', 'rows': [{'label': '甲', 'value': 0}]}
    ]})
    assert '甲：0' in '\n'.join(chapter_reporting._chapter_lines(zero))


def test_export_adds_native_slide_for_chapter_chart(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(ppt, 'OUTPUT_DIR', tmp_path / 'ppts')
    monkeypatch.setattr(ppt, 'TEMPLATE_DIR', tmp_path / 'templates')
    database.init_database()
    chapter = _chapter()
    with database.transaction() as db:
        db.execute('INSERT INTO chapters VALUES(?,?,?,?,?)', ('p', 'c1', 1, chapter.model_dump_json(), 'now'))
    artifact = chapter_reporting.export_chapters(ChapterExportRequest(project_id='p', chapter_revisions={'c1': 1}, operation_id='blocks'))
    path, _ = ppt.resolve_download(artifact.payload['file']['file_id'])
    prs = Presentation(path)
    texts = '\n'.join(shape.text for slide in prs.slides for shape in slide.shapes if shape.has_text_frame)
    assert '产量趋势' in texts and '模拟' in texts
    assert any(shape.has_chart for slide in prs.slides for shape in slide.shapes)
