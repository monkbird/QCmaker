from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from backend.app.core.errors import AppException
from backend.app.models.contracts import CleaningIssue, CleaningReport, CleaningRule, ColumnInfo, DataRow


def normalize_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or value is pd.NA or pd.isna(value): return None
    if hasattr(value, "item"): value = value.item()
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, int) and abs(value) > 9_007_199_254_740_991: return str(value)
    if isinstance(value, float): return value if math.isfinite(value) else None
    if isinstance(value, (str, bool, int)): return value
    return str(value)


def parse_file(content: bytes, filename: str) -> pd.DataFrame:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if suffix == "csv":
            text = None
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    text = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None: raise ValueError("encoding")
            reader = csv.reader(io.StringIO(text))
            header = next(reader)
            if not header or len(header) > 200: raise ValueError("columns")
            records = []
            for record in reader:
                if not record: continue
                if len(record) != len(header): raise ValueError("row width")
                records.append(record)
                if len(records) > 5000: raise ValueError("rows")
            frame = pd.DataFrame(records, columns=header).replace("", None)
        elif suffix in {"xls", "xlsx"}:
            if suffix == "xlsx" or zipfile.is_zipfile(io.BytesIO(content)):
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    entries = archive.infolist()
                    if len(entries) > 2000 or sum(x.file_size for x in entries) > 40 * 1024 * 1024:
                        raise ValueError("expanded workbook too large")
            frame = pd.read_excel(io.BytesIO(content), dtype=object, header=None, nrows=5002)
            if frame.empty: raise ValueError("empty workbook")
            header = frame.iloc[0].tolist()
            frame = frame.iloc[1:].reset_index(drop=True)
            frame.columns = header
        else:
            raise ValueError("unsupported extension")
        if frame.empty or len(frame) > 5000 or len(frame.columns) > 200: raise ValueError("size")
        names = [str(column).strip() if pd.notna(column) else "" for column in frame.columns]
        names = [name or f"未命名列_{index + 1}" for index, name in enumerate(names)]
        if len(set(names)) != len(names):
            raise AppException("DATA_DUPLICATE_COLUMNS", "列名去除首尾空格后重复，请修改表头后上传", 400)
        frame.columns = names
    except AppException:
        raise
    except Exception as exc:
        raise AppException("DATA_FORMAT_UNSUPPORTED", "文件为空、损坏或超出限制（5000 行、200 列；Excel 解压后 40MB）", 400) from exc
    return frame


def rows_from_frame(frame: pd.DataFrame) -> list[DataRow]:
    return [DataRow(row_id=f"row_{position + 1}", values={str(k): normalize_scalar(v) for k, v in row.items()}) for position, (_, row) in enumerate(frame.iterrows())]


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def analyze(rows: list[DataRow], mode: str = "detected", applied_rules: list[CleaningRule] | None = None) -> tuple[list[ColumnInfo], CleaningReport]:
    names = list(rows[0].values) if rows else []; issues: list[CleaningIssue] = []; columns: list[ColumnInfo] = []
    empty_rows = [row.row_id for row in rows if all(value is None or value == "" for value in row.values.values())]
    if empty_rows: issues.append(CleaningIssue(issue_type="empty_row", row_ids=empty_rows, suggested_actions=["drop_rows", "keep"]))
    total_rows = [row.row_id for row in rows if any(re.search(r"合计|总计|total", str(value), re.I) for value in row.values.values())]
    if total_rows: issues.append(CleaningIssue(issue_type="total_row", row_ids=total_rows, suggested_actions=["drop_rows", "keep"]))
    outlier_total = 0
    for name in names:
        values = [row.values.get(name) for row in rows]; missing = [row.row_id for row in rows if _is_blank(row.values.get(name))]

        nonempty = [value for value in values if value not in (None, "")]
        percent = bool(nonempty) and sum(isinstance(value, str) and value.strip().endswith("%") for value in nonempty) >= len(nonempty) / 2
        numeric = pd.to_numeric(pd.Series(nonempty), errors="coerce") if nonempty else pd.Series(dtype=float)
        inferred = "boolean" if nonempty and all(isinstance(x, bool) or str(x).lower() in {"true", "false"} for x in nonempty) else "percent" if percent else "number" if len(nonempty) and numeric.notna().mean() >= 0.8 else "string"
        if missing: issues.append(CleaningIssue(issue_type="missing", column=name, row_ids=missing, suggested_actions=(["median", "forward_fill", "keep"] if inferred == "number" else ["forward_fill", "keep"])))
        if percent: issues.append(CleaningIssue(issue_type="type_conversion", column=name, row_ids=[row.row_id for row in rows if isinstance(row.values.get(name), str) and row.values[name].strip().endswith("%")], suggested_actions=["convert_percent", "keep"]))
        outliers: list[str] = []
        if inferred == "number" and numeric.notna().sum() >= 4:
            q1, q3 = numeric.quantile([0.25, 0.75]); iqr = q3 - q1; low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            for row in rows:
                number = pd.to_numeric(pd.Series([row.values.get(name)]), errors="coerce").iloc[0]
                if pd.notna(number) and (number < low or number > high): outliers.append(row.row_id)
        if outliers: outlier_total += len(outliers); issues.append(CleaningIssue(issue_type="outlier", column=name, row_ids=outliers, suggested_actions=["keep"]))
        columns.append(ColumnInfo(name=name, inferred_type=inferred, missing_count=len(missing), outlier_count=len(outliers), display_format="percent" if percent else "plain"))
    return columns, CleaningReport(mode=mode, issues=issues, applied_rules=applied_rules or [], outliers_detected=outlier_total)


