from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _admin_env(monkeypatch, **overrides):
    values = {
        "ADMIN_ENABLED": "true",
        "ADMIN_BOOTSTRAP_USERNAME": "admin",
        "ADMIN_BOOTSTRAP_PASSWORD_HASH": "",
        "ADMIN_SESSION_IDLE_MINUTES": "30",
        "ADMIN_SESSION_ABSOLUTE_HOURS": "8",
        "ADMIN_LOGIN_RATE_PER_MINUTE": "5",
        "ADMIN_ALLOWED_IPS": "",
        "ADMIN_CSRF_TOKEN_TTL_MINUTES": "120",
        "ADMIN_MAX_SESSIONS": "20",
        "ENVIRONMENT": "development",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def admin_context(tmp_path, monkeypatch):
    from backend.app.core import config as core_config
    from backend.app.repositories import database

    monkeypatch.setattr(database, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "data" / "qcmaker.sqlite3")
    monkeypatch.setattr(core_config, "ENV_PATH", tmp_path / ".env")
    _admin_env(monkeypatch)
    database.init_database()
    from backend.app.core.admin_security import hash_password

    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD_HASH", hash_password("correct horse battery"))
    return tmp_path


def test_schema_migration_is_idempotent_and_has_security_constraints(admin_context):
    from backend.app.repositories.database import DB_PATH, init_database

    init_database()
    with sqlite3.connect(DB_PATH) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"schema_versions", "admin_users", "admin_sessions", "admin_login_throttles", "audit_logs", "operation_events", "admin_operations"} <= names
        assert db.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0] >= 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO admin_users(user_id,username,password_hash,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("u", "u", "x", "now", "now"),
            )
            db.execute(
                "INSERT INTO admin_users(user_id,username,password_hash,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("u2", "u2", "x", 2, "now", "now"),
            )


def test_bootstrap_creates_one_database_authoritative_user(admin_context, monkeypatch):
    from backend.app.core.admin_security import authenticate, init_admin

    status = init_admin()
    assert status.initialized is True
    assert authenticate("admin", "correct horse battery", source_ip="127.0.0.1").username == "admin"

    monkeypatch.setenv("ADMIN_BOOTSTRAP_USERNAME", "attacker")
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD_HASH", "pbkdf2_sha256$600000$bad$bad")
    init_admin()
    with pytest.raises(Exception):
        authenticate("attacker", "correct horse battery", source_ip="127.0.0.1")
    assert authenticate("admin", "correct horse battery", source_ip="127.0.0.1").username == "admin"


def test_missing_or_invalid_bootstrap_never_creates_partial_user(admin_context, monkeypatch):
    from backend.app.core.admin_security import AdminSecurityError, init_admin
    from backend.app.repositories import database

    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD_HASH", "")
    with pytest.raises(AdminSecurityError) as exc:
        init_admin()
    assert exc.value.code == "ADMIN_NOT_INITIALIZED"
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0] == 0


def test_password_hash_enforces_pbkdf2_policy(admin_context):
    from backend.app.core.admin_security import hash_password, verify_password

    with pytest.raises(ValueError):
        hash_password("short")
    encoded = hash_password("a sufficiently long password")
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert verify_password("a sufficiently long password", encoded)
    assert not verify_password("a different sufficiently long password", encoded)


