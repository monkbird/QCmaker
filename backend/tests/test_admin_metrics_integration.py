from datetime import UTC, datetime, timedelta

from backend.app.repositories.database import init_database, transaction
from backend.app.services import admin_metrics


def test_overrun_marker_is_not_counted_twice_in_budget(isolated_storage, isolated_settings):
    init_database()
    now = datetime.now(UTC).isoformat()
    with transaction(immediate=True) as db:
        db.execute('INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?)', ('u', 'r', 'p', 'm', 1, 1, 0, '2', None, now))
        db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?)', ('over', 'r', 'p', 'm', '1', 'provider_overrun', now))
        db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?)', ('unknown', 'r2', 'p', 'm', '0.5', 'usage_unknown', now))
    result = admin_metrics.budget_view()
    assert float(result['known_cost_usd']) == 2
    assert float(result['reserved_usd']) == 0.5
    assert float(result['remaining_usd']) == 2.5


def test_running_count_requires_live_lease_and_running_command(isolated_storage):
    init_database()
    now = datetime.now(UTC)
    with transaction(immediate=True) as db:
        for index, expiry in enumerate([now - timedelta(minutes=1), now + timedelta(minutes=1)]):
            sid = str(index)
            db.execute('INSERT INTO discussion_sessions VALUES(?,?,?,?,?,?,?,?)', (sid, 'round_done', '{}', 1, 'w', 1, expiry.isoformat(), (now + timedelta(days=1)).isoformat()))
            db.execute('INSERT INTO discussion_commands VALUES(?,?,?,?,?,?,?)', (sid, 'c', '{}', 'running', None, None, None))
    assert admin_metrics.session_counts()['running'] == 1
