"""Database backed audit and operations event primitives.

Audit writes are intentionally small, allow-listed, and accept an existing
SQLite connection.  Callers that change business state can therefore write
the audit row in the same ``BEGIN IMMEDIATE`` transaction.  If the insert
fails, the caller's transaction fails too.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from backend.app.repositories.database import transaction

AuditAction = Literal[
    "LOGIN_SUCCESS",
    "LOGIN_FAILURE",
    "LOGIN_LOCKED",
    "LOGOUT",
    "SESSION_REVOKE",
    "SESSION_REVOKE_ALL",
    "ADMIN_PASSWORD_CHANGE",
    "CONFIG_UPDATE",
    "ACCESS_TOKEN_ROTATE",
    "OVERRUN_RESET",
    "BUDGET_LIMIT_UPDATE",
    "MAINTENANCE_RUN",
    "DATASET_DELETE",
    "DATASET_PURGE_EXPIRED",
    "DISCUSSION_LEASE_RECOVER",
    "DISCUSSION_FORCE_END",
    "FILE_DELETE",
    "PPT_DELETE",
    "RAG_DOCUMENT_DELETE",
    "RAG_PROJECT_PURGE",
    "AUDIT_RETENTION_PURGE",
    "LLM_PROBE",
    "ADMIN_LOCAL_RECOVERY",
]
AuditResult = Literal["REQUESTED", "SUCCEEDED", "PARTIAL", "FAILED", "DENIED"]

ALLOWED_ACTIONS = frozenset(
    {
        "LOGIN_SUCCESS",
        "LOGIN_FAILURE",
        "LOGIN_LOCKED",
        "LOGOUT",
        "SESSION_REVOKE",
        "SESSION_REVOKE_ALL",
        "ADMIN_PASSWORD_CHANGE",
        "CONFIG_UPDATE",
        "ACCESS_TOKEN_ROTATE",
        "OVERRUN_RESET",
        "BUDGET_LIMIT_UPDATE",
        "MAINTENANCE_RUN",
        "DATASET_DELETE",
        "DATASET_PURGE_EXPIRED",
        "DISCUSSION_LEASE_RECOVER",
        "DISCUSSION_FORCE_END",
        "FILE_DELETE",
        "PPT_DELETE",
        "RAG_DOCUMENT_DELETE",
        "RAG_PROJECT_PURGE",
        "AUDIT_RETENTION_PURGE",
        "LLM_PROBE",
        "ADMIN_LOCAL_RECOVERY",
    }
)
ALLOWED_RESULTS = frozenset({"REQUESTED", "SUCCEEDED", "PARTIAL", "FAILED", "DENIED"})
ALLOWED_EVENT_LEVELS = frozenset({"info", "warning", "error"})
ALLOWED_EVENT_CATEGORIES = frozenset({"usage", "maintenance", "discussion", "ppt", "rag", "config", "security", "system"})

_SENSITIVE_KEY = re.compile(
    r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|raw[_-]?rows?|current[_-]?rows?|request[_-]?body|private[_-]?key|access[_-]?token|metadata)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|sk-[a-z0-9_-]{4,}|(?:api[_-]?key|token|password|secret|cookie)\s*[:=]\s*\S+)"
)
_MAX_DETAIL_BYTES = 4096
_MAX_OPERATION_BYTES = 65536


def hash_user_agent(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    return hashlib.sha256(user_agent.encode("utf-8", "replace")).hexdigest()


def _redact_text(value: str, max_length: int = 1000) -> str:
    from backend.app.services.admin_redaction import redact_admin_text
    value = redact_admin_text(value, max_length=max_length)
    value = _SECRET_VALUE.sub("[REDACTED]", value)
    value = value.replace("\x00", "")
    return value[:max_length]


def sanitize_summary(value: Any, *, max_bytes: int = _MAX_DETAIL_BYTES) -> Any:
    """Return a JSON-safe summary with secret-shaped fields redacted.

    This helper is intentionally conservative: keys that can carry a secret
    are retained only as ``[REDACTED]`` and long values are bounded.  It is
    used for audit details, event context, operation intents, and results.
    """

    def clean(item: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[REDACTED_DEPTH]"
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for raw_key, raw_value in item.items():
                key = _redact_text(str(raw_key), 120)
                if _SENSITIVE_KEY.search(key):
                    result[key] = "[REDACTED]"
                else:
                    result[key] = clean(raw_value, depth + 1)
            return result
        if isinstance(item, (list, tuple, set)):
            return [clean(entry, depth + 1) for entry in list(item)[:200]]
        if isinstance(item, bool) or item is None or isinstance(item, (int, float)):
            return item
        if isinstance(item, (datetime,)):
            return item.astimezone(UTC).isoformat()
        return _redact_text(str(item))

    cleaned = clean(value)
    try:
        encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        cleaned = {"value": "[REDACTED_UNSERIALIZABLE]"}
        encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= max_bytes:
        return cleaned
    return {"truncated": True, "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def encode_summary(value: Any, *, max_bytes: int = _MAX_DETAIL_BYTES) -> str:
    safe = sanitize_summary(value, max_bytes=max_bytes)
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > max_bytes:
        # sanitize_summary returns a compact digest when this happens.  Keep
        # the final guard here as protection if a caller supplies a custom
        # JSON encoder in the future.
        encoded = json.dumps({"truncated": True, "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}, separators=(",", ":"))
    return encoded


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_audit_tx(
    db,
    *,
    action: str,
    actor_id: str | None,
    actor_name: str,
    request_id: str,
    operation_id: str | None = None,
    result: str = "SUCCEEDED",
    target_type: str | None = None,
    target_id: str | None = None,
    error_code: str | None = None,
    reason: str | None = None,
    before_summary: Any = None,
    after_summary: Any = None,
    detail: Any = None,
    ip: str | None = None,
    user_agent: str | None = None,
    user_agent_hash: str | None = None,
    created_at: str | None = None,
) -> str:
    """Insert an audit row on an existing transaction.

    ``sqlite3`` errors intentionally propagate so sensitive state changes
    using this function roll back together with the failed audit write.
    """

    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported audit action: {action}")
    if result not in ALLOWED_RESULTS:
        raise ValueError(f"unsupported audit result: {result}")
    if not request_id or not actor_name:
        raise ValueError("audit actor_name and request_id are required")
    audit_id = f"audit_{uuid4().hex}"
    detail_json = encode_summary(detail, max_bytes=_MAX_DETAIL_BYTES) if detail is not None else None
    before_json = encode_summary(before_summary, max_bytes=_MAX_DETAIL_BYTES) if before_summary is not None else None
    after_json = encode_summary(after_summary, max_bytes=_MAX_DETAIL_BYTES) if after_summary is not None else None
    db.execute(
        """INSERT INTO audit_logs(
            id, actor_id, actor_name, action, target_type, target_id,
            request_id, operation_id, result, error_code, reason,
            before_summary, after_summary, detail_json, ip, user_agent_hash,
            created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            audit_id,
            actor_id,
            _redact_text(actor_name, 128),
            action,
            _redact_text(target_type, 120) if target_type else None,
            _redact_text(target_id, 256) if target_id else None,
            _redact_text(request_id, 128),
            _redact_text(operation_id, 128) if operation_id else None,
            result,
            _redact_text(error_code, 120) if error_code else None,
            _redact_text(reason, 500) if reason else None,
            before_json,
            after_json,
            detail_json,
            _redact_text(ip, 128) if ip else None,
            user_agent_hash or hash_user_agent(user_agent),
            created_at or _now(),
        ),
    )
    return audit_id