def test_auth_router_sets_scoped_secure_session_and_requires_csrf(admin_context):
    from backend.app.api.endpoints.admin.auth import router
    from backend.app.core.admin_security import init_admin
    from backend.app.core.errors import install_error_handlers

    init_admin()
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")
    install_error_handlers(app)
    with TestClient(app, base_url="http://testserver") as client:
        response = client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "correct horse battery"},
            headers={"Origin": "http://testserver", "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "Path=/api/admin" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        csrf = response.json()["csrf_token"]
        assert client.get("/api/admin/auth/me").status_code == 200
        assert client.post("/api/admin/auth/activity", json={}, headers={"Origin": "http://testserver"}).status_code == 403
        assert client.post(
            "/api/admin/auth/activity",
            json={},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        ).status_code == 200


def test_csrf_is_bound_to_session_and_me_refreshes_expired_token(admin_context, monkeypatch):
    from backend.app.api.endpoints.admin.auth import router
    from backend.app.core.admin_security import init_admin
    from backend.app.core.errors import install_error_handlers
    from backend.app.repositories.database import transaction

    init_admin()
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")
    install_error_handlers(app)
    with TestClient(app, base_url="http://testserver") as first, TestClient(app, base_url="http://testserver") as second:
        headers = {"Origin": "http://testserver", "Content-Type": "application/json"}
        one = first.post("/api/admin/auth/login", json={"username": "admin", "password": "correct horse battery"}, headers=headers)
        two = second.post("/api/admin/auth/login", json={"username": "admin", "password": "correct horse battery"}, headers=headers)
        assert one.status_code == two.status_code == 200
        csrf_one = one.json()["csrf_token"]
        csrf_two = two.json()["csrf_token"]
        assert csrf_one != csrf_two
        denied = first.post("/api/admin/auth/activity", json={}, headers={"Origin": "http://testserver", "X-CSRF-Token": csrf_two})
        assert denied.status_code == 403

        with transaction(immediate=True) as db:
            db.execute("UPDATE admin_sessions SET csrf_token_created_at=?", ((datetime.now(UTC) - timedelta(hours=3)).isoformat(),))
        refreshed = first.get("/api/admin/auth/me")
        assert refreshed.status_code == 200
        assert refreshed.json()["csrf_token"] != csrf_one
        assert first.post("/api/admin/auth/activity", json={}, headers={"Origin": "http://testserver", "X-CSRF-Token": csrf_one}).status_code == 403


def test_idle_activity_does_not_extend_absolute_expiry(admin_context):
    from backend.app.core.admin_security import authenticate, validate_session
    from backend.app.repositories.database import transaction

    principal = authenticate("admin", "correct horse battery", source_ip="127.0.0.1")
    with transaction(immediate=True) as db:
        row = db.execute("SELECT session_id FROM admin_sessions WHERE user_id=?", (principal.user_id,)).fetchone()
        db.execute(
            "UPDATE admin_sessions SET last_activity_at=?, idle_expires_at=?, absolute_expires_at=? WHERE session_id=?",
            ((datetime.now(UTC) - timedelta(minutes=31)).isoformat(), (datetime.now(UTC) - timedelta(minutes=1)).isoformat(), (datetime.now(UTC) + timedelta(hours=1)).isoformat(), row[0]),
        )
    with pytest.raises(Exception) as exc:
        validate_session(principal.session_secret)
    assert getattr(exc.value, "code", None) == "ADMIN_SESSION_EXPIRED"


def test_login_failures_are_durable_and_lock_account_ip(admin_context, monkeypatch):
    from backend.app.core.admin_security import AdminRateLimitError, authenticate

    monkeypatch.setenv("ADMIN_LOGIN_RATE_PER_MINUTE", "100")
    for _ in range(9):
        with pytest.raises(Exception):
            authenticate("admin", "wrong password here", source_ip="127.0.0.1")
    with pytest.raises(AdminRateLimitError) as exc:
        authenticate("admin", "wrong password here", source_ip="127.0.0.1")
    assert exc.value.code == "ADMIN_LOGIN_LOCKED"


def test_change_password_revokes_every_session_atomically(admin_context):
    from backend.app.core.admin_security import authenticate, change_password
    from backend.app.repositories.database import connect

    first = authenticate("admin", "correct horse battery", source_ip="127.0.0.1")
    authenticate("admin", "correct horse battery", source_ip="127.0.0.1")
    result = change_password(first, "correct horse battery", "new secure password", reason="rotation")
    assert result.relogin_required is True
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM admin_sessions WHERE revoked_at IS NULL").fetchone()[0] == 0
    with pytest.raises(Exception):
        authenticate("admin", "correct horse battery", source_ip="127.0.0.1")
    assert authenticate("admin", "new secure password", source_ip="127.0.0.1").username == "admin"


def test_operation_intent_and_audit_commit_together(admin_context):
    from backend.app.services.admin_operations import begin_operation, complete_operation, get_operation
    from backend.app.services.audit import list_audit_logs

    operation = begin_operation(actor_id="u", actor_name="admin", kind="dataset_delete", scope="dataset:x", intended={"dataset_id": "x"}, request_id="req-1", idempotency_key="idem-1")
    assert operation.state == "pending"
    assert complete_operation(operation.operation_id, actor_id="u", actor_name="admin", request_id="req-2", result={"deleted": True}).state == "succeeded"
    assert get_operation(operation.operation_id).result["deleted"] is True
    actions = [item["action"] for item in list_audit_logs(limit=20)]
    assert actions[:2] == ["DATASET_DELETE", "DATASET_DELETE"]


def test_operation_digest_distinguishes_redacted_values_and_rejects_oversized_lists(admin_context):
    from backend.app.services.admin_operations import request_digest

    first = request_digest(kind="token_rotate", scope="settings", intended={"token": "first-secret"})
    second = request_digest(kind="token_rotate", scope="settings", intended={"token": "second-secret"})
    assert first != second
    with pytest.raises(ValueError):
        request_digest(kind="dataset_delete", scope="datasets", intended={"dataset_ids": ["x"] * 100_000})


def test_audit_retention_persists_intent_and_terminal_result(admin_context):
    from backend.app.repositories import database
    from backend.app.services.audit import list_audit_logs, purge_retention, record_audit_tx

    now = datetime(2030, 1, 1, tzinfo=UTC)
    old = (now - timedelta(days=181)).isoformat()
    retained = (now - timedelta(days=1)).isoformat()
    with database.transaction(immediate=True) as db:
        record_audit_tx(db, action="MAINTENANCE_RUN", actor_id="u", actor_name="admin", request_id="old", created_at=old)
        record_audit_tx(db, action="MAINTENANCE_RUN", actor_id="u", actor_name="admin", request_id="recent", created_at=retained)

    stat = purge_retention(now=now)
    assert stat["attempted"] == stat["succeeded"] == 1
    rows = list_audit_logs(limit=20)
    assert {row["request_id"] for row in rows} >= {"recent"}
    retention_rows = [row for row in rows if row["action"] == "AUDIT_RETENTION_PURGE"]
    assert {row["result"] for row in retention_rows} == {"REQUESTED", "SUCCEEDED"}
    assert all(row["request_id"] != "old" for row in rows)


def test_audit_retention_rolls_back_delete_when_terminal_audit_fails(admin_context, monkeypatch):
    from backend.app.repositories import database
    from backend.app.services import audit

    now = datetime(2030, 1, 1, tzinfo=UTC)
    old = (now - timedelta(days=181)).isoformat()
    with database.transaction(immediate=True) as db:
        audit.record_audit_tx(db, action="MAINTENANCE_RUN", actor_id="u", actor_name="admin", request_id="old", created_at=old)

    original = audit.record_audit_tx

    def fail_success(db, **kwargs):
        if kwargs.get("result") == "SUCCEEDED":
            raise RuntimeError("terminal audit unavailable")
        return original(db, **kwargs)

    monkeypatch.setattr(audit, "record_audit_tx", fail_success)
    stat = audit.purge_retention(now=now)
    assert stat["failed"] == stat["attempted"] == 1
    assert stat["succeeded"] == 0
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE request_id='old'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE result='FAILED'").fetchone()[0] == 1


def test_operation_retry_reuses_original_id_and_retry_key_atomically(admin_context):
    from backend.app.services.admin_operations import begin_operation, complete_operation, retry_operation
    from backend.app.services.audit import list_audit_logs

    operation = begin_operation(
        actor_id="u",
        actor_name="admin",
        kind="dataset_delete",
        scope="dataset:x",
        intended={"dataset_id": "x"},
        request_id="req-1",
        idempotency_key="idem-1",
    )
    complete_operation(operation.operation_id, actor_id="u", actor_name="admin", request_id="req-2", state="failed", error_code="TEMP")
    retry = retry_operation(operation.operation_id, actor_id="u", actor_name="admin", request_id="req-retry", retry_key="retry-1", reason="再试")
    assert retry.operation_id == operation.operation_id
    assert retry.state == "running"
    assert retry.attempt_count == 1
    replay = retry_operation(operation.operation_id, actor_id="u", actor_name="admin", request_id="req-replay", retry_key="retry-1")
    assert replay.operation_id == retry.operation_id and replay.attempt_count == 1
    with pytest.raises(Exception) as exc:
        retry_operation(operation.operation_id, actor_id="other", actor_name="other", request_id="req-other", retry_key="retry-2")
    assert getattr(exc.value, "code", None) == "ADMIN_OPERATION_FORBIDDEN"
    retry_audits = [item for item in list_audit_logs(limit=20) if item["operation_id"] == operation.operation_id and item["result"] == "REQUESTED" and item["detail"].get("retry")]
    assert len(retry_audits) == 1


def test_operation_retry_audit_failure_rolls_back_attempt_and_state(admin_context, monkeypatch):
    from backend.app.services import admin_operations

    operation = admin_operations.begin_operation(
        actor_id="u",
        actor_name="admin",
        kind="dataset_delete",
        scope="dataset:x",
        intended={"dataset_id": "x"},
        request_id="req-1",
        idempotency_key="idem-1",
    )
    admin_operations.complete_operation(operation.operation_id, actor_id="u", actor_name="admin", request_id="req-2", state="failed", error_code="TEMP")
    original = admin_operations.record_audit_tx

    def fail_retry_audit(db, **kwargs):
        if kwargs.get("result") == "REQUESTED" and kwargs.get("operation_id") == operation.operation_id:
            raise RuntimeError("audit unavailable")
        return original(db, **kwargs)

    monkeypatch.setattr(admin_operations, "record_audit_tx", fail_retry_audit)
    with pytest.raises(RuntimeError):
        admin_operations.retry_operation(operation.operation_id, actor_id="u", actor_name="admin", request_id="req-retry", retry_key="retry-1")
    current = admin_operations.get_operation(operation.operation_id)
    assert current.state == "failed" and current.attempt_count == 0
    with admin_operations.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM admin_operation_attempts WHERE operation_id=?", (operation.operation_id,)).fetchone()[0] == 0


def test_operation_retryable_matches_supported_admin_retry_kinds(admin_context):
    from backend.app.services import admin_operations

    for kind, expected in {
        "llm_probe": False,
        "audit_retention_purge": False,
        "config_update": False,
        "access_token_rotate": False,
        "dataset_delete": True,
        "maintenance": True,
    }.items():
        operation = admin_operations.begin_operation(
            actor_id="u",
            actor_name="admin",
            kind=kind,
            scope="test",
            intended={"kind": kind},
            request_id=f"req-{kind}",
            idempotency_key=f"idem-{kind}",
        )
        operation = admin_operations.complete_operation(
            operation.operation_id,
            actor_id="u",
            actor_name="admin",
            request_id=f"done-{kind}",
            state="failed",
            error_code="TEMP",
        )
        assert operation.retryable is expected
