"""Read-only data products used by the administrator console.

The service deliberately reads the existing business tables instead of creating a
second, approximate ledger.  It also owns the output boundary: callers receive
safe dictionaries containing only fields that are suitable for an administrator
screen.  The router is responsible for authentication and HTTP concerns.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Sequence

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.core.errors import AppException
from backend.app.middleware.pii import pii_redactor
from backend.app.repositories import database
from backend.app.services import ppt as ppt_service
from backend.app.services.rag import rag_service

logger = logging.getLogger(__name__)

LOG_DIR = PROJECT_ROOT / "backend" / "logs"
MAX_LIST_LIMIT = 200
MAX_LOG_BYTES = 1_000_000
MAX_LOG_TAIL = 1_000
MAX_TEXT = 2_000

_SECRET_KEY = re.compile(
    r"(?i)\b(?:authorization|cookie|set-cookie|password|passwd|secret|token|api[_-]?key|access[_-]?token)\b"
)
_BEARER = re.compile(r"(?i)(\bBearer\s+)[^\s,;]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:token|api[_-]?key|access[_-]?token|password|secret|key)=)[^&#\s]+"
)
_HEADER_SECRET = re.compile(
    r"(?i)(\b(?:authorization|cookie|set-cookie|password|passwd|secret|token|api[_-]?key|access[_-]?token)\s*[:=]\s*)[^\s,;]+"
)
_LOG_LINE = re.compile(
    r"^(?P<created>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?)\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(?P<logger>[^ ]+)\s?(?P<message>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryWindow:
    start: datetime
    end: datetime
    name: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_datetime(value: str | datetime | None, *, field: str = "时间") -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _utc(value)
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return _utc(datetime.fromisoformat(raw))
    except ValueError as exc:
        raise AppException("ADMIN_RANGE_INVALID", f"{field}格式不合法", 422) from exc


def resolve_window(
    range_name: str = "24h",
    *,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
    now: datetime | None = None,
) -> QueryWindow:
    """Resolve a UTC half-open query range.

    Explicit bounds take precedence over the named range, but must be supplied
    together.  ``all`` starts at the oldest recorded event when one exists and
    otherwise at ``now`` so an empty installation still has a stable response.
    """

    current = _utc(now or datetime.now(UTC))
    start = parse_datetime(from_, field="from")
    end = parse_datetime(to, field="to")
    if (start is None) != (end is None):
        raise AppException("ADMIN_RANGE_INVALID", "from和to必须同时提供", 422)
    if start is not None and end is not None:
        if end <= start:
            raise AppException("ADMIN_RANGE_INVALID", "时间区间必须满足from小于to", 422)
        return QueryWindow(start, end, "custom")
    if range_name not in {"24h", "7d", "30d", "all"}:
        raise AppException("ADMIN_RANGE_INVALID", "range只能是24h、7d、30d或all", 422)
    if range_name == "24h":
        return QueryWindow(current - timedelta(hours=24), current, range_name)
    if range_name == "7d":
        return QueryWindow(current - timedelta(days=7), current, range_name)
    if range_name == "30d":
        return QueryWindow(current - timedelta(days=30), current, range_name)
    oldest = _oldest_usage_timestamp()
    return QueryWindow(oldest or current, current, range_name)


def _oldest_usage_timestamp() -> datetime | None:
    db = database.connect()
    try:
        if not _table_exists(db, "usage_events"):
            return None
        row = db.execute("SELECT MIN(created_at) AS created_at FROM usage_events").fetchone()
        return parse_datetime(row["created_at"]) if row and row["created_at"] else None
    except (ValueError, TypeError):
        return None
    finally:
        db.close()


def _table_exists(db, table: str) -> bool:
    row = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _limit_offset(limit: int = 50, offset: int = 0) -> tuple[int, int]:
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise AppException("ADMIN_PAGINATION_INVALID", "分页参数必须是整数", 422) from exc
    if limit < 1 or limit > MAX_LIST_LIMIT or offset < 0:
        raise AppException("ADMIN_PAGINATION_INVALID", f"limit范围为1-{MAX_LIST_LIMIT}且offset不能为负数", 422)
    return limit, offset


def _money(value: Decimal | int | float | str | None) -> str:
    try:
        amount = Decimal("0") if value is None else Decimal(str(value))
    except (InvalidOperation, ValueError):
        amount = Decimal("0")
    if not amount:
        return "0.00"
    return format(amount, "f")


def _csv_money(value: Decimal | int | float | str | None) -> str:
    """Format exported costs at the contract's fixed six-place precision."""

    try:
        amount = _decimal(value).quantize(Decimal("0.000001"))
    except InvalidOperation:
        amount = Decimal("0")
    if not amount.is_finite():
        amount = Decimal("0")
    return format(amount, "f")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    parsed = parse_datetime(str(value))
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _freshness(calculated_at: datetime | None = None) -> str:
    # SQLite/filesystem reads are local snapshots.  A read completed now is
    # fresh; explicit stale markers are reserved for partial dependency reads.
    return "fresh" if calculated_at is None or (datetime.now(UTC) - _utc(calculated_at)).total_seconds() < 60 else "stale"


def redact_text(value: Any, *, max_length: int = MAX_TEXT) -> str:
    from backend.app.services.admin_redaction import redact_admin_text
    text = redact_admin_text(value, max_length=max_length)
    text = _BEARER.sub(r"\1[REDACTED]", text)
    text = _QUERY_SECRET.sub(r"\1[REDACTED]", text)
    text = _HEADER_SECRET.sub(r"\1[REDACTED]", text)
    try:
        text = pii_redactor.redact(text)
    except Exception:
        logger.debug("PII redaction unavailable", exc_info=True)
    if len(text) > max_length:
        return text[:max_length] + "…"
    return text


def safe_json(value: Any, *, max_length: int = MAX_TEXT, max_items: int = 30) -> Any:
    """Recursively whitelist JSON-like values and redact sensitive keys."""

    if isinstance(value, str):
        return redact_text(value, max_length=max_length)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["_truncated"] = True
                break
            key_text = redact_text(key, max_length=100)
            if _SECRET_KEY.search(key_text):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = safe_json(item, max_length=max_length, max_items=max_items)
        return result
    if isinstance(value, (list, tuple, set)):
        output = [safe_json(item, max_length=max_length, max_items=max_items) for item in list(value)[:max_items]]
        if len(value) > max_items:
            output.append("[TRUNCATED]")
        return output
    return redact_text(value, max_length=max_length)


