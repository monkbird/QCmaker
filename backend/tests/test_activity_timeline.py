from backend.app.services.timeline_checks import check_timeline

def test_unknown_activity_date_is_pending_without_fabrication():
    x=check_timeline([{'event_type':'implementation','uploaded_at':'2026-01-01T00:00:00Z'}])
    assert 'activity_start' in x.missing_fields and 'uploaded_at_cannot_replace_activity_time' in x.warnings

def test_effect_before_implementation_and_bad_date_are_flagged():
    x=check_timeline([{'event_type':'implementation','activity_start':'2026-06-02'},{'event_type':'effect','activity_start':'2026-06-01'},{'activity_start':'bad'}])
    assert 'effect_before_implementation' in x.flags and 'invalid_activity_date' in x.flags

def test_sample_change_calculation_is_explicit():
    x=check_timeline([{'event_type':'effect','activity_start':'2026-06-03','measures':[{'metric_id':'m','before':337.04,'after':374.29,'unit':'x','subject':'same','comparison':'before_after','nature':'measured'}]}])
    assert x.calculations[0]['change_percent']==11.05
