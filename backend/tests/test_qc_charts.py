import pytest

from backend.app.core.errors import AppException
from backend.app.models.evidence import ChapterSnapshot, EvidenceRef, MetricSpec
from backend.app.models.reporting import ChartSpec
from backend.app.repositories import database
from backend.app.services.report_validation import build_chart, percentage_change


@pytest.fixture()
def simulation_source(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.sqlite3')
    database.init_database()
    with database.transaction() as db:
        db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)', ('p', 'source-event', 'source_version', '{"source_id":"s","revision":1,"source_kind":"simulation","origin_kind":"simulation","locator":"样例","text":"模拟"}', 'now'))


def snapshot(**updates):
    return ChapterSnapshot(project_id='p', chapter_id='current_state', revision=1,
        path_version='2020:self', metrics=[MetricSpec(metric_id='m', name='数量', unit='份', subject='台账',
        comparison='groups', sampling_method='统计', time_range='待补', value_kind='simulated')],
        content_blocks=[{'kind': 'table', 'metric_id': 'm', 'rows': [{'label': 'A', 'value': 108}, {'label': 'B', 'value': 42}]}], **updates)


def test_pareto_calculates_percentages_and_preserves_simulation():
    result = build_chart(ChartSpec(project_id='p', chapter_id='current_state', revision=1, metric_id='m', chart_type='pareto'), snapshot())
    assert result['option']['series'][1]['data'] == [72.0, 100.0]
    assert result['value_kind'] == 'simulated'
    assert '模拟' in result['option']['title']['subtext']


def test_growth_is_computed_without_fabricating_zero_baseline():
    assert round(percentage_change(337.04, 374.29), 2) == 11.05
    with pytest.raises(AppException): percentage_change(0, 4)


def test_chart_rejects_cross_project_snapshot():
    with pytest.raises(AppException) as exc:
        build_chart(ChartSpec(project_id='other', chapter_id='current_state', revision=1, metric_id='m'), snapshot())
    assert exc.value.status_code == 404


def test_percentage_average_requires_denominators():
    chapter = snapshot()
    chapter.metrics[0].unit = '%'
    with pytest.raises(AppException):
        build_chart(ChartSpec(project_id='p', chapter_id='current_state', revision=1, metric_id='m', aggregation='weighted_rate'), chapter)


def test_cause_tree_ref_alone_does_not_confirm_node(simulation_source):
    ref = EvidenceRef(source_kind='simulation', source_id='s', source_version=1, locator='样例', origin_kind='simulation')
    chapter = snapshot(evidence_refs=[ref]).model_copy(update={'content_blocks': [{
        'kind': 'cause_tree', 'nodes': [{'name': '原因', 'confirmed': True, 'evidence_refs': [ref.model_dump()]}]
    }]})
    result = build_chart(ChartSpec(project_id='p', chapter_id='current_state', revision=1, metric_id='m', chart_type='cause_tree'), chapter)
    assert '假设/待确认' in result['option']['series'][0]['data'][0]['name']
