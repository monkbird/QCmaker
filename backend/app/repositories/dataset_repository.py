from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException
from backend.app.models.contracts import CleaningReport, ColumnInfo, DataRow, DatasetResponse
from backend.app.repositories.database import connect, transaction


def _dump(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _from_row(row, restored_from_revision: int | None = None) -> DatasetResponse:
    return DatasetResponse(dataset_id=row["dataset_id"], revision=row["revision"], confirmed_revision=row["confirmed_revision"], restored_from_revision=restored_from_revision, filename=row["filename"], columns=[ColumnInfo.model_validate(x) for x in json.loads(row["columns_json"])], rows=[DataRow.model_validate(x) for x in json.loads(row["current_rows_json"])], report=CleaningReport.model_validate(json.loads(row["report_json"])))


def create(filename: str, rows: list[DataRow], columns: list[ColumnInfo], report: CleaningReport) -> DatasetResponse:
    dataset_id = f"ds_{uuid4().hex}"; now = datetime.now(UTC); expires = now + timedelta(hours=get_settings().DATASET_TTL_HOURS)
    with transaction(immediate=True) as db:
        db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?)", (dataset_id, filename, 0, None, _dump(rows), _dump(rows), _dump(columns), _dump(report), now.isoformat(), expires.isoformat()))
        row = db.execute("SELECT * FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    return _from_row(row)


def get(dataset_id: str) -> DatasetResponse:
    db = connect()
    try: row = db.execute("SELECT * FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    finally: db.close()
    if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC): raise AppException("SESSION_NOT_FOUND", "数据集不存在或已过期", 404)
    return _from_row(row)


def raw_rows(dataset_id: str) -> list[DataRow]:
    db = connect()
    try: row = db.execute("SELECT raw_rows_json FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    finally: db.close()
    if not row: raise AppException("SESSION_NOT_FOUND", "数据集不存在或已过期", 404)
    return [DataRow.model_validate(x) for x in json.loads(row[0])]


def update(dataset_id: str, base_revision: int, rows: list[DataRow], columns: list[ColumnInfo], report: CleaningReport, restored: bool = False) -> DatasetResponse:
    with transaction(immediate=True) as db:
        row = db.execute("SELECT revision FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        if not row: raise AppException("SESSION_NOT_FOUND", "数据集不存在或已过期", 404)
        if row["revision"] != base_revision: raise AppException("DATA_REVISION_CONFLICT", "数据版本已变化，请刷新后重试", 409, {"current_revision": row["revision"]})
        revision = base_revision + 1
        db.execute("UPDATE datasets SET revision=?,confirmed_revision=NULL,current_rows_json=?,columns_json=?,report_json=? WHERE dataset_id=? AND revision=?", (revision, _dump(rows), _dump(columns), _dump(report), dataset_id, base_revision))
        updated = db.execute("SELECT * FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    return _from_row(updated, 0 if restored else None)


def confirm(dataset_id: str, revision: int) -> DatasetResponse:
    with transaction(immediate=True) as db:
        row = db.execute("SELECT revision FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        if not row: raise AppException("SESSION_NOT_FOUND", "数据集不存在或已过期", 404)
        if row["revision"] != revision: raise AppException("DATA_REVISION_CONFLICT", "只能确认当前数据版本", 409, {"current_revision": row["revision"]})
        db.execute("UPDATE datasets SET confirmed_revision=? WHERE dataset_id=?", (revision, dataset_id))
        updated = db.execute("SELECT * FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
    return _from_row(updated)
