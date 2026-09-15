"""Idempotent operation-intent and compensation bookkeeping for admin writes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.core.errors import AppException
from backend.app.repositories.database import transaction
from backend.app.services.audit import record_audit_tx, record_operation_event_tx

_KIND_ACTIONS = {
    "dataset_delete": "DATASET_DELETE",
    "dataset_purge": "DATASET_PURGE_EXPIRED",
    "discussion_lease_recover": "DISCUSSION_LEASE_RECOVER",
    "discussion_force_end": "DISCUSSION_FORCE_END",
    "file_delete": "FILE_DELETE",
    "ppt_delete": "PPT_DELETE",
    "rag_document_delete": "RAG_DOCUMENT_DELETE",
    "rag_project_purge": "RAG_PROJECT_PURGE",
    "maintenance": "MAINTENANCE_RUN",
    "maintenance_run": "MAINTENANCE_RUN",
    "config_update": "CONFIG_UPDATE",
    "access_token_rotate": "ACCESS_TOKEN_ROTATE",
    "overrun_reset": "OVERRUN_RESET",
    "budget_limit_update": "BUDGET_LIMIT_UPDATE",
    "audit_retention_purge": "AUDIT_RETENTION_PURGE",
    "llm_probe": "LLM_PROBE",
}
_TERMINAL_STATES = frozenset({"succeeded", "partial", "failed", "cancelled"})
_VALID_STATES = frozenset({"pending", "running", "succeeded", "partial", "failed", "cancelled"})
_RETRYABLE_KINDS = frozenset(
    {
        "dataset_delete",
        "dataset_purge",
        "discussion_lease_recover",
        "discussion_force_end",
        "file_delete",
        "ppt_delete",
        "rag_document_delete",
        "rag_project_purge",
        "maintenance",
        "maintenance_run",
        "overrun_reset",
        "budget_limit_update",
    }
)
_SENSITIVE_KEY = re.compile(r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|access[_-]?token|raw[_-]?rows?|current[_-]?rows?|request[_-]?body|metadata)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _strict_safe(value: Any, *, depth: int = 0) -> Any:
    """Sanitize without dropping list members or hashing oversized values."""

    if depth > 16:
        raise ValueError("operation summary nesting is too deep")
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = _strict_safe(raw_value, depth=depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_strict_safe(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise ValueError("operation summary contains an unsupported value")


def _strict_full(value: Any, *, depth: int = 0) -> Any:
    """Validate and canonicalize a complete request for digesting.

    The persisted intent intentionally redacts secret-bearing fields, but a
    digest made from that redacted representation would make two different
    requests (for example two different token values) share one idempotency
    hash. This companion form keeps the complete value in process memory only
    so the size and canonicalization checks cover every list member and secret
    value before the digest is stored.
    """

    if depth > 16:
        raise ValueError("operation summary nesting is too deep")
    if isinstance(value, dict):
        return {str(raw_key): _strict_full(raw_value, depth=depth + 1) for raw_key, raw_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict_full(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise ValueError("operation summary contains an unsupported value")


def _digest_safe(value: Any, *, depth: int = 0) -> Any:
    """Build a canonical digest payload without retaining secret values.

    Secret values are represented by a one-way SHA-256 fingerprint. Their
    complete canonical value is hashed, rather than replaced with a common
    ``[REDACTED]`` marker, so idempotency remains collision-resistant while
    ``request_hash`` never contains the credential itself.
    """

    if depth > 16:
        raise ValueError("operation summary nesting is too deep")
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                secret_value = _strict_full(raw_value, depth=depth + 1)
                encoded = json.dumps(secret_value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
                cleaned[key] = {"sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}
            else:
                cleaned[key] = _digest_safe(raw_value, depth=depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_digest_safe(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise ValueError("operation summary contains an unsupported value")


def _operation_json(value: Any) -> str:
    safe = _strict_safe(value)
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("operation summary exceeds 64KB")
    return encoded


def request_digest(*, kind: str, scope: str, intended: Any) -> str:
    # Check the complete canonical request before replacing sensitive fields
    # with fingerprints. This prevents an oversized secret or target list
    # from being silently accepted merely because redaction made it small.
    full_payload = {"kind": kind, "scope": scope, "intended": _strict_full(intended)}
    full_encoded = json.dumps(full_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    if len(full_encoded.encode("utf-8")) > 65536:
        raise ValueError("operation summary exceeds 64KB")
    digest_payload = {"kind": kind, "scope": scope, "intended": _digest_safe(intended)}
    encoded = json.dumps(digest_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AdminOperation:
    operation_id: str
    actor_id: str | None
    kind: str
    scope: str
    idempotency_key: str | None
    request_hash: str | None
    state: str
    attempt_count: int
    intended: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def retryable(self) -> bool:
        # Credential and token changes deliberately stay non-retryable: a
        # lost response must not replay a secret-bearing operation. The same
        # explicit whitelist keeps config updates (whose safe intent stores
        # only field names) from claiming they can be replayed automatically.
        return self.kind in _RETRYABLE_KINDS and self.state in {"failed", "partial"} and bool(self.error_code or self.result is not None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "actor_id": self.actor_id,
            "kind": self.kind,
            "scope": self.scope,
            "idempotency_key": self.idempotency_key,
            "request_hash": self.request_hash,
            "state": self.state,
            "attempt_count": self.attempt_count,
            "intended": self.intended,
            "result": self.result,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _safe_loaded_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    if len(raw.encode("utf-8", "replace")) > 65536:
        return {"truncated": True, "sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()}
    try:
        parsed = json.loads(raw)
        safe = _strict_safe(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"value": "[REDACTED_UNSAFE_SUMMARY]"}
    return safe if isinstance(safe, dict) else {"value": safe}


def _from_row(row: Any) -> AdminOperation:
    intended = _safe_loaded_json(row["intended_json"])
    result = _safe_loaded_json(row["result_json"]) if row["result_json"] else None
    return AdminOperation(
        operation_id=row["operation_id"],
        actor_id=row["actor_id"],
        kind=row["kind"],
        scope=row["scope"],
        idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"],
        state=row["state"],
        attempt_count=int(row["attempt_count"]),
        intended=intended,
        result=result,
        error_code=row["error_code"],
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _find_by_idempotency(db, actor_id: str | None, kind: str, idempotency_key: str | None):
    if not actor_id or not idempotency_key:
        return None
    return db.execute(
        "SELECT * FROM admin_operations WHERE actor_id=? AND kind=? AND idempotency_key=?",
        (actor_id, kind, idempotency_key),
    ).fetchone()


def begin_operation_tx(
    db,
    *,
    actor_id: str,
    actor_name: str,
    kind: str,
    scope: str,
    intended: dict[str, Any],
    request_id: str,
    idempotency_key: str,
    action: str | None = None,
    reason: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AdminOperation:
    if not actor_id or not actor_name or not kind or not scope or not request_id or not idempotency_key:
        raise ValueError("actor, operation kind/scope, request_id and idempotency_key are required")
    if len(idempotency_key) > 200:
        raise ValueError("idempotency key is too long")
    intended_json = _operation_json(intended)
    digest = request_digest(kind=kind, scope=scope, intended=intended)
    existing = _find_by_idempotency(db, actor_id, kind, idempotency_key)
    if existing is not None:
        if existing["request_hash"] != digest:
            raise AppException("IDEMPOTENCY_CONFLICT", "幂等键已用于其他操作", 409)
        return _from_row(existing)
    operation_id = f"op_{uuid4().hex}"
    now = _now()
    try:
        db.execute(
            """INSERT INTO admin_operations(
                operation_id,actor_id,kind,scope,idempotency_key,request_hash,
                attempt_count,state,intended_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,0,'pending',?,?,?)""",
            (operation_id, actor_id, kind, scope, idempotency_key, digest, intended_json, now, now),
        )
    except Exception:
        # Another request may have won the unique key race.  Return it only
        # when its normalized request is identical; otherwise preserve the
        # explicit conflict contract.
        existing = _find_by_idempotency(db, actor_id, kind, idempotency_key)
        if existing is None:
            raise
        if existing["request_hash"] != digest:
            raise AppException("IDEMPOTENCY_CONFLICT", "幂等键已用于其他操作", 409)
        return _from_row(existing)
    selected_action = action or _KIND_ACTIONS.get(kind, "MAINTENANCE_RUN")
    record_audit_tx(
        db,
        action=selected_action,
        actor_id=actor_id,
        actor_name=actor_name,
        request_id=request_id,
        operation_id=operation_id,
        result="REQUESTED",
        target_type=target_type or kind,
        target_id=target_id or scope,
        reason=reason,
        detail=intended,
        ip=ip,
        user_agent=user_agent,
    )
    row = db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
    return _from_row(row)


def begin_operation(**kwargs: Any) -> AdminOperation:
    with transaction(immediate=True) as db:
        return begin_operation_tx(db, **kwargs)


def mark_operation_running_tx(db, operation_id: str) -> AdminOperation:
    row = db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
    if row is None:
        raise AppException("OPERATION_NOT_FOUND", "操作不存在", 404)
    if row["state"] in _TERMINAL_STATES:
        return _from_row(row)
    if row["state"] != "pending":
        raise AppException("OPERATION_RUNNING", "操作正在执行", 409)
    now = _now()
    db.execute(
        "UPDATE admin_operations SET state='running',attempt_count=attempt_count+1,updated_at=? WHERE operation_id=? AND state='pending'",
        (now, operation_id),
    )
    row = db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
    return _from_row(row)


def mark_operation_running(operation_id: str) -> AdminOperation:
    with transaction(immediate=True) as db:
        return mark_operation_running_tx(db, operation_id)


def complete_operation_tx(
    db,
    operation_id: str,
    *,
    actor_id: str,
    actor_name: str,
    request_id: str,
    result: dict[str, Any] | None = None,
    state: str = "succeeded",
    error_code: str | None = None,
    reason: str | None = None,
    action: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AdminOperation:
    if state not in _VALID_STATES or state not in _TERMINAL_STATES:
        raise ValueError(f"invalid terminal operation state: {state}")
    row = db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
    if row is None:
        raise AppException("OPERATION_NOT_FOUND", "操作不存在", 404)
    if row["state"] in _TERMINAL_STATES:
        return _from_row(row)
    result_json = _operation_json(result) if result is not None else None
    now = _now()
    db.execute(
        "UPDATE admin_operations SET state=?,result_json=?,error_code=?,updated_at=? WHERE operation_id=? AND state IN ('pending','running')",
        (state, result_json, error_code, now, operation_id),
    )
    selected_action = action or _KIND_ACTIONS.get(row["kind"], "MAINTENANCE_RUN")
    record_audit_tx(
        db,
        action=selected_action,
        actor_id=actor_id,
        actor_name=actor_name,
        request_id=request_id,
        operation_id=operation_id,
        result={"succeeded": "SUCCEEDED", "partial": "PARTIAL", "failed": "FAILED", "cancelled": "FAILED"}[state],
        target_type=row["kind"],
        target_id=row["scope"],
        error_code=error_code,
        reason=reason,
        after_summary=result,
        ip=ip,
        user_agent=user_agent,
    )
    if state in {"partial", "failed"}:
        record_operation_event_tx(db, level="warning" if state == "partial" else "error", category="system", event_key=f"operation.{state}", message=f"管理操作 {operation_id} {state}", operation_id=operation_id, context={"kind": row["kind"], "scope": row["scope"], "error_code": error_code})
    return _from_row(db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone())


def complete_operation(operation_id: str, **kwargs: Any) -> AdminOperation:
    with transaction(immediate=True) as db:
        return complete_operation_tx(db, operation_id, **kwargs)


def retry_operation_tx(
    db,
    operation_id: str,
    *,
    actor_id: str,
    actor_name: str,
    request_id: str,
    retry_key: str,
    reason: str = "",
) -> AdminOperation:
    """Move one failed/partial operation back to running exactly once.

    ``retry_key`` is stored only as a SHA-256 digest in the attempt table.
    Replaying that key returns the current original operation without another
    attempt or audit row; a fresh key is required for a later retry.
    """

    if not operation_id or not actor_id or not actor_name or not request_id or not retry_key:
        raise ValueError("operation, actor, request_id and retry_key are required")
    if len(retry_key) > 200 or any(ord(char) < 32 for char in retry_key):
        raise ValueError("retry key is invalid")
    row = db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
    if row is None:
        raise AppException("OPERATION_NOT_FOUND", "操作不存在", 404)
    if row["actor_id"] != actor_id:
        raise AppException("ADMIN_OPERATION_FORBIDDEN", "无权重试该管理操作", 403)

    retry_key_hash = hashlib.sha256(retry_key.encode("utf-8")).hexdigest()
    existing_attempt = db.execute(
        "SELECT actor_id FROM admin_operation_attempts WHERE operation_id=? AND retry_key_hash=?",
        (operation_id, retry_key_hash),
    ).fetchone()
    if existing_attempt is not None:
        if existing_attempt["actor_id"] != actor_id:
            raise AppException("ADMIN_OPERATION_FORBIDDEN", "无权重试该管理操作", 403)
        return _from_row(row)

    if row["state"] in {"pending", "running"}:
        raise AppException("OPERATION_RUNNING", "操作正在执行，请等待其完成", 409)
    if row["state"] not in {"failed", "partial"} or row["kind"] not in _RETRYABLE_KINDS:
        raise AppException("OPERATION_NOT_RETRYABLE", "该操作当前不可重试", 409)

    now = _now()
    # The immediate transaction held by the wrapper serializes two different
    # retry keys. The conditional update remains a second line of defence for
    # callers that compose this primitive with a larger transaction.
    db.execute(
        "INSERT INTO admin_operation_attempts(attempt_id,operation_id,actor_id,retry_key_hash,created_at) VALUES(?,?,?,?,?)",
        (f"attempt_{uuid4().hex}", operation_id, actor_id, retry_key_hash, now),
    )
    updated = db.execute(
        "UPDATE admin_operations SET state='running',attempt_count=attempt_count+1,error_code=NULL,updated_at=? WHERE operation_id=? AND actor_id=? AND state IN ('failed','partial')",
        (now, operation_id, actor_id),
    ).rowcount
    if updated != 1:
        raise AppException("OPERATION_RUNNING", "操作正在执行，请等待其完成", 409)
    selected_action = _KIND_ACTIONS.get(row["kind"], "MAINTENANCE_RUN")
    record_audit_tx(
        db,
        action=selected_action,
        actor_id=actor_id,
        actor_name=actor_name,
        request_id=request_id,
        operation_id=operation_id,
        result="REQUESTED",
        target_type=row["kind"],
        target_id=row["scope"],
        reason=reason or "operation retry",
        detail={"retry": True, "attempt_count": int(row["attempt_count"]) + 1},
    )
    return _from_row(db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone())


def retry_operation(operation_id: str, **kwargs: Any) -> AdminOperation:
    with transaction(immediate=True) as db:
        return retry_operation_tx(db, operation_id, **kwargs)


def get_operation(operation_id: str) -> AdminOperation:
    with transaction() as db:
        row = db.execute("SELECT * FROM admin_operations WHERE operation_id=?", (operation_id,)).fetchone()
    if row is None:
        raise AppException("OPERATION_NOT_FOUND", "操作不存在", 404)
    return _from_row(row)


def list_operations(*, actor_id: str | None = None, idempotency_key: str | None = None, state: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200)); offset = max(0, int(offset))
    clauses: list[str] = []; params: list[Any] = []
    if actor_id:
        clauses.append("actor_id=?"); params.append(actor_id)
    if idempotency_key:
        clauses.append("idempotency_key=?"); params.append(idempotency_key)
    if state:
        if state not in _VALID_STATES:
            raise ValueError("invalid operation state")
        clauses.append("state=?"); params.append(state)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM admin_operations{where} ORDER BY created_at DESC,operation_id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        total = db.execute(f"SELECT COUNT(*) FROM admin_operations{where}", params).fetchone()[0]
    return {"items": [_from_row(row) for row in rows], "total": int(total), "limit": limit, "offset": offset, "total_is_estimate": False}


__all__ = [
    "AdminOperation",
    "begin_operation",
    "begin_operation_tx",
    "complete_operation",
    "complete_operation_tx",
    "get_operation",
    "list_operations",
    "mark_operation_running",
    "mark_operation_running_tx",
    "request_digest",
    "retry_operation",
    "retry_operation_tx",
]
