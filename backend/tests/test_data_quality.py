from io import BytesIO


def _upload(client, csv_text: str):
    response = client.post("/api/data/upload", files={"file": ("sample.csv", BytesIO(csv_text.encode("utf-8")), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def test_convert_number_never_produces_nan(client):
    # cells edited in the UI arrive as JSON strings; "nan"/"inf" must stay untouched, not become floats
    from backend.app.models.contracts import CleaningRule, DataRow
    from backend.app.services.data_cleaning import apply_rules
    rows = [DataRow(row_id="row_1", values={"数值": "nan"}), DataRow(row_id="row_2", values={"数值": "inf"}), DataRow(row_id="row_3", values={"数值": 3}), DataRow(row_id="row_4", values={"数值": "2,500"})]
    out_rows, _, report = apply_rules(rows, [CleaningRule(action="convert_number", column="数值", row_ids=[])])
    values = {row.values["数值"] for row in out_rows}
    assert values == {"nan", "inf", 2500.0, 3}
    assert report.type_conversions == 2


def test_chart_rejects_non_finite_and_hides_none_labels(client):
    dataset = _upload(client, "类别,数值\n甲,1\n乙,nan\n")
    confirmed = client.post("/api/data/confirm", json={"dataset_id": dataset["dataset_id"], "revision": 0})
    assert confirmed.status_code == 200
    chart = client.post("/api/visualization/generate", json={"chart_type": "bar", "dataset_id": dataset["dataset_id"], "revision": 0, "x_axis": "类别", "y_axis": "数值"})
    assert chart.status_code == 422 and chart.json()["code"] == "DATA_Y_NOT_NUMERIC"

    dataset2 = _upload(client, "类别,数值\n,5\n乙,7\n")
    assert client.post("/api/data/confirm", json={"dataset_id": dataset2["dataset_id"], "revision": 0}).status_code == 200
    chart2 = client.post("/api/visualization/generate", json={"chart_type": "bar", "dataset_id": dataset2["dataset_id"], "revision": 0, "x_axis": "类别", "y_axis": "数值", "aggregation": "sum"})
    assert chart2.status_code == 200
    assert "None" not in chart2.json()["option"]["xAxis"]["data"]


def test_empty_string_cells_count_as_missing_and_fill(client):
    dataset = _upload(client, "月份,产量\n1月,\n2月,8\n")
    missing = next(issue for issue in dataset["report"]["issues"] if issue["issue_type"] == "missing")
    assert "row_1" in missing["row_ids"]
    applied = client.post("/api/data/apply", json={"dataset_id": dataset["dataset_id"], "base_revision": 0, "rules": [{"action": "median", "column": "产量", "row_ids": []}]})
    assert applied.status_code == 200
    rows = {row["row_id"]: row["values"]["产量"] for row in applied.json()["rows"]}
    assert rows["row_1"] == 8.0


def test_expired_dataset_is_read_only_everywhere(client):
    from datetime import UTC, datetime, timedelta

    from backend.app.repositories.database import transaction

    dataset = _upload(client, "a\n1\n")
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with transaction(immediate=True) as db:
        db.execute("UPDATE datasets SET expires_at=? WHERE dataset_id=?", (past, dataset["dataset_id"]))
    assert client.get(f"/api/data/{dataset['dataset_id']}").status_code == 404
    undo = client.post("/api/data/undo", json={"dataset_id": dataset["dataset_id"], "base_revision": 0})
    assert undo.status_code == 404 and undo.json()["code"] == "SESSION_NOT_FOUND"


def test_recommend_avoids_numeric_category_column(client):
    payload = {"columns": [{"name": "成本", "inferred_type": "number", "missing_count": 0, "outlier_count": 0}, {"name": "工序", "inferred_type": "string", "missing_count": 0, "outlier_count": 0}, {"name": "工时", "inferred_type": "number", "missing_count": 0, "outlier_count": 0}]}
    result = client.post("/api/visualization/recommend", json=payload).json()
    assert result["y_axis"] == "成本"
    assert result["x_axis"] == "工序"