def _load_json(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _usage_filter(window: QueryWindow, *, provider: str | None = None, model: str | None = None) -> tuple[str, list[Any]]:
    clauses = ["created_at >= ?", "created_at < ?"]
    params: list[Any] = [window.start.isoformat(), window.end.isoformat()]
    if provider:
        clauses.append("provider=?")
        params.append(provider)
    if model:
        clauses.append("model=?")
        params.append(model)
    return " AND ".join(clauses), params


def _rows_in_window(
    db,
    window: QueryWindow,
    *,
    provider: str | None = None,
    model: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    if not _table_exists(db, "usage_events"):
        return []
    where, params = _usage_filter(window, provider=provider, model=model)
    sql = (
        "SELECT id,request_id,provider,model,input_tokens,output_tokens,"
        "embedding_tokens,cost_usd,price_effective_from,created_at "
        f"FROM usage_events WHERE {where} ORDER BY created_at ASC,id ASC"
    )
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    return db.execute(sql, params).fetchall()


def _reservation_filter(window: QueryWindow | None = None, status: str | None = None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if window:
        clauses.extend(["created_at >= ?", "created_at < ?"])
        params.extend([window.start.isoformat(), window.end.isoformat()])
    if status:
        statuses = [item.strip() for item in status.split(",") if item.strip()]
        allowed = {"reserved", "usage_unknown", "settled", "released", "provider_overrun", "overrun_cleared"}
        if any(item not in allowed for item in statuses):
            raise AppException("ADMIN_STATUS_INVALID", "预算预留状态不合法", 422)
        if len(statuses) == 1:
            clauses.append("status=?")
            params.append(statuses[0])
        elif statuses:
            clauses.append("status IN (" + ",".join("?" for _ in statuses) + ")")
            params.extend(statuses)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _reservation_rows(
    db,
    window: QueryWindow | None = None,
    status: str | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
):
    if not _table_exists(db, "reservations"):
        return []
    where, params = _reservation_filter(window, status)
    sql = f"SELECT * FROM reservations{where} ORDER BY created_at DESC,id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    return db.execute(sql, params).fetchall()


def _usage_totals(rows: Sequence[Any]) -> dict[str, Any]:
    cost = Decimal("0")
    input_tokens = output_tokens = embedding_tokens = 0
    for row in rows:
        input_tokens += int(row["input_tokens"] or 0)
        output_tokens += int(row["output_tokens"] or 0)
        embedding_tokens += int(row["embedding_tokens"] or 0)
        cost += _decimal(row["cost_usd"])
    return {
        "cost_usd": _money(cost),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "embedding_tokens": embedding_tokens,
        "requests": len(rows),
    }


def _reservation_totals(rows: Sequence[Any]) -> dict[str, str]:
    values = {"usage_unknown": Decimal("0"), "provider_overrun": Decimal("0"), "overrun_cleared": Decimal("0"), "reserved": Decimal("0")}
    for row in rows:
        status = str(row["status"] or "")
        if status in values:
            values[status] += _decimal(row["reserved_usd"])
    return {
        "usage_unknown_usd": _money(values["usage_unknown"]),
        "provider_overrun_usd": _money(values["provider_overrun"]),
        "overrun_cleared_usd": _money(values["overrun_cleared"]),
        # A provider_overrun row already has its realized usage in
        # usage_events.  Counting its original reservation again would double
        # charge the budget; it remains a circuit-breaker/status signal only.
        "reserved_usd": _money(values["reserved"] + values["usage_unknown"]),
    }


def usage_summary(
    range_name: str = "24h",
    *,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
    now: datetime | None = None,
    include_buckets: bool = True,
) -> dict[str, Any]:
    window = resolve_window(range_name, from_=from_, to=to, now=now)
    db = database.connect()
    try:
        usage_rows = _rows_in_window(db, window)
        reservations = _reservation_rows(db, window)
    finally:
        db.close()
    result = _usage_totals(usage_rows)
    result.update(_reservation_totals(reservations))
    result.update(
        {
            "range": window.name,
            "from": _iso(window.start),
            "to": _iso(window.end),
            "buckets": usage_trends(window.name if window.name in {"24h", "7d", "30d"} else "30d", "cost", now=now, from_=window.start if window.name == "custom" else None, to=window.end if window.name == "custom" else None) if include_buckets else [],
            "calculated_at": _iso(datetime.now(UTC)),
            "data_source": "sqlite",
            "freshness": "fresh",
        }
    )
    return result


def _bucket_window(range_name: str, *, now: datetime | None = None, start: datetime | None = None, end: datetime | None = None) -> tuple[datetime, datetime, timedelta, int]:
    current = _utc(now or datetime.now(UTC))
    if start is not None and end is not None:
        # Custom summary buckets are daily unless the range is one day or less.
        span = end - start
        step = timedelta(hours=1) if span <= timedelta(days=2) else timedelta(days=1)
        count = max(1, int((span.total_seconds() + step.total_seconds() - 1) // step.total_seconds()))
        return start, start + step * count, step, count
    if range_name == "24h":
        aligned_end = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return aligned_end - timedelta(hours=24), aligned_end, timedelta(hours=1), 24
    if range_name == "7d":
        aligned_end = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return aligned_end - timedelta(days=7), aligned_end, timedelta(days=1), 7
    aligned_end = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return aligned_end - timedelta(days=30), aligned_end, timedelta(days=1), 30


def usage_trends(
    range_name: str = "24h",
    metric: str = "cost",
    *,
    now: datetime | None = None,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    if metric not in {"cost", "tokens", "requests"}:
        raise AppException("ADMIN_METRIC_INVALID", "metric只能是cost、tokens或requests", 422)
    explicit_start = parse_datetime(from_, field="from")
    explicit_end = parse_datetime(to, field="to")
    if (explicit_start is None) != (explicit_end is None):
        raise AppException("ADMIN_RANGE_INVALID", "from和to必须同时提供", 422)
    start, end, step, count = _bucket_window(range_name, now=now, start=explicit_start, end=explicit_end)
    window = QueryWindow(start, end, "custom" if explicit_start is not None else range_name)
    db = database.connect()
    try:
        rows = _rows_in_window(db, window, provider=provider, model=model)
    finally:
        db.close()
    buckets = [{"bucket": _iso(start + step * index), "cost_usd": "0.00", "tokens": 0, "requests": 0} for index in range(count)]
    costs = [Decimal("0") for _ in range(count)]
    for row in rows:
        timestamp = parse_datetime(row["created_at"])
        if timestamp is None or timestamp < start or timestamp >= end:
            continue
        index = int((timestamp - start).total_seconds() // step.total_seconds())
        if not 0 <= index < len(buckets):
            continue
        bucket = buckets[index]
        costs[index] += _decimal(row["cost_usd"])
        bucket["tokens"] += int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0) + int(row["embedding_tokens"] or 0)
        bucket["requests"] += 1
    for bucket, cost in zip(buckets, costs):
        bucket["cost_usd"] = _money(cost)
    return buckets


def usage_by_model(
    range_name: str = "24h",
    *,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
    provider: str | None = None,
    model: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    window = resolve_window(range_name, from_=from_, to=to)
    db = database.connect()
    try:
        rows = _rows_in_window(db, window, provider=provider, model=model)
    finally:
        db.close()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["provider"]), str(row["model"]))
        item = grouped.setdefault(key, {"provider": key[0], "model": key[1], "input_tokens": 0, "output_tokens": 0, "embedding_tokens": 0, "requests": 0, "cost_usd": Decimal("0")})
        item["input_tokens"] += int(row["input_tokens"] or 0)
        item["output_tokens"] += int(row["output_tokens"] or 0)
        item["embedding_tokens"] += int(row["embedding_tokens"] or 0)
        item["requests"] += 1
        item["cost_usd"] += _decimal(row["cost_usd"])
    all_items = []
    for item in sorted(grouped.values(), key=lambda value: (value["provider"], value["model"])):
        item = dict(item)
        item["cost_usd"] = _money(item["cost_usd"])
        all_items.append(item)
    return {"items": all_items[offset : offset + limit], "total": len(all_items), "limit": limit, "offset": offset, "total_is_estimate": False}


def reservation_views(
    *,
    range_name: str | None = None,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    window = resolve_window(range_name or "all", from_=from_, to=to) if range_name or from_ or to else None
    db = database.connect()
    try:
        if not _table_exists(db, "reservations"):
            total = 0
            rows = []
        else:
            where, filter_params = _reservation_filter(window, status)
            total = int(db.execute(f"SELECT COUNT(*) FROM reservations{where}", filter_params).fetchone()[0])
            rows = _reservation_rows(db, window, status, limit=limit, offset=offset)
    finally:
        db.close()
    items = []
    for row in rows:
        keys = set(row.keys())
        items.append(
            {
                "id": str(row["id"]),
                "request_id": redact_text(row["request_id"], max_length=120),
                "provider": redact_text(row["provider"], max_length=80),
                "model": redact_text(row["model"], max_length=120),
                "amount_usd": _money(row["reserved_usd"]),
                "status": str(row["status"]),
                "created_at": _iso(row["created_at"]),
                "expires_at": _iso(row["expires_at"]) if "expires_at" in keys else None,
                "released_at": _iso(row["released_at"]) if "released_at" in keys else None,
                "reason": redact_text(row["reason"], max_length=300) if "reason" in keys else None,
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset, "total_is_estimate": False}


def usage_export_rows(
    range_name: str = "24h",
    *,
    from_: str | datetime | None = None,
    to: str | datetime | None = None,
    provider: str | None = None,
    model: str | None = None,
    max_rows: int = 100_000,
) -> list[dict[str, Any]]:
    window = resolve_window(range_name, from_=from_, to=to)
    if window.end - window.start > timedelta(days=90):
        raise AppException("ADMIN_EXPORT_RANGE_TOO_LARGE", "CSV导出时间范围不能超过90天", 422)
    try:
        max_rows = int(max_rows)
    except (TypeError, ValueError) as exc:
        raise AppException("ADMIN_EXPORT_TOO_LARGE", "CSV导出行数上限不合法", 422) from exc
    if max_rows < 1 or max_rows > 100_000:
        raise AppException("ADMIN_EXPORT_TOO_LARGE", "CSV导出行数上限不合法", 422)
    db = database.connect()
    try:
        if not _table_exists(db, "usage_events"):
            rows = []
        else:
            where, filter_params = _usage_filter(window, provider=provider, model=model)
            total = int(db.execute(f"SELECT COUNT(*) FROM usage_events WHERE {where}", filter_params).fetchone()[0])
            if total > max_rows:
                raise AppException("ADMIN_EXPORT_TOO_LARGE", "CSV导出行数超过上限，请缩小筛选范围", 422, {"max_rows": max_rows})
            # The count enforces the contract before any result rows are read;
            # the bounded query also keeps a concurrent append from causing an
            # unbounded response body.
            rows = _rows_in_window(db, window, provider=provider, model=model, limit=max_rows, offset=0)
    finally:
        db.close()
    return [
        {
            "time": _iso(row["created_at"]),
            "provider": redact_text(row["provider"], max_length=80),
            "model": redact_text(row["model"], max_length=120),
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "embedding_tokens": int(row["embedding_tokens"] or 0),
            "cost_usd": _csv_money(row["cost_usd"]),
            "request_id": redact_text(row["request_id"], max_length=120),
        }
        for row in rows
    ]


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def stream_usage_csv(rows: Iterable[dict[str, Any]]):
    """Emit bounded CSV chunks after the caller has validated the row limit."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    fields = ["time", "provider", "model", "input_tokens", "output_tokens", "embedding_tokens", "cost_usd", "request_id"]
    writer.writerow(fields)
    yield "\ufeff" + stream.getvalue()
    stream.seek(0)
    stream.truncate(0)
    for index, row in enumerate(rows, 1):
        writer.writerow([_csv_safe(row.get(field)) for field in fields])
        if index % 500 == 0:
            yield stream.getvalue()
            stream.seek(0)
            stream.truncate(0)
    if stream.tell():
        yield stream.getvalue()


def render_usage_csv(rows: Iterable[dict[str, Any]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    fields = ["time", "provider", "model", "input_tokens", "output_tokens", "embedding_tokens", "cost_usd", "request_id"]
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_csv_safe(row.get(field)) for field in fields])
    return "\ufeff" + stream.getvalue()


def list_datasets(*, expired: bool | None = None, limit: int = 50, offset: int = 0, now: datetime | None = None) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    current = _utc(now or datetime.now(UTC))
    db = database.connect()
    try:
        if not _table_exists(db, "datasets"):
            rows = []
            total = 0
        else:
            where = ""
            params: list[Any] = []
            if expired is True:
                where = " WHERE expires_at<=?"
                params.append(current.isoformat())
            elif expired is False:
                where = " WHERE expires_at>?"
                params.append(current.isoformat())
            total = int(db.execute(f"SELECT COUNT(*) FROM datasets{where}", params).fetchone()[0])
            rows = db.execute(
                f"SELECT dataset_id,filename,revision,confirmed_revision,current_rows_json,columns_json,created_at,expires_at FROM datasets{where} ORDER BY created_at DESC,dataset_id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
    finally:
        db.close()
    items = []
    for row in rows:
        is_expired = _expired(row["expires_at"], current)
        current_rows = _load_json(row["current_rows_json"], [])
        columns = _load_json(row["columns_json"], [])
        items.append(
            {
                "dataset_id": str(row["dataset_id"]),
                "filename": redact_text(row["filename"], max_length=255),
                "revision": int(row["revision"]),
                "confirmed_revision": int(row["confirmed_revision"]) if row["confirmed_revision"] is not None else None,
                "row_count": len(current_rows) if isinstance(current_rows, list) else 0,
                "column_count": len(columns) if isinstance(columns, list) else 0,
                "expires_at": _iso(row["expires_at"]),
                "created_at": _iso(row["created_at"]),
                "status": "expired" if is_expired else "active",
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset, "total_is_estimate": False}


def _expired(value: Any, now: datetime) -> bool:
    parsed = parse_datetime(value)
    return parsed is not None and parsed <= now


def dataset_detail(dataset_id: str) -> dict[str, Any]:
    db = database.connect()
    try:
        row = db.execute("SELECT dataset_id,filename,revision,confirmed_revision,current_rows_json,columns_json,report_json,created_at,expires_at FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone() if _table_exists(db, "datasets") else None
    finally:
        db.close()
    if not row:
        raise AppException("DATASET_NOT_FOUND", "数据集不存在", 404)
    current_rows = _load_json(row["current_rows_json"], [])
    columns_raw = _load_json(row["columns_json"], [])
    report = _load_json(row["report_json"], {})
    columns = []
    missing_cells = outliers = 0
    for column in columns_raw if isinstance(columns_raw, list) else []:
        if not isinstance(column, dict):
            continue
        missing = int(column.get("missing_count") or 0)
        outlier = int(column.get("outlier_count") or 0)
        missing_cells += missing
        outliers += outlier
        columns.append(
            {
                "name": redact_text(column.get("name", ""), max_length=200),
                "inferred_type": str(column.get("inferred_type", "string")),
                "missing_count": missing,
                "outlier_count": outlier,
                "display_format": str(column.get("display_format", "plain")),
            }
        )
    issues = report.get("issues", []) if isinstance(report, dict) else []
    safe_report = {
        "issue_count": len(issues) if isinstance(issues, list) else 0,
        "missing_cells": missing_cells,
        "outliers": outliers,
        "report_mode": report.get("mode") if isinstance(report, dict) else None,
        "removed_rows": int(report.get("removed_rows") or 0) if isinstance(report, dict) else 0,
        "filled_cells": int(report.get("filled_cells") or 0) if isinstance(report, dict) else 0,
        "type_conversions": int(report.get("type_conversions") or 0) if isinstance(report, dict) else 0,
    }
    return {
        "dataset_id": str(row["dataset_id"]),
        "filename": redact_text(row["filename"], max_length=255),
        "revision": int(row["revision"]),
        "confirmed_revision": int(row["confirmed_revision"]) if row["confirmed_revision"] is not None else None,
        "row_count": len(current_rows) if isinstance(current_rows, list) else 0,
        "column_count": len(columns),
        "expires_at": _iso(row["expires_at"]),
        "created_at": _iso(row["created_at"]),
        "status": "expired" if _expired(row["expires_at"], datetime.now(UTC)) else "active",
        "columns": columns,
        "quality": safe_report,
    }


def _discussion_state(row: Any) -> dict[str, Any]:
    state = _load_json(row["state_json"], {})
    return state if isinstance(state, dict) else {}


def list_discussions(*, status: str | None = None, active: bool | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    allowed = {"created", "round_done", "round_error", "error", "finished", "cancelled"}
    if status and status not in allowed:
        raise AppException("DISCUSSION_STATUS_INVALID", "研讨会话状态不合法", 422)
    db = database.connect()
    try:
        if not _table_exists(db, "discussion_sessions"):
            rows = []
            total = 0
        else:
            clauses: list[str] = []
            params: list[Any] = []
            if status:
                clauses.append("status=?")
                params.append(status)
            if active is True:
                clauses.append("status NOT IN ('finished','cancelled')")
            elif active is False:
                clauses.append("status IN ('finished','cancelled')")
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = int(db.execute(f"SELECT COUNT(*) FROM discussion_sessions{where}", params).fetchone()[0])
            rows = db.execute(f"SELECT * FROM discussion_sessions{where} ORDER BY expires_at DESC,session_id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        session_ids = [str(row["session_id"]) for row in rows]
        command_map = _discussion_command_statuses(db, session_ids)
        event_counts, event_times = _discussion_event_stats(db, session_ids)
        command_times = _discussion_command_times(db, session_ids)
    finally:
        db.close()
    items = []
    for row in rows:
        state = _discussion_state(row)
        actual_status = str(row["status"])
        if actual_status not in allowed:
            actual_status = "error"
        is_active = actual_status not in {"finished", "cancelled"}
        if status and actual_status != status:
            continue
        if active is not None and active != is_active:
            continue
        session_id = str(row["session_id"])
        command_status = command_map.get(session_id, "none")
        event_count = event_counts.get(session_id, 0)
        times = [item for item in (event_times.get(session_id, []) + command_times.get(session_id, [])) if item]
        parsed_times = [parse_datetime(item) for item in times]
        parsed_times = [item for item in parsed_times if item]
        created_at = _iso(min(parsed_times)) if parsed_times else _iso(row["expires_at"])
        updated = _iso(max(parsed_times)) if parsed_times else _iso(row["expires_at"])
        items.append(
            {
                "session_id": session_id,
                "project_id": redact_text(state.get("project_id", ""), max_length=200),
                "topic": redact_text(state.get("topic", ""), max_length=500),
                "status": actual_status,
                "command_status": command_status,
                "event_count": event_count,
                "generation": int(row["lease_generation"] or 0),
                "lease_owner": redact_text(row["lease_owner"], max_length=100) if row["lease_owner"] else None,
                "lease_until": _iso(row["lease_until"]),
                "created_at": created_at,
                "updated_at": updated,
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset, "total_is_estimate": False}


def _discussion_command_statuses(db, session_ids: Sequence[str]) -> dict[str, str]:
    if not session_ids or not _table_exists(db, "discussion_commands"):
        return {}
    marks = ",".join("?" for _ in session_ids)
    rows = db.execute(f"SELECT session_id,status FROM discussion_commands WHERE session_id IN ({marks}) ORDER BY rowid DESC", list(session_ids)).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["session_id"]), []).append(str(row["status"]))
    result: dict[str, str] = {}
    for session_id, values in grouped.items():
        result[session_id] = next((candidate for candidate in ("running", "pending", "failed", "cancelled", "completed") if candidate in values), "none")
    return result


def _discussion_event_stats(db, session_ids: Sequence[str]) -> tuple[dict[str, int], dict[str, list[str]]]:
    if not session_ids or not _table_exists(db, "discussion_events"):
        return {}, {}
    marks = ",".join("?" for _ in session_ids)
    rows = db.execute(f"SELECT session_id,COUNT(*) AS count,MIN(created_at) AS first_at,MAX(created_at) AS last_at FROM discussion_events WHERE session_id IN ({marks}) GROUP BY session_id", list(session_ids)).fetchall()
    counts = {str(row["session_id"]): int(row["count"]) for row in rows}
    times = {str(row["session_id"]): [str(row["first_at"]), str(row["last_at"])] for row in rows}
    return counts, times


def _discussion_command_times(db, session_ids: Sequence[str]) -> dict[str, list[str]]:
    if not session_ids or not _table_exists(db, "discussion_commands"):
        return {}
    marks = ",".join("?" for _ in session_ids)
    rows = db.execute(f"SELECT session_id,MIN(COALESCE(picked_at,completed_at)) AS first_at,MAX(COALESCE(completed_at,picked_at)) AS last_at FROM discussion_commands WHERE session_id IN ({marks}) GROUP BY session_id", list(session_ids)).fetchall()
    return {str(row["session_id"]): [item for item in (row["first_at"], row["last_at"]) if item] for row in rows}


def _command_status(session_id: str) -> str:
    db = database.connect()
    try:
        if not _table_exists(db, "discussion_commands"):
            return "none"
        rows = db.execute("SELECT status FROM discussion_commands WHERE session_id=? ORDER BY rowid DESC", (session_id,)).fetchall()
    finally:
        db.close()
    statuses = [str(row[0]) for row in rows]
    for candidate in ("running", "pending", "failed", "cancelled", "completed"):
        if candidate in statuses:
            return candidate
    return "none"


def _event_count(session_id: str) -> int:
    db = database.connect()
    try:
        if not _table_exists(db, "discussion_events"):
            return 0
        return int(db.execute("SELECT COUNT(*) FROM discussion_events WHERE session_id=?", (session_id,)).fetchone()[0])
    finally:
        db.close()


def _discussion_timestamps(session_id: str, expires_at: Any) -> list[str]:
    db = database.connect()
    try:
        values: list[str] = []
        if _table_exists(db, "discussion_events"):
            values.extend(str(row[0]) for row in db.execute("SELECT created_at FROM discussion_events WHERE session_id=?", (session_id,)).fetchall() if row[0])
        if _table_exists(db, "discussion_commands"):
            values.extend(str(row[0]) for row in db.execute("SELECT picked_at FROM discussion_commands WHERE session_id=? AND picked_at IS NOT NULL", (session_id,)).fetchall())
            values.extend(str(row[0]) for row in db.execute("SELECT completed_at FROM discussion_commands WHERE session_id=? AND completed_at IS NOT NULL", (session_id,)).fetchall())
        return values
    finally:
        db.close()


def _discussion_created_at(session_id: str, fallback: Any) -> str | None:
    values = _discussion_timestamps(session_id, fallback)
    parsed = [parse_datetime(item) for item in values]
    parsed = [item for item in parsed if item]
    return _iso(min(parsed)) if parsed else _iso(fallback)


def _discussion_updated_at(session_id: str, fallback: Any) -> str | None:
    values = _discussion_timestamps(session_id, fallback)
    parsed = [parse_datetime(item) for item in values]
    parsed = [item for item in parsed if item]
    return _iso(max(parsed)) if parsed else _iso(fallback)


def discussion_events(session_id: str, *, after_seq: int = 0, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    if after_seq < 0:
        raise AppException("ADMIN_PAGINATION_INVALID", "after_seq不能为负数", 422)
    db = database.connect()
    try:
        if not _table_exists(db, "discussion_events"):
            rows = []
            total = 0
        else:
            total = int(db.execute("SELECT COUNT(*) FROM discussion_events WHERE session_id=? AND event_seq>?", (session_id, after_seq)).fetchone()[0])
            rows = db.execute("SELECT event_seq,event_type,client_message_id,payload_json,created_at FROM discussion_events WHERE session_id=? AND event_seq>? ORDER BY event_seq ASC LIMIT ? OFFSET ?", (session_id, after_seq, limit, offset)).fetchall()
    finally:
        db.close()
    if not rows and not _discussion_exists(session_id):
        raise AppException("DISCUSSION_NOT_FOUND", "研讨会话不存在", 404)
    items = []
    for row in rows:
        payload = _load_json(row["payload_json"], {})
        summary = _event_summary(payload)
        items.append({"event_seq": int(row["event_seq"]), "event_type": redact_text(row["event_type"], max_length=80), "client_message_id": redact_text(row["client_message_id"], max_length=120) if row["client_message_id"] else None, "created_at": _iso(row["created_at"]), "summary": summary})
    return {"items": items, "total": total, "limit": limit, "offset": offset, "total_is_estimate": False}


def _event_summary(payload: Any) -> dict[str, Any] | str:
    if isinstance(payload, dict):
        allowed = {"type", "session_id", "event_seq", "timestamp", "reply_to_client_message_id", "session_status", "round", "agent", "recoverable", "error", "summary"}
        value = {key: safe_json(item, max_length=800, max_items=10) for key, item in payload.items() if key in allowed}
        if "content" in payload:
            value["content"] = redact_text(payload["content"], max_length=800)
        return value
    return redact_text(payload, max_length=800)


def discussion_commands(session_id: str, *, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    db = database.connect()
    try:
        if _table_exists(db, "discussion_commands"):
            params: list[Any] = [session_id]
            where = "session_id=?"
            if status:
                where += " AND status=?"
                params.append(status)
            total = int(db.execute(f"SELECT COUNT(*) FROM discussion_commands WHERE {where}", params).fetchone()[0])
            rows = db.execute(f"SELECT client_message_id,status,picked_at,completed_at,payload_json,error_json FROM discussion_commands WHERE {where} ORDER BY rowid DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        else:
            total = 0
            rows = []
    finally:
        db.close()
    if not rows and not _discussion_exists(session_id):
        raise AppException("DISCUSSION_NOT_FOUND", "研讨会话不存在", 404)
    items = []
    for row in rows:
        payload = _load_json(row["payload_json"], {})
        error = _load_json(row["error_json"], None)
        payload_summary = safe_json({key: payload.get(key) for key in ("type", "topic", "project_id", "dataset_id", "revision") if isinstance(payload, dict) and key in payload}, max_length=300)
        items.append({"client_message_id": redact_text(row["client_message_id"], max_length=120), "status": redact_text(row["status"], max_length=40), "picked_at": _iso(row["picked_at"]), "completed_at": _iso(row["completed_at"]), "payload_summary": payload_summary, "error_summary": safe_json(error, max_length=500) if error else None})
    return {"items": items, "total": total, "limit": limit, "offset": offset, "total_is_estimate": False}


def _discussion_exists(session_id: str) -> bool:
    db = database.connect()
    try:
        return bool(_table_exists(db, "discussion_sessions") and db.execute("SELECT 1 FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone())
    finally:
        db.close()


def list_files(*, kind: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0, now: datetime | None = None) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    current = _utc(now or datetime.now(UTC))
    db = database.connect()
    try:
        if not _table_exists(db, "files"):
            rows = []
            total = 0
        else:
            clauses: list[str] = []
            params: list[Any] = []
            if status in {"ready", "missing", "expired"}:
                # ready/missing are filesystem-derived and cannot be selected
                # safely by SQL; fetch a bounded page and filter below.
                if status == "expired":
                    clauses.append("expires_at<=?")
                    params.append(current.isoformat())
            elif status:
                raise AppException("ADMIN_FILE_QUERY_INVALID", "文件状态不合法", 422)
            if kind and kind != "ppt":
                return {"items": [], "total": 0, "limit": limit, "offset": offset, "total_is_estimate": False}
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = int(db.execute(f"SELECT COUNT(*) FROM files{where}", params).fetchone()[0])
            rows = db.execute(f"SELECT * FROM files{where} ORDER BY created_at DESC,file_id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    finally:
        db.close()
    items = []
    for row in rows:
        item = _file_view(row, current)
        if kind and item["kind"] != kind:
            continue
        if status and item["status"] != status:
            continue
        items.append(item)
    # For filesystem-derived ready/missing filters, the SQL count is only an
    # estimate because a row can change between stat and response.  The page
    # itself remains bounded and stable.
    total_is_estimate = status in {"ready", "missing"}
    return {"items": items, "total": total, "limit": limit, "offset": offset, "total_is_estimate": total_is_estimate}


def _file_view(row: Any, now: datetime) -> dict[str, Any]:
    path = Path(str(row["disk_path"])).resolve()
    expired = _expired(row["expires_at"], now)
    exists = False
    size = 0
    try:
        # The DB record is the authority.  The path is used only for a bounded
        # existence/stat check and is never returned to the caller.
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
    except OSError:
        exists = False
    status = "expired" if expired else "ready" if exists else "missing"
    integrity = "ok" if exists else "missing"
    return {"file_id": str(row["file_id"]), "display_name": redact_text(row["display_name"], max_length=255), "kind": "ppt", "status": status, "size_bytes": size, "created_at": _iso(row["created_at"]), "expires_at": _iso(row["expires_at"]), "integrity_status": integrity}


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def storage_view() -> dict[str, Any]:
    data_path = database.DATA_DIR.resolve()
    generated_path = Path(ppt_service.OUTPUT_DIR).resolve()
    logs_path = Path(LOG_DIR).resolve()
    root = data_path.anchor or str(data_path)
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = 0
    directories = []
    for label, path in (("data", data_path), ("generated_ppts", generated_path), ("logs", logs_path)):
        exists = path.exists()
        directories.append({"path_label": label, "exists": exists, "used_bytes": _directory_size(path) if exists else 0, "free_bytes": free, "status": "ready" if exists else "not_initialized"})
    return {"directories": directories, "used_bytes": sum(item["used_bytes"] for item in directories), "free_bytes": free, "calculated_at": _iso(datetime.now(UTC)), "data_source": "filesystem", "freshness": "fresh"}


def health_view() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    db_ok = True
    try:
        db = database.connect()
        try:
            db.execute("SELECT 1").fetchone()
            wal_exists = Path(str(database.DB_PATH) + "-wal").exists()
            checks.append({"name": "database", "status": "ok", "detail": "sqlite可读"})
            checks.append({"name": "wal", "status": "ok" if wal_exists or not database.DB_PATH.exists() else "warning", "detail": "WAL状态已检查"})
        finally:
            db.close()
    except Exception as exc:
        db_ok = False
        checks.append({"name": "database", "status": "error", "detail": type(exc).__name__})
    for name, path in (("data", database.DATA_DIR), ("generated_ppts", ppt_service.OUTPUT_DIR), ("logs", LOG_DIR)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            writable = os.access(path, os.W_OK)
        except OSError:
            writable = False
        checks.append({"name": name, "status": "ok" if writable else "warning", "detail": "目录可写" if writable else "目录不可写"})
    chroma_path = Path(getattr(rag_service, "persist_directory", ""))
    if not chroma_path.exists():
        checks.append({"name": "chroma", "status": "unknown", "detail": "尚未初始化"})
    else:
        try:
            collections = rag_service._admin_collections()
            checks.append({"name": "chroma", "status": "ok", "detail": f"metadata可读，{len(collections)}个集合"})
        except Exception as exc:
            logger.info("chroma metadata health check failed", exc_info=True)
            checks.append({"name": "chroma", "status": "warning", "detail": type(exc).__name__})
    bad = sum(check["status"] == "error" for check in checks)
    warning = sum(check["status"] in {"warning", "unknown"} for check in checks)
    overall = "unavailable" if not db_ok else "degraded" if bad or warning else "healthy"
    return {"status": overall, "checks": checks, "calculated_at": _iso(datetime.now(UTC)), "data_source": "sqlite|filesystem|chroma", "freshness": "fresh" if not bad else "stale"}


def _cursor_encode(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _cursor_decode(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        raise AppException("ADMIN_CURSOR_INVALID", "日志游标无效", 422)


def _file_identity(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        # Size and mtime describe the cursor position, not the file identity:
        # appending a line must not make the next tail request replay the whole
        # file.  Device/inode remain stable for appends and change on rotation.
        return {"name": path.name, "device": int(getattr(stat, "st_dev", 0)), "inode": int(getattr(stat, "st_ino", 0))}
    except OSError:
        return {"name": path.name, "device": 0, "inode": 0}


def _log_paths(include_rotated: bool) -> list[Path]:
    main = Path(LOG_DIR) / "app.log"
    paths = [main]
    if include_rotated:
        paths.extend(sorted((Path(LOG_DIR)).glob("app.log.*"), key=lambda item: item.name, reverse=True))
    return [path for path in paths if path.is_file()]


def _parse_log_line(raw: str) -> dict[str, Any]:
    line = raw.rstrip("\r\n")
    match = _LOG_LINE.match(line)
    if match:
        created = match.group("created").replace(",", ".")
        try:
            parsed = datetime.fromisoformat(created).replace(tzinfo=UTC)
            created_at = parsed.isoformat().replace("+00:00", "Z")
        except ValueError:
            created_at = None
        level = match.group("level").upper()
        message = f"{match.group('logger')} {match.group('message')}".strip()
    else:
        created_at = None
        level = "INFO"
        message = line
    return {"created_at": created_at, "level": level, "message": redact_text(message, max_length=MAX_TEXT), "truncated": len(message) > MAX_TEXT}


def read_logs(*, level: str | None = None, tail: int = 200, cursor: str | None = None, max_bytes: int = MAX_LOG_BYTES, include_rotated: bool = False) -> dict[str, Any]:
    try:
        tail = int(tail)
        max_bytes = int(max_bytes)
    except (TypeError, ValueError) as exc:
        raise AppException("ADMIN_LOG_QUERY_INVALID", "日志参数必须是整数", 422) from exc
    if tail < 1 or tail > MAX_LOG_TAIL or max_bytes < 1 or max_bytes > MAX_LOG_BYTES:
        raise AppException("ADMIN_LOG_QUERY_INVALID", f"tail范围为1-{MAX_LOG_TAIL}，max_bytes范围为1-{MAX_LOG_BYTES}", 422)
    if level and level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise AppException("ADMIN_LOG_QUERY_INVALID", "日志级别不合法", 422)
    paths = _log_paths(include_rotated)
    if not paths:
        return {"lines": [], "cursor": None, "file_identity": None, "freshness": "unknown"}
    main = paths[0]
    current_identity = _file_identity(main)
    try:
        current_size = main.stat().st_size
    except OSError:
        current_size = 0
    decoded = _cursor_decode(cursor)
    offset = 0
    reset = False
    if decoded:
        saved_identity = decoded.get("file")
        try:
            saved_offset = int(decoded.get("offset", 0))
        except (TypeError, ValueError):
            saved_offset = 0
        if saved_identity == current_identity and 0 <= saved_offset <= current_size:
            offset = saved_offset
        else:
            # Rotation, replacement, or truncation: start at a bounded safe
            # position in the new file and tell the caller why continuity was
            # lost.  Never seek using an untrusted path from the cursor.
            reset = True
            offset = max(0, current_size - max_bytes)
    chunks: list[str] = []
    # Cursor reads only the current file.  Without a cursor, tail the bounded
    # end of the configured files; rotated files are read oldest-to-newest for
    # a stable display order.
    read_paths = [main] if decoded else [main, *list(reversed(paths[1:]))]
    remaining = max_bytes
    next_offset = offset if decoded else current_size
    for path in read_paths:
        try:
            with path.open("rb") as stream:
                if path == main and decoded:
                    stream.seek(offset)
                elif not decoded:
                    size = path.stat().st_size
                    stream.seek(max(0, size - remaining))
                data = stream.read(remaining)
                if path == main and decoded:
                    next_offset = offset + len(data)
            remaining -= len(data)
            if data:
                chunks.append(data.decode("utf-8", errors="replace"))
        except OSError:
            continue
        if remaining <= 0:
            break
    raw_lines = "\n".join(chunks).splitlines()[-tail:]
    lines = [_parse_log_line(line) for line in raw_lines]
    if level:
        lines = [line for line in lines if line["level"] == level.upper()]
    next_cursor = _cursor_encode({"file": current_identity, "offset": next_offset, "generated_at": _iso(datetime.now(UTC))})
    return {"lines": lines, "cursor": next_cursor, "file_identity": current_identity, "freshness": "fresh", "reset": reset}


def activity_events(*, level: str | None = None, category: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    allowed_levels = {"info", "warning", "error"}
    allowed_categories = {"usage", "maintenance", "discussion", "ppt", "rag", "config", "security", "system"}
    if level and level not in allowed_levels:
        raise AppException("ADMIN_ACTIVITY_QUERY_INVALID", "事件级别不合法", 422)
    if category and category not in allowed_categories:
        raise AppException("ADMIN_ACTIVITY_QUERY_INVALID", "事件分类不合法", 422)
    db = database.connect()
    try:
        if not _table_exists(db, "operation_events"):
            rows = []
        else:
            clauses: list[str] = []
            params: list[Any] = []
            if level:
                clauses.append("level=?")
                params.append(level)
            if category:
                clauses.append("category=?")
                params.append(category)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            # Deduplication is applied after reading. Bound the candidate
            # query so a long-lived event table cannot turn a paginated poll
            # into an unbounded read. The response marks the count as an
            # estimate when this bound is reached.
            candidate_limit = min(20_000, max(1_000, (offset + limit) * 8))
            rows = db.execute(
                f"SELECT id,level,category,event_key,message,operation_id,context_json,created_at FROM operation_events{where} ORDER BY created_at DESC,id DESC LIMIT ?",
                [*params, candidate_limit],
            ).fetchall()
    finally:
        db.close()
    unique: list[dict[str, Any]] = []
    last_seen: dict[str, datetime] = {}
    for row in rows:
        event_key = str(row["event_key"])
        created = parse_datetime(row["created_at"]) or datetime.min.replace(tzinfo=UTC)
        previous = last_seen.get(event_key)
        if previous and abs((previous - created).total_seconds()) < 300:
            continue
        last_seen[event_key] = created
        unique.append({"id": str(row["id"]), "level": str(row["level"]), "category": str(row["category"]), "message": redact_text(row["message"], max_length=500), "operation_id": str(row["operation_id"]) if row["operation_id"] else None, "context": safe_json(_load_json(row["context_json"], {}), max_length=500), "created_at": _iso(row["created_at"])})
    return {"items": unique[offset : offset + limit], "total": len(unique), "limit": limit, "offset": offset, "total_is_estimate": len(rows) >= candidate_limit if 'candidate_limit' in locals() else False}


def session_counts() -> dict[str, int]:
    db = database.connect()
    try:
        if not _table_exists(db, "discussion_sessions"):
            return {"active": 0, "running": 0, "needs_recovery": 0}
        now = datetime.now(UTC)
        terminal = "s.status NOT IN ('finished','cancelled')"
        active = int(db.execute(f"SELECT COUNT(*) FROM discussion_sessions s WHERE {terminal}").fetchone()[0])
        if not _table_exists(db, "discussion_commands"):
            errors = int(db.execute(f"SELECT COUNT(*) FROM discussion_sessions s WHERE {terminal} AND s.status IN ('round_error','error')").fetchone()[0])
            return {"active": active, "running": 0, "needs_recovery": errors}
        now_iso = now.isoformat()
        running = int(db.execute(
            f"SELECT COUNT(*) FROM discussion_sessions s WHERE {terminal} AND s.lease_owner IS NOT NULL AND s.lease_until>? AND EXISTS (SELECT 1 FROM discussion_commands c WHERE c.session_id=s.session_id AND c.status='running')",
            (now_iso,),
        ).fetchone()[0])
        needs_recovery = int(db.execute(
            f"SELECT COUNT(*) FROM discussion_sessions s WHERE {terminal} AND (s.status IN ('round_error','error') OR (NOT (s.lease_owner IS NOT NULL AND s.lease_until>?) AND EXISTS (SELECT 1 FROM discussion_commands c WHERE c.session_id=s.session_id AND c.status IN ('pending','running','failed'))))",
            (now_iso,),
        ).fetchone()[0])
        return {"active": active, "running": running, "needs_recovery": needs_recovery}
    finally:
        db.close()


def _parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def budget_view() -> dict[str, Any]:
    settings = get_settings()
    db = database.connect()
    try:
        all_usage = db.execute("SELECT cost_usd FROM usage_events").fetchall() if _table_exists(db, "usage_events") else []
        reservations = db.execute("SELECT status,reserved_usd FROM reservations").fetchall() if _table_exists(db, "reservations") else []
    finally:
        db.close()
    known = sum((_decimal(row["cost_usd"]) for row in all_usage), Decimal("0"))
    totals = _reservation_totals(reservations)
    limit = _decimal(getattr(settings, "MAX_BUDGET_USD", 0))
    held = _decimal(totals["reserved_usd"])
    remaining = max(Decimal("0"), limit - known - held)
    progress = None if limit <= 0 else min(100.0, float((known + held) / limit * 100))
    return {"revision": settings.CONFIG_REVISION, "limit_usd": _money(limit), "known_cost_usd": _money(known), "reserved_usd": _money(held), "remaining_usd": _money(remaining), "usage_unknown_usd": totals["usage_unknown_usd"], "provider_overrun_usd": totals["provider_overrun_usd"], "progress_percent": progress, "calculated_at": _iso(datetime.now(UTC)), "data_source": "sqlite", "freshness": "fresh"}


def file_counts() -> dict[str, int]:
    counts = {"ready": 0, "missing": 0, "expired": 0}
    db = database.connect()
    try:
        if not _table_exists(db, "files"):
            return counts
        rows = db.execute("SELECT expires_at,disk_path FROM files").fetchall()
    finally:
        db.close()
    current = datetime.now(UTC)
    for row in rows:
        if _expired(row["expires_at"], current):
            counts["expired"] += 1
            continue
        try:
            if Path(str(row["disk_path"])).resolve().is_file():
                counts["ready"] += 1
            else:
                counts["missing"] += 1
        except OSError:
            counts["missing"] += 1
    return counts


def dashboard_overview() -> dict[str, Any]:
    now = datetime.now(UTC)
    health = health_view()
    usage_today = usage_summary(from_=now.replace(hour=0, minute=0, second=0, microsecond=0), to=now, include_buckets=False)
    return {
        "health": health,
        "budget": budget_view(),
        "usage_today": {key: usage_today[key] for key in ("cost_usd", "requests", "input_tokens", "output_tokens", "embedding_tokens", "calculated_at", "data_source", "freshness")},
        "sessions": {**session_counts(), "calculated_at": _iso(now), "data_source": "sqlite", "freshness": "fresh"},
        "files": {**file_counts(), "calculated_at": _iso(now), "data_source": "sqlite|filesystem", "freshness": "fresh"},
        "storage": storage_view(),
        "trend": usage_trends("24h", "cost", now=now),
        "activity": activity_events(limit=20, offset=0)["items"],
    }


async def rag_projects(*, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    try:
        raw = await rag_service.admin_projects()
    except Exception as exc:
        logger.info("rag project metadata unavailable", exc_info=True)
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "total_is_estimate": False, "degraded": True, "error": type(exc).__name__}
    items = []
    for item in raw or []:
        project_id = redact_text(item.get("project_id", ""), max_length=200)
        items.append({"project_id": project_id, "name": project_id, "document_count": int(item.get("documents", item.get("document_count", 0)) or 0), "chunk_count": int(item.get("chunks", item.get("chunk_count", 0)) or 0), "legacy": project_id == "__legacy_unassigned__", "freshness": "fresh"})
    items.sort(key=lambda item: item["project_id"])
    return {"items": items[offset : offset + limit], "total": len(items), "limit": limit, "offset": offset, "total_is_estimate": False}


async def rag_documents(project_id: str, *, limit: int = 50, offset: int = 0, filename: str | None = None) -> dict[str, Any]:
    limit, offset = _limit_offset(limit, offset)
    if not project_id:
        raise AppException("PROJECT_REQUIRED", "项目不能为空", 422)
    try:
        # Prefer the metadata-only helper supplied by the RAG service.  It does
        # not initialize an embedding client or make an LLM request.
        raw = await rag_service.admin_documents(project_id)
    except Exception as exc:
        logger.info("rag document metadata unavailable", exc_info=True)
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "total_is_estimate": False, "degraded": True, "error": type(exc).__name__}
    items = []
    for item in raw or []:
        source = str(item.get("filename", ""))
        if filename and filename.lower() not in source.lower():
            continue
        items.append({"document_id": redact_text(item.get("document_id", ""), max_length=200), "filename": redact_text(source, max_length=255), "chunk_count": int(item.get("chunks", item.get("chunk_count", 0)) or 0), "collection_count": int(item.get("collection_count", 1) or 1), "created_at": _iso(item.get("created_at")), "metadata_summary": safe_json(item.get("metadata_summary", {}), max_length=600)})
    items.sort(key=lambda item: (item["filename"], item["document_id"]))
    return {"items": items[offset : offset + limit], "total": len(items), "limit": limit, "offset": offset, "total_is_estimate": False}


async def rag_collections() -> dict[str, Any]:
    try:
        collections = await __import__("asyncio").to_thread(rag_service._admin_collections)
    except Exception as exc:
        return {"items": [], "total": 0, "degraded": True, "error": type(exc).__name__}
    items = []
    for collection in collections:
        name = str(getattr(collection, "name", ""))
        project_ids: set[str] = set()
        documents: set[str] = set()
        try:
            for offset in range(0, int(collection.count()), 500):
                rows = collection.get(limit=500, offset=offset, include=["metadatas"])
                for metadata in rows.get("metadatas", []) or []:
                    metadata = metadata or {}
                    project_ids.add(str(metadata.get("project_id") or "__legacy_unassigned__"))
                    documents.add(str(metadata.get("document_id") or "__unassigned__"))
        except Exception:
            return {"items": items, "total": len(items), "degraded": True, "error": "COLLECTION_READ_FAILED"}
        items.append({"name": redact_text(name, max_length=120), "model_fingerprint": name.removeprefix("qc_"), "project_count": len(project_ids), "document_count": len(documents), "status": "ready"})
    return {"items": items, "total": len(items), "degraded": False}
