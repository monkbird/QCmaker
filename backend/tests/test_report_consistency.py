import pytest

from backend.app.models.evidence import ChapterSnapshot, EvidenceRef
from backend.app.repositories import database
from backend.app.services.report_validation import preflight


@pytest.fixture()
def simulation_source(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.sqlite3')
    database.init_database()
    with database.transaction() as db:
        db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)', ('p', 'source-event', 'source_version', '{"source_id":"s","revision":1,"source_kind":"simulation","origin_kind":"simulation","locator":"样例","text":"模拟"}', 'now'))


def test_preflight_flags_missing_chapters_unreviewed_and_simulation(simulation_source):
    chapter = ChapterSnapshot(project_id='p', chapter_id='topic', revision=1, path_version='2020:self',
        content_state='complete', review_state='approved', evidence_state='partial',
        evidence_refs=[EvidenceRef(source_kind='simulation', source_id='s', source_version=1, locator='样例', origin_kind='simulation')])
    report = preflight([chapter], ['topic', 'effects'])
    assert not report['blocked']
    assert {x['code'] for x in report['issues']} >= {'MISSING_CHAPTER', 'EVIDENCE_PENDING', 'SIMULATION'}


def test_report_rejects_mixed_paths_and_conflicting_metric_definitions():
    a = ChapterSnapshot(project_id='p', chapter_id='a', revision=1, path_version='2020:self')
    b = ChapterSnapshot(project_id='p', chapter_id='b', revision=1, path_version='2020:assigned')
    report = preflight([a, b], [])
    assert report['blocked']
    assert any(x['code'] == 'PATH_CONFLICT' for x in report['issues'])