def record_audit(**kwargs: Any) -> str:
    """Insert one audit row in a new immediate transaction."""

    with transaction(immediate=True) as db:
        return record_audit_tx(db, **kwargs)


def _row_to_audit(row: Any) -> dict[str, Any]:
    result = dict(row)
    for field in ("before_summary", "after_summary", "detail_json"):
        raw = result.pop(field, None)
        if raw:
            try:
                result[field.removesuffix("_json")] = sanitize_summary(json.loads(raw), max_bytes=_MAX_DETAIL_BYTES)
            except (TypeError, ValueError):
                result[field.removesuffix("_json")] = {"truncated": True}
        else:
            result[field.removesuffix("_json")] = None
    return result


def _audit_filter(action: str | None, actor_id: str | None, actor: str | None, result: str | None, date_from: str | None, date_to: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if action:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported audit action: {action}")
        clauses.append("action=?"); params.append(action)
    if actor_id:
        clauses.append("actor_id=?"); params.append(actor_id)
    if actor:
        clauses.append("actor_name LIKE ?"); params.append(f"%{_redact_text(actor, 128)}%")
    if result:
        if result not in ALLOWED_RESULTS:
            raise ValueError(f"unsupported audit result: {result}")
        clauses.append("result=?"); params.append(result)
    if date_from:
        clauses.append("created_at>=?"); params.append(date_from)
    if date_to:
        clauses.append("created_at<?"); params.append(date_to)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else "", params)


