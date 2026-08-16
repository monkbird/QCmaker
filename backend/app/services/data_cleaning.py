from __future__ import annotations

import io
import math
import re
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
    if suffix == "csv":
        frame = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try: frame = pd.read_csv(io.BytesIO(content), encoding=encoding, dtype=object); break
            except UnicodeDecodeError: continue
        if frame is None: raise AppException("DATA_FORMAT_UNSUPPORTED", "CSV 编码无法识别", 400)
    elif suffix in {"xls", "xlsx"}: frame = pd.read_excel(io.BytesIO(content), dtype=object)
    else: raise AppException("DATA_FORMAT_UNSUPPORTED", "仅支持 csv、xls、xlsx 文件", 400)
    if len(frame) > 5000 or len(frame.columns) > 200: raise AppException("DATA_FORMAT_UNSUPPORTED", "数据最多 5000 行、200 列", 400)
    frame.columns = [str(column).strip() or f"未命名列_{index + 1}" for index, column in enumerate(frame.columns)]
    return frame


def rows_from_frame(frame: pd.DataFrame) -> list[DataRow]:
    return [DataRow(row_id=f"row_{position + 1}", values={str(k): normalize_scalar(v) for k, v in row.items()}) for position, (_, row) in enumerate(frame.iterrows())]


def analyze(rows: list[DataRow], mode: str = "detected", applied_rules: list[CleaningRule] | None = None) -> tuple[list[ColumnInfo], CleaningReport]:
    names = list(rows[0].values) if rows else []; issues: list[CleaningIssue] = []; columns: list[ColumnInfo] = []
    empty_rows = [row.row_id for row in rows if all(value is None or value == "" for value in row.values.values())]
    if empty_rows: issues.append(CleaningIssue(issue_type="empty_row", row_ids=empty_rows, suggested_actions=["drop_rows", "keep"]))
    total_rows = [row.row_id for row in rows if any(re.search(r"合计|总计|total", str(value), re.I) for value in row.values.values())]
    if total_rows: issues.append(CleaningIssue(issue_type="total_row", row_ids=total_rows, suggested_actions=["drop_rows", "keep"]))
    outlier_total = 0
    for name in names:
        values = [row.values.get(name) for row in rows]; missing = [row.row_id for row in rows if row.values.get(name) is None]
        if missing: issues.append(CleaningIssue(issue_type="missing", column=name, row_ids=missing, suggested_actions=["median", "forward_fill", "keep"]))
        nonempty = [value for value in values if value not in (None, "")]
        percent = bool(nonempty) and sum(isinstance(value, str) and value.strip().endswith("%") for value in nonempty) >= len(nonempty) / 2
        numeric = pd.to_numeric(pd.Series(nonempty), errors="coerce") if nonempty else pd.Series(dtype=float)
        inferred = "percent" if percent else "number" if len(nonempty) and numeric.notna().mean() >= 0.8 else "boolean" if nonempty and all(isinstance(x, bool) for x in nonempty) else "string"
        outliers: list[str] = []
        if inferred == "number" and numeric.notna().sum() >= 4:
            q1, q3 = numeric.quantile([0.25, 0.75]); iqr = q3 - q1; low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            for row in rows:
                number = pd.to_numeric(pd.Series([row.values.get(name)]), errors="coerce").iloc[0]
                if pd.notna(number) and (number < low or number > high): outliers.append(row.row_id)
        if outliers: outlier_total += len(outliers); issues.append(CleaningIssue(issue_type="outlier", column=name, row_ids=outliers, suggested_actions=["keep"]))
        columns.append(ColumnInfo(name=name, inferred_type=inferred, missing_count=len(missing), outlier_count=len(outliers), display_format="percent" if percent else "plain"))
    return columns, CleaningReport(mode=mode, issues=issues, applied_rules=applied_rules or [], outliers_detected=outlier_total)


def apply_rules(source: list[DataRow], rules: list[CleaningRule], mode: str = "applied") -> tuple[list[DataRow], list[ColumnInfo], CleaningReport]:
    rows = [row.model_copy(deep=True) for row in source]; removed = filled = converted = 0
    for rule in rules:
        targets = set(rule.row_ids)
        if rule.action == "keep": continue
        if rule.action == "drop_rows": before = len(rows); rows = [row for row in rows if row.row_id not in targets]; removed += before - len(rows); continue
        assert rule.column
        selected_ids = targets or {row.row_id for row in rows}
        if rule.action == "median":
            numbers = pd.to_numeric(pd.Series([row.values.get(rule.column) for row in rows]), errors="coerce"); median = float(numbers.median()) if numbers.notna().any() else None
            for row in rows:
                if row.row_id in selected_ids and row.values.get(rule.column) is None and median is not None: row.values[rule.column] = median; filled += 1
        elif rule.action == "forward_fill":
            previous = None
            for row in rows:
                if row.values.get(rule.column) is not None: previous = row.values[rule.column]
                elif row.row_id in selected_ids and previous is not None: row.values[rule.column] = previous; filled += 1
        else:
            for row in rows:
                if row.row_id not in selected_ids: continue
                value = row.values.get(rule.column)
                if value in (None, ""): continue
                raw = str(value).strip().replace(",", ""); factor = 0.01 if rule.action == "convert_percent" else 1.0
                if rule.action == "convert_percent": raw = raw.removesuffix("%")
                try: row.values[rule.column] = float(raw) * factor; converted += 1
                except ValueError: continue
    columns, report = analyze(rows, mode=mode, applied_rules=rules); report.removed_rows = removed; report.filled_cells = filled; report.type_conversions = converted
    return rows, columns, report