def apply_rules(source: list[DataRow], rules: list[CleaningRule], mode: str = "applied", source_columns: list[ColumnInfo] | None = None) -> tuple[list[DataRow], list[ColumnInfo], CleaningReport]:
    rows = [row.model_copy(deep=True) for row in source]; removed = filled = converted = 0
    # Convert before filling so copied cells have the same storage unit.
    ordered_rules = sorted(rules, key=lambda rule: 0 if rule.action == "drop_rows" else 1 if rule.action in {"convert_number", "convert_percent"} else 2)
    for rule in ordered_rules:
        targets = set(rule.row_ids)
        if targets - {row.row_id for row in source} or (rule.column and source and rule.column not in source[0].values):
            raise AppException("REQUEST_INVALID", "清洗规则包含不存在的行或列", 422)
        if rule.action == "keep": continue
        if rule.action == "drop_rows": before = len(rows); rows = [row for row in rows if row.row_id not in targets]; removed += before - len(rows); continue
        assert rule.column
        selected_ids = targets or {row.row_id for row in rows}
        if rule.action == "median":
            numbers = pd.to_numeric(pd.Series([row.values.get(rule.column) for row in rows]), errors="coerce"); median = float(numbers.median()) if numbers.notna().any() else None
            if median is not None and not math.isfinite(median): median = None
            for row in rows:
                if row.row_id in selected_ids and _is_blank(row.values.get(rule.column)) and median is not None: row.values[rule.column] = median; filled += 1
        elif rule.action == "forward_fill":
            previous = None
            for row in rows:
                if not _is_blank(row.values.get(rule.column)): previous = row.values[rule.column]
                elif row.row_id in selected_ids and previous is not None: row.values[rule.column] = previous; filled += 1
        else:
            for row in rows:
                if row.row_id not in selected_ids: continue
                value = row.values.get(rule.column)
                if value is None or value == "": continue
                raw = str(value).strip().replace(",", ""); factor = 0.01 if rule.action == "convert_percent" else 1.0
                if rule.action == "convert_percent":
                    if not raw.endswith("%"): continue
                    raw = raw.removesuffix("%")
                try:
                    number = float(raw) * factor
                    if not math.isfinite(number): raise ValueError("non-finite number")
                    row.values[rule.column] = number; converted += 1
                except ValueError: continue
    columns, report = analyze(rows, mode=mode, applied_rules=ordered_rules); report.removed_rows = removed; report.filled_cells = filled; report.type_conversions = converted
    percent_columns = {rule.column for rule in rules if rule.action == "convert_percent"} | {column.name for column in source_columns or [] if column.display_format == "percent"}
    for column in columns:
        if column.name in percent_columns:
            column.inferred_type = "percent"
            column.display_format = "percent"
    return rows, columns, report
