from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Iterator

from backend.app.core.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "backend" / "data"
DB_PATH = DATA_DIR / "qcmaker.sqlite3"


_BUSINESS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS datasets(dataset_id TEXT PRIMARY KEY,filename TEXT NOT NULL,revision INTEGER NOT NULL,confirmed_revision INTEGER,raw_rows_json TEXT NOT NULL,current_rows_json TEXT NOT NULL,columns_json TEXT NOT NULL,report_json TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,reserved_usd TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,input_tokens INTEGER NOT NULL,output_tokens INTEGER NOT NULL,embedding_tokens INTEGER NOT NULL,cost_usd TEXT NOT NULL,price_effective_from TEXT,created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS files(file_id TEXT PRIMARY KEY,display_name TEXT NOT NULL,disk_path TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS discussion_sessions(session_id TEXT PRIMARY KEY,status TEXT NOT NULL,state_json TEXT NOT NULL,next_event_seq INTEGER NOT NULL,lease_owner TEXT,lease_generation INTEGER NOT NULL DEFAULT 0,lease_until TEXT,expires_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS discussion_commands(session_id TEXT NOT NULL,client_message_id TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL,picked_at TEXT,completed_at TEXT,error_json TEXT,PRIMARY KEY(session_id,client_message_id))",
    "CREATE TABLE IF NOT EXISTS discussion_events(session_id TEXT NOT NULL,event_seq INTEGER NOT NULL,client_message_id TEXT,event_type TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(session_id,event_seq))",
    "CREATE TABLE IF NOT EXISTS llm_operations(operation_id TEXT PRIMARY KEY,status TEXT NOT NULL,response_json TEXT,usage_id TEXT)",
)


_ADMIN_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS admin_users(
        user_id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS admin_sessions(
        session_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES admin_users(user_id),
        token_hash TEXT NOT NULL UNIQUE,
        csrf_token_created_at TEXT NOT NULL,
        csrf_key_version INTEGER NOT NULL DEFAULT 1,
        csrf_generation INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_activity_at TEXT NOT NULL,
        last_request_at TEXT NOT NULL,
        reauthenticated_at TEXT,
        idle_expires_at TEXT NOT NULL,
        absolute_expires_at TEXT NOT NULL,
        ip TEXT,
        user_agent_hash TEXT,
        revoked_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS admin_login_throttles(
        throttle_key TEXT PRIMARY KEY,
        account_key TEXT NOT NULL,
        source_ip TEXT NOT NULL,
        failure_count INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
        window_started_at TEXT NOT NULL,
        locked_until TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_logs(
        id TEXT PRIMARY KEY,
        actor_id TEXT,
        actor_name TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN (
            'LOGIN_SUCCESS','LOGIN_FAILURE','LOGIN_LOCKED','LOGOUT',
            'SESSION_REVOKE','SESSION_REVOKE_ALL','ADMIN_PASSWORD_CHANGE',
            'CONFIG_UPDATE','ACCESS_TOKEN_ROTATE','OVERRUN_RESET',
            'BUDGET_LIMIT_UPDATE','MAINTENANCE_RUN','DATASET_DELETE',
            'DATASET_PURGE_EXPIRED','DISCUSSION_LEASE_RECOVER',
            'DISCUSSION_FORCE_END','FILE_DELETE','PPT_DELETE',
            'RAG_DOCUMENT_DELETE','RAG_PROJECT_PURGE','AUDIT_RETENTION_PURGE',
            'LLM_PROBE','ADMIN_LOCAL_RECOVERY'
        )),
        target_type TEXT,
        target_id TEXT,
        request_id TEXT NOT NULL,
        operation_id TEXT,
        result TEXT NOT NULL CHECK(result IN ('REQUESTED','SUCCEEDED','PARTIAL','FAILED','DENIED')),
        error_code TEXT,
        reason TEXT,
        before_summary TEXT,
        after_summary TEXT,
        detail_json TEXT CHECK(detail_json IS NULL OR length(detail_json) <= 4096),
        ip TEXT,
        user_agent_hash TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS operation_events(
        id TEXT PRIMARY KEY,
        level TEXT NOT NULL CHECK(level IN ('info','warning','error')),
        category TEXT NOT NULL CHECK(category IN (
            'usage','maintenance','discussion','ppt','rag','config','security','system'
        )),
        event_key TEXT NOT NULL,
        message TEXT NOT NULL,
        operation_id TEXT,
        context_json TEXT CHECK(context_json IS NULL OR length(context_json) <= 4096),
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS admin_operations(
        operation_id TEXT PRIMARY KEY,
        actor_id TEXT,
        kind TEXT NOT NULL,
        scope TEXT NOT NULL,
        idempotency_key TEXT,
        request_hash TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
        state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','partial','failed','cancelled')),
        intended_json TEXT NOT NULL CHECK(length(intended_json) <= 65536),
        result_json TEXT CHECK(result_json IS NULL OR length(result_json) <= 65536),
        error_code TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(actor_id,kind,idempotency_key)
    )""",
    """CREATE TABLE IF NOT EXISTS admin_operation_attempts(
        attempt_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES admin_operations(operation_id),
        actor_id TEXT NOT NULL,
        retry_key_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(operation_id,retry_key_hash)
    )""",
    """CREATE TABLE IF NOT EXISTS admin_security_meta(
        meta_key TEXT PRIMARY KEY,
        meta_value TEXT NOT NULL
    )""",
)


_ADMIN_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_admin_sessions_user_revoked ON admin_sessions(user_id,revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_sessions_revoked_absolute ON admin_sessions(revoked_at,absolute_expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_sessions_activity ON admin_sessions(last_activity_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_throttle_ip_updated ON admin_login_throttles(source_ip,updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_throttle_account_updated ON admin_login_throttles(account_key,updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC,id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_action_created ON audit_logs(action,created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor_created ON audit_logs(actor_id,created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_logs(request_id)",
    "CREATE INDEX IF NOT EXISTS idx_operation_events_created ON operation_events(created_at DESC,id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_operation_events_category ON operation_events(category,created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_admin_operations_state ON admin_operations(state,updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_admin_operations_actor_created ON admin_operations(actor_id,created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_admin_operation_attempts_operation ON admin_operation_attempts(operation_id,created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_datasets_expiry ON datasets(expires_at,dataset_id)",
    "CREATE INDEX IF NOT EXISTS idx_datasets_created ON datasets(created_at DESC,dataset_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_discussion_sessions_status_expiry ON discussion_sessions(status,expires_at,session_id)",
    "CREATE INDEX IF NOT EXISTS idx_discussion_commands_session_status ON discussion_commands(session_id,status)",
    "CREATE INDEX IF NOT EXISTS idx_discussion_events_session_seq ON discussion_events(session_id,event_seq)",
    "CREATE INDEX IF NOT EXISTS idx_files_expiry ON files(expires_at,file_id)",
    "CREATE INDEX IF NOT EXISTS idx_usage_created_provider_model ON usage_events(created_at,provider,model)",
    "CREATE INDEX IF NOT EXISTS idx_reservations_status_created ON reservations(status,created_at,id)",
)


_SCHEMA_VERSION = 1
_SCHEMA_MIGRATION_SQL = "\n".join((*_BUSINESS_SCHEMA, *_ADMIN_SCHEMA, *_ADMIN_INDEXES))
_SCHEMA_CHECKSUM = sha256(_SCHEMA_MIGRATION_SQL.encode("utf-8")).hexdigest()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def transaction(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database() -> None:
    with transaction(immediate=True) as db:
        # ``executescript`` implicitly commits an active transaction in the
        # stdlib sqlite driver.  Migrations are therefore executed one
        # statement at a time so a failed schema change cannot leave a partly
        # installed management surface behind.
        db.execute("CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)")
        applied = {int(row[0]): row[2] for row in db.execute("SELECT version, applied_at, checksum FROM schema_versions")}
        unsupported = sorted(version for version in applied if version > _SCHEMA_VERSION)
        if unsupported:
            raise RuntimeError(f"unsupported database schema version(s): {unsupported}")
        if _SCHEMA_VERSION in applied:
            if applied[_SCHEMA_VERSION] != _SCHEMA_CHECKSUM:
                raise RuntimeError(f"schema version {_SCHEMA_VERSION} checksum mismatch")
            # CREATE IF NOT EXISTS keeps a previously committed v1 database
            # self-healing if an operator restored only part of a snapshot.
            # The checksum gate above still rejects software/schema drift.
            for statement in (*_BUSINESS_SCHEMA, *_ADMIN_SCHEMA, *_ADMIN_INDEXES):
                db.execute(statement)
            return
        for statement in (*_BUSINESS_SCHEMA, *_ADMIN_SCHEMA, *_ADMIN_INDEXES):
            db.execute(statement)
        db.execute(
            "INSERT INTO schema_versions(version,applied_at,checksum) VALUES(?,?,?)",
            (_SCHEMA_VERSION, datetime.now(UTC).isoformat(), _SCHEMA_CHECKSUM),
        )

