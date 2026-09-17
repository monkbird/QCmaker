import json

import pytest
from pptx import Presentation

from backend.app.core.errors import AppException
from backend.app.models.evidence import ChapterSnapshot
from backend.app.models.reporting import ChapterExportRequest
from backend.app.repositories import database
from backend.app.repositories.artifact_repository import list_artifacts
from backend.app.services import chapter_reporting, ppt


@pytest.fixture()
def report_store(tmp_path, monkeypatch, isolated_settings):
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(ppt, 'OUTPUT_DIR', tmp_path / 'ppts')
    monkeypatch.setattr(ppt, 'TEMPLATE_DIR', tmp_path / 'templates')
    database.init_database()
    chapter = ChapterSnapshot(project_id='p', chapter_id='example', revision=1, path_version='T/CAQ 10201-2020',
        content_state='complete', review_state='approved', evidence_state='partial',
        content_blocks=[{'kind': 'text', 'text': '模拟产量变化示例，待核实。', 'origin_kind': 'simulation'}])
    with database.transaction() as db:
        db.execute('INSERT INTO chapters VALUES(?,?,?,?,?)', ('p', 'example', 1, chapter.model_dump_json(), 'now'))
    return chapter


def test_export_preserves_markers_and_idempotent_result(report_store):
    request = ChapterExportRequest(project_id='p', chapter_revisions={'example': 1}, operation_id='export1')
    a = chapter_reporting.export_chapters(request)
    b = chapter_reporting.export_chapters(request)
    assert a.artifact_id == b.artifact_id
    path, _ = ppt.resolve_download(a.payload['file']['file_id'])
    text = '\n'.join(shape.text for slide in Presentation(path).slides for shape in slide.shapes if shape.has_text_frame)
    assert '模拟' in text and '待核实' in text
    assert a.upstream_versions['chapter:example'] == 1


def test_export_rejects_cross_project_and_operation_reuse(report_store):
    request = ChapterExportRequest(project_id='p', chapter_revisions={'example': 1}, operation_id='op')
    chapter_reporting.export_chapters(request)
    with pytest.raises(AppException):
        chapter_reporting.export_chapters(request.model_copy(update={'mode': 'confirmed'}))
    with pytest.raises(AppException) as exc:
        chapter_reporting.export_chapters(request.model_copy(update={'project_id': 'other'}))
    assert exc.value.status_code == 404


def test_chapter_changes_stale_only_dependent_artifacts(report_store):
    chapter_reporting.export_chapters(ChapterExportRequest(project_id='p', chapter_revisions={'example': 1}, operation_id='op'))
    new = report_store.model_copy(update={'revision': 2})
    with database.transaction() as db:
        db.execute('INSERT INTO chapters VALUES(?,?,?,?,?)', ('p', 'example', 2, new.model_dump_json(), 'now'))
    artifacts = list_artifacts('p')
    assert len(artifacts) == 1 and artifacts[0].stale
