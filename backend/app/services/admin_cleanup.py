"""Scoped, auditable maintenance primitives for the admin console.

The legacy maintenance helper removed datasets, sessions and files as one
operation.  That made a request intended to clean one scope unexpectedly erase
related records.  This module keeps each scope explicit and reports every
candidate as succeeded, skipped, failed or unknown.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from backend.app.core.errors import AppException
from backend.app.repositories import database
from backend.app.services import ppt as ppt_service
from backend.app.services import usage as usage_service

logger = logging.getLogger(__name__)

SCOPES = (
    "datasets",
    "sessions",
    "files",
    "reservations",
    "audit_logs",
    "operation_events",
    "admin_sessions",
    "throttles",
    "terminal_operations",
)
_maintenance_lock = threading.Lock()


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _table_exists(db, table: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _expired(value: Any, current: datetime) -> bool:
    parsed = _parse_time(value)
    return parsed is not None and parsed <= current


def _empty_stat() -> dict[str, Any]:
    return {"attempted": 0, "succeeded": 0, "skipped": 0, "failed": 0, "unknown": 0, "errors": []}


def _scopes(scopes: Iterable[str] | str | None) -> list[str]:
    if scopes is None:
        return ["datasets", "sessions", "files", "reservations"]
    if isinstance(scopes, str):
        values = [item.strip() for item in scopes.split(",") if item.strip()]
    else:
        values = [str(item).strip() for item in scopes if str(item).strip()]
    if not values or "all" in values:
        values = list(SCOPES)
    unknown = sorted(set(values) - set(SCOPES))
    if unknown:
        raise AppException("MAINTENANCE_SCOPE_INVALID", f"不支持的清理范围: {', '.join(unknown)}", 422)
    return list(dict.fromkeys(values))


def _dataset_references(db) -> set[str]:
    references: set[str] = set()
    if not _table_exists(db, "discussion_sessions"):
        return references
    rows = db.execute("SELECT status,state_json FROM discussion_sessions").fetchall()
    for row in rows:
        if str(row["status"]) in {"finished", "cancelled"}:
            continue
        try:
            state = json.loads(row["state_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        dataset_id = state.get("dataset_id") if isinstance(state, dict) else None
        if dataset_id:
            references.add(str(dataset_id))
    return references


def purge_expired_datasets(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    stat = _empty_stat()
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "datasets"):
            return stat
        references = _dataset_references(db)
        rows = db.execute("SELECT dataset_id,expires_at FROM datasets WHERE expires_at<=? ORDER BY expires_at,dataset_id", (current.isoformat(),)).fetchall()
        for row in rows:
            stat["attempted"] += 1
            dataset_id = str(row["dataset_id"])
            if dataset_id in references:
                stat["skipped"] += 1
                continue
            if dry_run:
                stat["succeeded"] += 1
                continue
            try:
                deleted = db.execute("DELETE FROM datasets WHERE dataset_id=?", (dataset_id,))
                if deleted.rowcount:
                    stat["succeeded"] += 1
                else:
                    stat["skipped"] += 1
            except Exception as exc:
                stat["failed"] += 1
                stat["errors"].append({"target_id": dataset_id, "error": type(exc).__name__})
    return stat


def delete_dataset(dataset_id: str) -> dict[str, Any]:
    """Delete one dataset, preserving all snapshots and other domain records."""

    if not dataset_id or len(dataset_id) > 200:
        raise AppException("DATASET_ID_INVALID", "数据集标识不合法", 422)
    with database.transaction(immediate=True) as db:
        delete_dataset_tx(db, dataset_id)
    return {"dataset_id": dataset_id, "deleted": True, "scope": "datasets"}


def delete_dataset_tx(db, dataset_id: str) -> dict[str, Any]:
    """Transactional variant used when the caller must add an audit row."""

    if not dataset_id or len(dataset_id) > 200:
        raise AppException("DATASET_ID_INVALID", "数据集标识不合法", 422)
    if not _table_exists(db, "datasets"):
        raise AppException("DATASET_NOT_FOUND", "数据集不存在", 404)
    row = db.execute("SELECT dataset_id FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    if not row:
        raise AppException("DATASET_NOT_FOUND", "数据集不存在", 404)
    if dataset_id in _dataset_references(db):
        raise AppException("DATASET_IN_USE", "数据集仍被存续研讨会话引用", 409)
    db.execute("DELETE FROM datasets WHERE dataset_id=?", (dataset_id,))
    return {"dataset_id": dataset_id, "deleted": True, "scope": "datasets"}


def purge_expired_sessions(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    stat = _empty_stat()
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "discussion_sessions"):
            return stat
        rows = db.execute("SELECT session_id,status,expires_at FROM discussion_sessions WHERE expires_at<=? ORDER BY expires_at,session_id", (current.isoformat(),)).fetchall()
        for row in rows:
            stat["attempted"] += 1
            session_id = str(row["session_id"])
            if str(row["status"]) not in {"finished", "cancelled"}:
                stat["skipped"] += 1
                continue
            if dry_run:
                stat["succeeded"] += 1
                continue
            savepoint = f"purge_session_{stat['attempted']}"
            try:
                # A corrupt child row or a future schema constraint must not
                # leave earlier deletions from this same cleanup transaction
                # half-applied. Each target gets its own SQLite savepoint.
                db.execute(f"SAVEPOINT {savepoint}")
                if _table_exists(db, "discussion_events"):
                    db.execute("DELETE FROM discussion_events WHERE session_id=?", (session_id,))
                if _table_exists(db, "discussion_commands"):
                    db.execute("DELETE FROM discussion_commands WHERE session_id=?", (session_id,))
                db.execute("DELETE FROM discussion_sessions WHERE session_id=?", (session_id,))
                db.execute(f"RELEASE SAVEPOINT {savepoint}")
                stat["succeeded"] += 1
            except Exception as exc:
                try:
                    db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    db.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception as rollback_exc:
                    # Continuing after a failed rollback could report a
                    # partially applied cleanup while the transaction still
                    # contains an unknown child deletion.  Fail the whole
                    # cleanup so the outer transaction can roll back.
                    raise RuntimeError("session cleanup savepoint rollback failed") from rollback_exc
                stat["failed"] += 1
                stat["errors"].append({"target_id": session_id, "error": type(exc).__name__})
    return stat


def purge_expired_files(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    stat = _empty_stat()
    output_dir = Path(ppt_service.OUTPUT_DIR).resolve()
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "files"):
            return stat
        rows = db.execute("SELECT file_id,disk_path,expires_at FROM files WHERE expires_at<=? ORDER BY expires_at,file_id", (current.isoformat(),)).fetchall()
        for row in rows:
            stat["attempted"] += 1
            file_id = str(row["file_id"])
            try:
                path = Path(str(row["disk_path"])).resolve()
                if os.path.commonpath([str(path), str(output_dir)]) != str(output_dir):
                    stat["failed"] += 1
                    stat["errors"].append({"target_id": file_id, "error": "FILE_PATH_OUTSIDE_OUTPUT_DIR"})
                    continue
                if dry_run:
                    stat["succeeded"] += 1
                    continue
                # A missing file remains registered for reconciliation.  It is
                # not reported as a successful deletion.
                if not path.exists():
                    stat["skipped"] += 1
                    continue
                path.unlink()
                db.execute("DELETE FROM files WHERE file_id=?", (file_id,))
                stat["succeeded"] += 1
            except PermissionError:
                stat["failed"] += 1
                stat["errors"].append({"target_id": file_id, "error": "FILE_PERMISSION_DENIED"})
            except OSError as exc:
                stat["failed"] += 1
                stat["errors"].append({"target_id": file_id, "error": type(exc).__name__})
    # Keep stale temp files outside the files table, but use the existing
    # service's fixed output directory and active-temp guard.
    if not dry_run:
        try:
            ppt_service._purge_stale_temp_files()
        except Exception:
            logger.info("stale PPT temp cleanup failed", exc_info=True)
    return stat


def sweep_reservations(*, dry_run: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    stat = _empty_stat()
    before_unknown = {"count": 0, "amount": "0.00"}
    from decimal import Decimal, InvalidOperation

    db = database.connect()
    try:
        if _table_exists(db, "reservations"):
            rows = db.execute("SELECT status,reserved_usd FROM reservations").fetchall()
            total = Decimal("0")
            for row in rows:
                if str(row["status"]) in {"usage_unknown", "provider_overrun"}:
                    before_unknown["count"] += 1
                    try:
                        total += Decimal(str(row["reserved_usd"]))
                    except (InvalidOperation, ValueError):
                        pass
            before_unknown["amount"] = format(total, "f") if total else "0.00"
    finally:
        db.close()
    if dry_run:
        db = database.connect()
        try:
            if _table_exists(db, "reservations"):
                cutoff = (_now() - timedelta(minutes=usage_service.RESERVED_GRACE_MINUTES)).isoformat()
                stat["attempted"] = int(db.execute("SELECT COUNT(*) FROM reservations WHERE status='reserved' AND created_at<=?", (cutoff,)).fetchone()[0])
                stat["succeeded"] = stat["attempted"]
        finally:
            db.close()
        return stat, before_unknown
    released = usage_service.sweep_stale_reservations()
    stat["attempted"] = released
    stat["succeeded"] = released
    return stat, before_unknown


def purge_operation_events(*, dry_run: bool = False, now: datetime | None = None, retention_days: int = 90) -> dict[str, Any]:
    current = _now(now)
    stat = _empty_stat()
    cutoff = (current - timedelta(days=retention_days)).isoformat()
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "operation_events"):
            return stat
        rows = db.execute("SELECT id FROM operation_events WHERE created_at<?", (cutoff,)).fetchall()
        stat["attempted"] = len(rows)
        if dry_run:
            stat["succeeded"] = len(rows)
            return stat
        try:
            db.execute("DELETE FROM operation_events WHERE created_at<?", (cutoff,))
            stat["succeeded"] = len(rows)
        except Exception as exc:
            stat["failed"] = len(rows)
            stat["errors"].append({"error": type(exc).__name__})
    return stat


def purge_admin_sessions(*, dry_run: bool = False, now: datetime | None = None, retention_days: int = 7) -> dict[str, Any]:
    """Remove only long expired/revoked administrator sessions.

    A live session is retained even when another timestamp is old.  The
    retention boundary is deliberately based on the effective invalidation
    timestamp, so an idle-expired session is eligible without touching a
    session whose absolute lifetime is still valid.
    """

    current = _now(now)
    cutoff = (current - timedelta(days=max(1, int(retention_days)))).isoformat()
    stat = _empty_stat()
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "admin_sessions"):
            return stat
        where = (
            "((revoked_at IS NOT NULL AND revoked_at<=?) "
            "OR (revoked_at IS NULL AND "
            "(absolute_expires_at<=? OR idle_expires_at<=?)))"
        )
        params = (cutoff, cutoff, cutoff)
        stat["attempted"] = int(db.execute(f"SELECT COUNT(*) FROM admin_sessions WHERE {where}", params).fetchone()[0])
        if dry_run:
            stat["succeeded"] = stat["attempted"]
            return stat
        try:
            deleted = int(db.execute(f"DELETE FROM admin_sessions WHERE {where}", params).rowcount)
            stat["succeeded"] = max(0, deleted)
        except Exception as exc:
            stat["failed"] = stat["attempted"]
            stat["errors"].append({"error": type(exc).__name__})
            raise
    return stat


def purge_login_throttles(*, dry_run: bool = False, now: datetime | None = None, retention_hours: int = 24) -> dict[str, Any]:
    """Drop throttle rows that are both old and no longer locked."""

    current = _now(now)
    cutoff = (current - timedelta(hours=max(1, int(retention_hours)))).isoformat()
    current_iso = current.isoformat()
    stat = _empty_stat()
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "admin_login_throttles"):
            return stat
        where = "updated_at<=? AND (locked_until IS NULL OR locked_until<=?)"
        params = (cutoff, current_iso)
        stat["attempted"] = int(db.execute(f"SELECT COUNT(*) FROM admin_login_throttles WHERE {where}", params).fetchone()[0])
        if dry_run:
            stat["succeeded"] = stat["attempted"]
            return stat
        try:
            deleted = int(db.execute(f"DELETE FROM admin_login_throttles WHERE {where}", params).rowcount)
            stat["succeeded"] = max(0, deleted)
        except Exception as exc:
            stat["failed"] = stat["attempted"]
            stat["errors"].append({"error": type(exc).__name__})
            raise
    return stat


def purge_terminal_operations(*, dry_run: bool = False, now: datetime | None = None, retention_days: int = 180) -> dict[str, Any]:
    """Purge old completed operation records while keeping retryable work.

    ``admin_operation_attempts`` is removed first because older databases may
    enforce the foreign key without an ON DELETE CASCADE clause.  Failed
    operations whose kind is retryable remain discoverable indefinitely until
    an explicit retry or operator decision; successful/cancelled records and
    non-retryable failures follow the 180-day retention boundary.
    """

    current = _now(now)
    cutoff = (current - timedelta(days=max(1, int(retention_days)))).isoformat()
    stat = _empty_stat()
    try:
        from backend.app.services.admin_operations import _RETRYABLE_KINDS

        retryable_kinds = tuple(sorted(str(kind) for kind in _RETRYABLE_KINDS))
    except Exception:
        # If the operation service cannot be inspected, retain all failed
        # rows.  Deletion of only successful/cancelled rows remains safe.
        retryable_kinds = ()
    params: list[Any] = [cutoff]
    where = " WHERE (updated_at<=? AND state IN ('succeeded','cancelled'))"
    if retryable_kinds:
        marks = ",".join("?" for _ in retryable_kinds)
        where += f" OR (updated_at<=? AND state='failed' AND kind NOT IN ({marks}))"
        params.extend([cutoff, *retryable_kinds])
    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "admin_operations"):
            return stat
        ids = [str(row[0]) for row in db.execute(f"SELECT operation_id FROM admin_operations{where} ORDER BY updated_at,operation_id", params).fetchall()]
        stat["attempted"] = len(ids)
        if dry_run:
            stat["succeeded"] = len(ids)
            return stat
        try:
            if ids and _table_exists(db, "admin_operation_attempts"):
                marks = ",".join("?" for _ in ids)
                db.execute(f"DELETE FROM admin_operation_attempts WHERE operation_id IN ({marks})", ids)
            if ids:
                marks = ",".join("?" for _ in ids)
                deleted = int(db.execute(f"DELETE FROM admin_operations WHERE operation_id IN ({marks})", ids).rowcount)
            else:
                deleted = 0
            stat["succeeded"] = max(0, deleted)
        except Exception as exc:
            stat["failed"] = stat["attempted"]
            stat["errors"].append({"error": type(exc).__name__})
            raise
    return stat


def purge_audit_logs(*, dry_run: bool = False, now: datetime | None = None, retention_days: int = 180) -> dict[str, Any]:
    """Delegate audit retention to the audit service when available.

    Audit deletion needs an intent/result chain.  Returning ``unknown`` while
    that service is unavailable is safer than silently deleting the trail.
    """

    current = _now(now)
    cutoff = (current - timedelta(days=max(1, int(retention_days)))).isoformat()
    stat = _empty_stat()
    request_id = f"maintenance_audit_{uuid4().hex}"
    # The audit table is itself the source of truth for retention.  Keep the
    # intent and result rows in the same transaction as the deletion so a
    # failed audit insert rolls the purge back rather than erasing history
    # without a trace. The fresh intent/result rows are newer than the cutoff.
    from backend.app.services import audit as audit_service

    shared_purge = getattr(audit_service, "purge_retention", None)
    if callable(shared_purge):
        result = shared_purge(dry_run=dry_run, now=now, retention_days=retention_days)
        return result if isinstance(result, dict) else stat

    with database.transaction(immediate=not dry_run) as db:
        if not _table_exists(db, "audit_logs"):
            return stat
        candidate = int(db.execute("SELECT COUNT(*) FROM audit_logs WHERE created_at<?", (cutoff,)).fetchone()[0])
        stat["attempted"] = candidate
        if dry_run:
            stat["succeeded"] = candidate
            return stat
        audit_service.record_audit_tx(
            db,
            action="AUDIT_RETENTION_PURGE",
            actor_id="system",
            actor_name="system",
            request_id=request_id,
            result="REQUESTED",
            target_type="audit_logs",
            target_id=f"older_than_{retention_days}d",
            detail={"retention_days": int(retention_days), "candidate_count": candidate},
        )
        try:
            deleted = db.execute("DELETE FROM audit_logs WHERE created_at<?", (cutoff,)).rowcount
            stat["succeeded"] = max(0, int(deleted))
            audit_service.record_audit_tx(
                db,
                action="AUDIT_RETENTION_PURGE",
                actor_id="system",
                actor_name="system",
                request_id=request_id,
                result="SUCCEEDED",
                target_type="audit_logs",
                target_id=f"older_than_{retention_days}d",
                after_summary={"deleted_count": int(deleted), "retention_days": int(retention_days)},
            )
        except Exception as exc:
            stat["failed"] = candidate
            stat["succeeded"] = 0
            stat["errors"].append({"error": type(exc).__name__})
            raise
    return stat


def run_cleanup(*, scopes: Iterable[str] | str | None = None, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    selected = _scopes(scopes)
    if not _maintenance_lock.acquire(blocking=False):
        raise AppException("MAINTENANCE_RUNNING", "已有维护任务正在执行", 409)
    try:
        stats: dict[str, dict[str, Any]] = {scope: _empty_stat() for scope in selected}
        retained_unknown = {"count": 0, "amount": "0.00"}
        for scope in selected:
            if scope == "datasets":
                stats[scope] = purge_expired_datasets(dry_run=dry_run, now=now)
            elif scope == "sessions":
                stats[scope] = purge_expired_sessions(dry_run=dry_run, now=now)
            elif scope == "files":
                stats[scope] = purge_expired_files(dry_run=dry_run, now=now)
            elif scope == "reservations":
                stats[scope], retained_unknown = sweep_reservations(dry_run=dry_run)
            elif scope == "operation_events":
                stats[scope] = purge_operation_events(dry_run=dry_run, now=now)
            elif scope == "audit_logs":
                stats[scope] = purge_audit_logs(dry_run=dry_run, now=now)
            elif scope == "admin_sessions":
                stats[scope] = purge_admin_sessions(dry_run=dry_run, now=now)
            elif scope == "throttles":
                stats[scope] = purge_login_throttles(dry_run=dry_run, now=now)
            elif scope == "terminal_operations":
                stats[scope] = purge_terminal_operations(dry_run=dry_run, now=now)
        return {"scopes": stats, "retained_unknown_count": retained_unknown["count"], "retained_unknown_amount": retained_unknown["amount"], "dry_run": dry_run}
    finally:
        _maintenance_lock.release()


def run_scheduled_cleanup() -> dict[str, int]:
    """Compatibility adapter for the existing hourly scheduler.

    Scheduled cleanup never touches audit logs or operation events; those need
    an administrator-authorized retention intent.  It keeps live sessions and
    unknown usage holds according to the scoped rules above.
    """

    request_id = f"maintenance_scheduled_{uuid4().hex}"
    audit_enabled = False
    try:
        from backend.app.core.admin_security import get_admin_settings

        audit_enabled = bool(get_admin_settings().enabled)
    except Exception:
        logger.info("admin settings unavailable for scheduled maintenance audit", exc_info=True)
    if audit_enabled:
        try:
            from backend.app.services import audit as audit_service

            audit_service.record_audit(
                action="MAINTENANCE_RUN",
                actor_id="system",
                actor_name="system",
                request_id=request_id,
                result="REQUESTED",
                target_type="maintenance",
                target_id="scheduled",
                detail={"scope": ["datasets", "sessions", "files", "reservations"]},
            )
        except Exception:
            # When the admin surface is enabled, a maintenance mutation must
            # have a durable intent before any rows/files are changed.
            logger.error("scheduled maintenance intent audit failed; refusing cleanup", exc_info=True)
            raise AppException("AUDIT_UNAVAILABLE", "定时维护意图审计不可用，已拒绝清理", 503)
    try:
        result = run_cleanup(scopes=("datasets", "sessions", "files", "reservations"), dry_run=False)
        stats = {scope: int(stat.get("succeeded", 0)) for scope, stat in result["scopes"].items() if stat.get("succeeded", 0)}
        if audit_enabled:
            try:
                from backend.app.services import audit as audit_service

                audit_result = "PARTIAL" if any(int(item.get("failed", 0)) > 0 or int(item.get("unknown", 0)) > 0 for item in result["scopes"].values()) else "SUCCEEDED"
                audit_service.record_audit(
                    action="MAINTENANCE_RUN",
                    actor_id="system",
                    actor_name="system",
                    request_id=request_id,
                    result=audit_result,
                    target_type="maintenance",
                    target_id="scheduled",
                    after_summary={"scopes": result["scopes"], "retained_unknown_count": result["retained_unknown_count"]},
                )
            except Exception:
                # The mutation has already happened, but without a terminal
                # audit row the scheduler must not present a successful run.
                # The outer handler records a FAILED result when possible and
                # propagates an explicit dependency error to the scheduler.
                logger.error("scheduled maintenance result audit failed", exc_info=True)
                raise AppException("AUDIT_UNAVAILABLE", "定时维护结果审计不可用，任务结果待核对", 503)
        return stats
    except Exception as exc:
        if audit_enabled:
            try:
                from backend.app.services import audit as audit_service

                audit_service.record_audit(
                    action="MAINTENANCE_RUN",
                    actor_id="system",
                    actor_name="system",
                    request_id=request_id,
                    result="FAILED",
                    target_type="maintenance",
                    target_id="scheduled",
                    error_code=type(exc).__name__,
                )
            except Exception:
                logger.error("scheduled maintenance failure audit failed", exc_info=True)
                raise AppException("AUDIT_UNAVAILABLE", "定时维护失败审计不可用，任务结果待核对", 503)
        raise
