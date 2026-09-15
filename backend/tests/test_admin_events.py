import pytest

from backend.app.repositories.database import connect, init_database
from backend.app.services import events


def test_alerts_deduplicate_and_recovery_is_recorded(isolated_storage):
    init_database()
    args = {'category': 'system', 'message': '数据库状态'}
    assert not events.observe_state('database', 'ok', healthy=True, **args)
    assert events.observe_state('database', 'error', healthy=False, **args)
    for _ in range(3):
        assert not events.observe_state('database', 'error', healthy=False, **args)
    assert events.observe_state('database', 'ok', healthy=True, **args)
    with connect() as db:
        keys = [row[0] for row in db.execute('SELECT event_key FROM operation_events ORDER BY rowid')]
    assert keys == ['database:alert', 'database:recovered']


def test_event_failure_does_not_suppress_next_attempt(isolated_storage, monkeypatch):
    init_database()
    original = events.record_operation_event_tx
    def fail(*args, **kwargs):
        raise RuntimeError('event storage unavailable')
    monkeypatch.setattr(events, 'record_operation_event_tx', fail)
    with pytest.raises(RuntimeError):
        events.observe_state('budget', 'active', category='usage', message='未知占用', healthy=False)
    monkeypatch.setattr(events, 'record_operation_event_tx', original)
    assert events.observe_state('budget', 'active', category='usage', message='未知占用', healthy=False)
