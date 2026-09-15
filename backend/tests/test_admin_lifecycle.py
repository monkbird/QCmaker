import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.core.errors import AppException
from backend.app.repositories.database import init_database, transaction
from backend.app.services import discussion_session as sessions


def seed(status='round_error', lease_until=None):
    command = {'session_id': 's', 'client_message_id': 'c', 'type': 'message', 'content': 'continue'}
    with transaction(immediate=True) as db:
        db.execute('INSERT INTO discussion_sessions VALUES(?,?,?,?,?,?,?,?)',
                   ('s', status, '{}', 1, 'old', 4, lease_until, '2099-01-01T00:00:00Z'))
        db.execute('INSERT INTO discussion_commands VALUES(?,?,?,?,?,?,?)',
                   ('s', 'c', json.dumps(command), 'failed', None, None, None))
    return command


def test_cancel_invalidates_worker_and_seals_commands(isolated_storage):
    init_database()
    seed(lease_until=(datetime.now(UTC) + timedelta(minutes=1)).isoformat())
    with transaction(immediate=True) as db:
        result = sessions.admin_cancel(db, 's')
        assert result['cancelled_commands'] == 1
        assert result['inflight_cost_preserved']
        assert db.execute("SELECT status,lease_generation FROM discussion_sessions").fetchone()[:] == ('cancelled', 5)
        with pytest.raises(AppException, match='租约'):
            sessions._guard_lease(db, 's', 'old', 4)
    with pytest.raises(AppException):
        sessions.accept_command({'type': 'message', 'session_id': 's', 'client_message_id': 'new'})


def test_recovery_requeues_only_expired_work_and_is_transactional(isolated_storage):
    init_database()
    command = seed(lease_until=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    with transaction(immediate=True) as db:
        assert sessions.admin_recover(db, 's') == [command]
        assert db.execute('SELECT status,lease_generation FROM discussion_sessions').fetchone()[:] == ('round_done', 5)
        assert db.execute('SELECT status FROM discussion_commands').fetchone()[0] == 'pending'


def test_recovery_rejects_live_lease_without_changes(isolated_storage):
    init_database()
    seed(lease_until=(datetime.now(UTC) + timedelta(minutes=1)).isoformat())
    with transaction(immediate=True) as db:
        with pytest.raises(AppException):
            sessions.admin_recover(db, 's')
        assert db.execute('SELECT lease_generation FROM discussion_sessions').fetchone()[0] == 4


def test_config_invalid_candidate_never_changes_disk_or_memory(isolated_settings, monkeypatch):
    from backend.app.core import config
    config.ENV_PATH.write_text('MAX_BUDGET_USD=5\n', encoding='utf-8')
    before = config.ENV_PATH.read_bytes()
    with pytest.raises(ValueError):
        config.update_settings({'MAX_BUDGET_USD': -1}, expected_revision=0)
    assert config.ENV_PATH.read_bytes() == before
    assert config.get_settings().MAX_BUDGET_USD == 5
    config.update_settings({'MAX_BUDGET_USD': 7}, expected_revision=0)
    with pytest.raises(AppException):
        config.update_settings({'MAX_BUDGET_USD': 8}, expected_revision=0)
    monkeypatch.setenv('MAX_BUDGET_USD', '10')
    with pytest.raises(AppException):
        config.update_settings({'MAX_BUDGET_USD': 9}, expected_revision=1)
    assert config.get_settings().MAX_BUDGET_USD == 7


def test_config_quoted_secret_roundtrips(isolated_settings):
    from backend.app.core import config
    secret = "a#b'c\\d"
    config.update_settings({'OPENAI_API_KEY': secret})
    assert config.Settings(_env_file=config.ENV_PATH).OPENAI_API_KEY == secret
