from backend.app.services.timeline_checks import check_timeline


def test_timeline_does_not_use_upload_time_as_activity_time():
    result = check_timeline([{"activity_start": None, "uploaded_at": "2026-01-01T00:00:00+00:00"}])
    assert "activity_start" in result.missing_fields
    assert result.warnings
