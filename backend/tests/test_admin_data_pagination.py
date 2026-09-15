import json
from datetime import UTC, datetime, timedelta

import pytest


def test_usage_export_and_reservations_are_bounded_and_stable(isolated_storage):
    from backend.app.core.errors import AppException
    from backend.app.repositories.database import init_database, transaction
    from backend.app.services.admin_metrics import render_usage_csv, reservation_views, usage_export_rows

    now = datetime.now(UTC).replace(microsecond=0)
    init_database()
    with transaction(immediate=True) as db:
        db.executemany(
            "INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                (f"u{index}", f"req{index}", "openai", "gpt-a", 1, 2, 0, "0.125", None, (now - timedelta(minutes=index)).isoformat())
                for index in range(3)
            ],
        )
        db.executemany(
            "INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
            [
                (f"r{index}", f"req{index}", "openai", "gpt-a", str(index), "reserved", (now - timedelta(minutes=index)).isoformat())
                for index in range(3)
            ],
        )

    page = reservation_views(from_=now - timedelta(hours=1), to=now + timedelta(seconds=1), limit=1, offset=1)
    assert page["total"] == 3
    assert len(page["items"]) == 1
    assert page["items"][0]["id"] == "r1"

    with pytest.raises(AppException) as exc:
        usage_export_rows(from_=now - timedelta(hours=1), to=now + timedelta(seconds=1), max_rows=2)
    assert exc.value.code == "ADMIN_EXPORT_TOO_LARGE"

    rows = usage_export_rows(from_=now - timedelta(hours=1), to=now + timedelta(seconds=1), max_rows=3)
    assert rows[0]["cost_usd"] == "0.125000"
    csv_text = render_usage_csv([{**rows[0], "provider": "=formula"}])
    assert csv_text.startswith("\ufefftime,provider,")
    assert "'=formula" in csv_text


def test_retention_scopes_keep_live_sessions_locks_and_retryable_work(isolated_storage):
    from backend.app.repositories.database import connect, init_database, transaction
    from backend.app.services.admin_cleanup import run_cleanup

    now = datetime(2030, 1, 1, tzinfo=UTC)
    old = (now - timedelta(days=181)).isoformat()
    recent_session = (now - timedelta(hours=12)).isoformat()
    future = (now + timedelta(days=1)).isoformat()
    init_database()
    with transaction(immediate=True) as db:
        db.execute("INSERT INTO admin_users VALUES(?,?,?,?,?,?,?)", ("u", "admin", "hash", 1, old, old, None))
        db.executemany(
            "INSERT INTO admin_sessions(session_id,user_id,token_hash,csrf_token_created_at,created_at,last_activity_at,last_request_at,reauthenticated_at,idle_expires_at,absolute_expires_at,ip,user_agent_hash,revoked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("s-old", "u", "hash-old", old, old, old, old, None, old, future, None, None, old),
                ("s-recent", "u", "hash-recent", recent_session, recent_session, recent_session, recent_session, None, recent_session, future, None, None, recent_session),
                ("s-live", "u", "hash-live", recent_session, recent_session, recent_session, recent_session, None, future, future, None, None, None),
            ],
        )
        db.executemany(
            "INSERT INTO admin_login_throttles VALUES(?,?,?,?,?,?,?)",
            [
                ("t-old", "admin", "127.0.0.1", 1, old, None, old),
                ("t-locked", "admin", "127.0.0.2", 1, old, future, old),
                ("t-recent", "admin", "127.0.0.3", 1, recent_session, None, recent_session),
            ],
        )
        db.executemany(
            "INSERT INTO admin_operations(operation_id,actor_id,kind,scope,idempotency_key,request_hash,attempt_count,state,intended_json,result_json,error_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("op-success", "u", "dataset_delete", "ds", "k-success", "h", 1, "succeeded", "{}", "{}", None, old, old),
                ("op-retry", "u", "dataset_delete", "ds2", "k-retry", "h", 1, "failed", json.dumps({"dataset_id": "ds2"}), "{}", "TEMP", old, old),
            ],
        )

    result = run_cleanup(scopes=["admin_sessions", "throttles", "terminal_operations"], now=now)
    assert result["scopes"]["admin_sessions"]["succeeded"] == 1
    assert result["scopes"]["throttles"]["succeeded"] == 1
    assert result["scopes"]["terminal_operations"]["succeeded"] == 1
    with connect() as db:
        sessions = {row[0] for row in db.execute("SELECT session_id FROM admin_sessions")}
        throttles = {row[0] for row in db.execute("SELECT throttle_key FROM admin_login_throttles")}
        operations = {row[0] for row in db.execute("SELECT operation_id FROM admin_operations")}
    assert sessions == {"s-recent", "s-live"}
    assert throttles == {"t-locked", "t-recent"}
    assert operations == {"op-retry"}


def test_streamed_csv_matches_escaped_export_without_single_large_chunk():
    from backend.app.services.admin_metrics import render_usage_csv, stream_usage_csv
    rows = [{'provider': '=formula', 'model': 'sample', 'cost_usd': '0.000001'} for _ in range(1200)]
    chunks = list(stream_usage_csv(rows))
    assert len(chunks) == 4
    assert ''.join(chunks) == render_usage_csv(rows)
    assert "'=formula" in chunks[1]


def test_scheduled_cleanup_does_not_mutate_without_audit_intent(isolated_storage, monkeypatch):
    from backend.app.core.errors import AppException
    from backend.app.services import admin_cleanup, audit
    monkeypatch.setenv('ADMIN_ENABLED', 'true')
    touched = []
    def unavailable(**kwargs):
        raise RuntimeError('audit offline')
    monkeypatch.setattr(audit, 'record_audit', unavailable)
    monkeypatch.setattr(admin_cleanup, 'run_cleanup', lambda **kwargs: touched.append(kwargs))
    with pytest.raises(AppException) as caught:
        admin_cleanup.run_scheduled_cleanup()
    assert caught.value.code == 'AUDIT_UNAVAILABLE'
    assert touched == []