def list_audit_logs(
    *,
    action: str | None = None,
    actor_id: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where, params = _audit_filter(action, actor_id, actor, result, date_from, date_to)
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM audit_logs{where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return [_row_to_audit(row) for row in rows]


def query_audit_logs(**kwargs: Any) -> dict[str, Any]:
    limit = max(1, min(int(kwargs.pop("limit", 100)), 200))
    offset = max(0, int(kwargs.pop("offset", 0)))
    items = list_audit_logs(limit=limit, offset=offset, **kwargs)
    where, params = _audit_filter(kwargs.get("action"), kwargs.get("actor_id"), kwargs.get("actor"), kwargs.get("result"), kwargs.get("date_from"), kwargs.get("date_to"))
    # The count query uses the same predicates as the page query so total is
    # meaningful for filtered admin audit views.
    with transaction() as db:
        row = db.execute(f"SELECT COUNT(*) FROM audit_logs{where}", params).fetchone()
    return {"items": items, "total": int(row[0]), "limit": limit, "offset": offset, "total_is_estimate": False}


def _retention_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _retention_stat() -> dict[str, Any]:
    return {"attempted": 0, "succeeded": 0, "skipped": 0, "failed": 0, "unknown": 0, "errors": []}


def purge_retention(*, dry_run: bool = False, now: datetime | None = None, retention_days: int = 180) -> dict[str, Any]:
    """Purge old audit rows with a durable intent and terminal audit result.

    The cutoff is captured before the REQUESTED row is written. The intent is
    committed first, then the fixed set of eligible rows is deleted and the
    SUCCEEDED result is inserted in the same transaction as that deletion.
    If deletion or its terminal audit write fails, the delete transaction is
    rolled back and a FAILED result is attempted in a separate transaction;
    the function never reports a successful purge after an audit failure.
    """

    try:
        retention = max(1, int(retention_days))
    except (TypeError, ValueError) as exc:
        raise ValueError("retention_days must be a positive integer") from exc
    current = _retention_now(now)
    current_iso = current.isoformat()
    cutoff = (current - timedelta(days=retention)).isoformat()
    request_id = f"maintenance_audit_{uuid4().hex}"
    target_id = f"older_than_{retention}d"
    stat = _retention_stat()

    try:
        with transaction() as db:
            table_exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_logs'").fetchone() is not None
            if not table_exists:
                stat["unknown"] = 1
                stat["errors"].append({"error": "AUDIT_TABLE_UNAVAILABLE"})
                return stat
            candidate = int(db.execute("SELECT COUNT(*) FROM audit_logs WHERE created_at<?", (cutoff,)).fetchone()[0])
    except Exception as exc:
        stat["unknown"] = 1
        stat["errors"].append({"error": type(exc).__name__})
        return stat

    stat["attempted"] = candidate
    if dry_run:
        stat["succeeded"] = candidate
        return stat

    request_detail = {"retention_days": retention, "cutoff": cutoff, "candidate_count": candidate}
    try:
        # Persist the intent before any row can be deleted. Its timestamp is
        # the captured task time, which is newer than the fixed cutoff even
        # when tests supply a synthetic ``now`` value.
        with transaction(immediate=True) as db:
            record_audit_tx(
                db,
                action="AUDIT_RETENTION_PURGE",
                actor_id="system",
                actor_name="system",
                request_id=request_id,
                result="REQUESTED",
                target_type="audit_logs",
                target_id=target_id,
                detail=request_detail,
                created_at=current_iso,
            )
    except Exception as exc:
        # No deletion was attempted. A second write is best effort because
        # the first audit failure may mean the database is unavailable; the
        # unknown count prevents a caller from presenting a false success.
        stat["unknown"] = candidate
        stat["errors"].append({"error": type(exc).__name__, "phase": "request"})
        return stat

    try:
        with transaction(immediate=True) as db:
            # Recount under the deletion lock so rows inserted after the
            # intent are included while the cutoff remains unchanged.
            stat["attempted"] = int(db.execute("SELECT COUNT(*) FROM audit_logs WHERE created_at<?", (cutoff,)).fetchone()[0])
            deleted = int(db.execute("DELETE FROM audit_logs WHERE created_at<?", (cutoff,)).rowcount)
            record_audit_tx(
                db,
                action="AUDIT_RETENTION_PURGE",
                actor_id="system",
                actor_name="system",
                request_id=request_id,
                result="SUCCEEDED",
                target_type="audit_logs",
                target_id=target_id,
                after_summary={"deleted_count": deleted, "cutoff": cutoff, "retention_days": retention},
                created_at=current_iso,
            )
            stat["succeeded"] = max(0, deleted)
    except Exception as exc:
        # The transaction context rolls the delete back, so no old row is
        # lost when the terminal audit insert cannot be made.
        attempted = int(stat["attempted"])
        stat["succeeded"] = 0
        stat["failed"] = attempted
        stat["errors"].append({"error": type(exc).__name__, "phase": "delete"})
        try:
            with transaction(immediate=True) as db:
                record_audit_tx(
                    db,
                    action="AUDIT_RETENTION_PURGE",
                    actor_id="system",
                    actor_name="system",
                    request_id=request_id,
                    result="FAILED",
                    target_type="audit_logs",
                    target_id=target_id,
                    error_code="AUDIT_RETENTION_FAILED",
                    reason="audit retention deletion rolled back",
                    after_summary={"deleted_count": 0, "cutoff": cutoff, "retention_days": retention},
                    created_at=current_iso,
                )
        except Exception as terminal_exc:
            stat["unknown"] = attempted
            stat["errors"].append({"error": type(terminal_exc).__name__, "phase": "failure_audit"})
    return stat


def record_operation_event_tx(
    db,
    *,
    level: str,
    category: str,
    event_key: str,
    message: str,
    operation_id: str | None = None,
    context: Any = None,
    created_at: str | None = None,
) -> str:
    if level not in ALLOWED_EVENT_LEVELS:
        raise ValueError(f"unsupported event level: {level}")
    if category not in ALLOWED_EVENT_CATEGORIES:
        raise ValueError(f"unsupported event category: {category}")
    event_id = f"event_{uuid4().hex}"
    context_json = encode_summary(context, max_bytes=_MAX_DETAIL_BYTES) if context is not None else None
    db.execute(
        "INSERT INTO operation_events(id,level,category,event_key,message,operation_id,context_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (event_id, level, category, _redact_text(event_key, 160), _redact_text(message, 1000), operation_id, context_json, created_at or _now()),
    )
    return event_id


def record_operation_event(**kwargs: Any) -> str:
    best_effort = bool(kwargs.pop("best_effort", False))
    try:
        with transaction(immediate=True) as db:
            return record_operation_event_tx(db, **kwargs)
    except Exception:
        if best_effort:
            return ""
        raise


__all__ = [
    "ALLOWED_ACTIONS",
    "ALLOWED_RESULTS",
    "AuditAction",
    "AuditResult",
    "encode_summary",
    "hash_user_agent",
    "list_audit_logs",
    "purge_retention",
    "query_audit_logs",
    "record_audit",
    "record_audit_tx",
    "record_operation_event",
    "record_operation_event_tx",
    "sanitize_summary",
]
