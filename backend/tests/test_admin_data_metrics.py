import json
from datetime import UTC, datetime, timedelta


def _seed_usage(now: datetime):
    from backend.app.repositories.database import init_database, transaction

    init_database()

    with transaction(immediate=True) as db:
        db.executemany(
            "INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                ("u1", "req1", "openai", "gpt-a", 10, 20, 0, "0.125", None, (now - timedelta(hours=1)).isoformat()),
                ("u2", "req2", "openai", "gpt-a", 5, 0, 3, "0.075", None, (now - timedelta(days=2)).isoformat()),
                ("u3", "req3", "local", "llama", 1, 2, 0, "1.0", None, (now + timedelta(hours=1)).isoformat()),
            ],
        )
        db.executemany(
            "INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
            [
                ("r1", "req4", "openai", "gpt-a", "0.40", "usage_unknown", (now - timedelta(hours=1)).isoformat()),
                ("r2", "req5", "openai", "gpt-a", "0.50", "provider_overrun", (now - timedelta(hours=1)).isoformat()),
                ("r3", "req6", "openai", "gpt-b", "0.10", "overrun_cleared", (now - timedelta(hours=1)).isoformat()),
            ],
        )


def test_usage_summary_uses_utc_half_open_range_and_keeps_unknown_holds(isolated_storage):
    from backend.app.services.admin_metrics import usage_summary

    now = datetime.now(UTC).replace(microsecond=0)
    _seed_usage(now)
    summary = usage_summary(from_=now - timedelta(hours=2), to=now)

    assert summary["input_tokens"] == 10
    assert summary["output_tokens"] == 20
    assert summary["embedding_tokens"] == 0
    assert summary["requests"] == 1
    assert summary["cost_usd"] == "0.125"
    assert summary["usage_unknown_usd"] == "0.40"
    assert summary["provider_overrun_usd"] == "0.50"
    assert summary["overrun_cleared_usd"] == "0.10"


def test_usage_trends_fill_empty_buckets(isolated_storage):
    from backend.app.services.admin_metrics import usage_trends

    now = datetime.now(UTC).replace(minute=15, second=0, microsecond=0)
    _seed_usage(now)
    points = usage_trends("24h", "cost", now=now)

    assert len(points) == 24
    assert all(set(point) == {"bucket", "cost_usd", "tokens", "requests"} for point in points)
    assert any(point["requests"] == 1 for point in points)
    assert any(point["requests"] == 0 and point["cost_usd"] == "0.00" for point in points)


def test_dataset_detail_is_metadata_only(isolated_storage):
    from backend.app.repositories.database import init_database
    from backend.app.services.admin_metrics import dataset_detail

    now = datetime.now(UTC)
    init_database()
    columns = [{"name": "手机号", "inferred_type": "string", "missing_count": 1, "outlier_count": 0, "display_format": "plain"}]
    report = {"mode": "detected", "issues": [{"issue_type": "missing", "column": "手机号", "row_ids": ["row_1"], "suggested_actions": ["keep"]}], "applied_rules": [], "removed_rows": 0, "filled_cells": 0, "outliers_detected": 0, "type_conversions": 0}
    with __import__("backend.app.repositories.database", fromlist=["transaction"]).transaction(immediate=True) as db:
        db.execute(
            "INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("ds_safe", "secret.csv", 2, 2, json.dumps([{"row_id": "row_1", "values": {"手机号": "13812345678"}}]), json.dumps([{"row_id": "row_1", "values": {"手机号": "13812345678"}}]), json.dumps(columns), json.dumps(report), now.isoformat(), (now + timedelta(hours=1)).isoformat()),
        )
    detail = dataset_detail("ds_safe")

    assert detail["filename"] == "secret.csv"
    assert detail["row_count"] == 1
    assert detail["quality"]["missing_cells"] == 1
    serialized = json.dumps(detail, ensure_ascii=False)
    assert "13812345678" not in serialized
    assert "raw_rows_json" not in serialized and "current_rows_json" not in serialized


def test_log_reader_is_fixed_path_and_redacts_credentials(isolated_storage, tmp_path, monkeypatch):
    from backend.app.services import admin_metrics

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "app.log").write_text(
        "2026-09-13 10:00:00 INFO api Authorization: Bearer sk-secret path?token=abc\n"
        "2026-09-13 10:00:01 ERROR api Cookie: sid=secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(admin_metrics, "LOG_DIR", log_dir)
    result = admin_metrics.read_logs(tail=10, max_bytes=1024)

    assert len(result["lines"]) == 2
    text = " ".join(line["message"] for line in result["lines"])
    assert "sk-secret" not in text and "token=abc" not in text and "sid=secret" not in text
    assert result["cursor"]
