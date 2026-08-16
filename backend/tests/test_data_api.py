from io import BytesIO


def upload(client):
    content = "类别,数量,比例\nA,10,15%\nA,20,20%\nB,,30%\n合计,30,65%\n".encode("utf-8")
    response = client.post("/api/data/upload", files={"file": ("sample.csv", BytesIO(content), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def test_dataset_clean_confirm_and_chart(client):
    dataset = upload(client)
    assert dataset["revision"] == 0 and dataset["confirmed_revision"] is None
    assert all("key" not in row["values"] for row in dataset["rows"])
    total = next(issue for issue in dataset["report"]["issues"] if issue["issue_type"] == "total_row")
    rules = [{"action": "drop_rows", "row_ids": total["row_ids"]}, {"action": "median", "column": "数量", "row_ids": ["row_3"]}]
    preview = client.post("/api/data/preview", json={"dataset_id": dataset["dataset_id"], "base_revision": 0, "rules": rules})
    assert preview.status_code == 200
    assert client.get(f"/api/data/{dataset['dataset_id']}").json()["revision"] == 0
    applied = client.post("/api/data/apply", json={"dataset_id": dataset["dataset_id"], "base_revision": 0, "rules": rules})
    assert applied.status_code == 200 and applied.json()["revision"] == 1
    conflict = client.post("/api/data/apply", json={"dataset_id": dataset["dataset_id"], "base_revision": 0, "rules": []})
    assert conflict.status_code == 409 and conflict.json()["code"] == "DATA_REVISION_CONFLICT"
    assert client.post("/api/data/confirm", json={"dataset_id": dataset["dataset_id"], "revision": 1}).status_code == 200
    chart = client.post("/api/visualization/generate", json={"chart_type": "bar", "dataset_id": dataset["dataset_id"], "revision": 1, "x_axis": "类别", "y_axis": "数量"})
    assert chart.status_code == 200, chart.text
    assert chart.json()["processing"]["aggregation"] == "sum"
    assert chart.json()["option"]["series"][0]["data"] == [30.0, 15.0]


def test_undo_revision_is_monotonic(client):
    dataset = upload(client)
    applied = client.post("/api/data/apply", json={"dataset_id": dataset["dataset_id"], "base_revision": 0, "rules": []}).json()
    undone = client.post("/api/data/undo", json={"dataset_id": dataset["dataset_id"], "base_revision": applied["revision"]})
    assert undone.status_code == 200
    assert undone.json()["revision"] == 2
    assert undone.json()["restored_from_revision"] == 0
