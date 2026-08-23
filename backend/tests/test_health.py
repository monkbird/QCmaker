def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert payload["version"] == "1.3.0"
    assert payload["llm"] in {"ready", "missing"}
    assert payload["disk_writable"] is True
    assert response.headers["x-request-id"].startswith("req_")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_config_never_returns_keys(client):
    payload = client.get("/api/config/").json()
    assert "openai_api_key" not in payload
    assert "tavily_api_key" not in payload
    assert payload["status"] in {"ready", "missing", "degraded"}
