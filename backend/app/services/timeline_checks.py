from __future__ import annotations

import math
from datetime import date, datetime

from pydantic import BaseModel, Field


class TimelineCheck(BaseModel):
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    calculations: list[dict] = Field(default_factory=list)
    valid: bool = True


def _date(value):
    if not value: return None
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    return date.fromisoformat(str(value)[:10])


def check_timeline(records: list[dict]) -> TimelineCheck:
    missing, warnings, flags, calculations = [], [], [], []
    implementations = {}
    # Compare actual activity dates independently from entry/upload order.
    for record in records:
        if record.get('event_type') == 'implementation':
            try:
                end = _date(record.get('activity_end') or record.get('activity_start'))
                if end: implementations.setdefault(record.get('object', ''), []).append(end)
            except (TypeError, ValueError): pass
    definitions = {}
    for record in records:
        try: start, end = _date(record.get('activity_start')), _date(record.get('activity_end'))
        except (TypeError, ValueError): flags.append('invalid_activity_date'); continue
        if not start: missing.append('activity_start')
        if start and end and end < start: flags.append('activity_end_before_start')
        if record.get('uploaded_at') and not start: warnings.append('uploaded_at_cannot_replace_activity_time')
        if record.get('event_type') == 'effect' and start:
            corresponding = implementations.get(record.get('object', ''), [])
            if corresponding and start < max(corresponding): flags.append('effect_before_implementation')
            if not corresponding: warnings.append('implementation_record_missing')
        if record.get('contribution_note') and not record.get('mechanism'): warnings.append('contribution_requires_support')
        for metric in record.get('measures', []):
            if not all(metric.get(k) for k in ['unit', 'comparison', 'subject', 'nature']):
                if metric: flags.append('measure_definition_incomplete')
                continue
            definition = tuple(metric[k] for k in ['unit', 'comparison', 'subject', 'nature'])
            key = metric.get('metric_id')
            if key in definitions and definition != definitions[key]: flags.append('measure_scope_conflict')
            definitions[key] = definition
            if metric.get('before') is not None and metric.get('after') is not None:
                try:
                    before, after = float(metric['before']), float(metric['after'])
                    if not math.isfinite(before) or not math.isfinite(after): raise ValueError('nonfinite')
                    if before == 0: flags.append('zero_baseline'); continue
                    calculations.append({'metric_id': key, 'change_percent': round((after-before)/before*100, 2),
                                         'comparison': metric['comparison'], 'nature': metric['nature'], 'basis': 'declared_comparison_not_authenticity_verification'})
                except (TypeError, ValueError): flags.append('invalid_measure')
    return TimelineCheck(missing_fields=sorted(set(missing)), warnings=list(dict.fromkeys(warnings)), flags=list(dict.fromkeys(flags)), calculations=calculations, valid=not missing and not flags and not warnings)
