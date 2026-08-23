import pytest
from starlette.websockets import WebSocketDisconnect


def test_security_headers_on_every_response(client):
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_rate_limit_blocks_flood(client, isolated_settings):
    from backend.app.core import security

    isolated_settings.RATE_LIMIT_PER_MINUTE = 3
    security.rebuild_rate_limiter()
    statuses = [client.post("/api/topic/chat", json={"message": "x", "history": []}).status_code for _ in range(5)]
    assert 429 in statuses and statuses.count(429) == 2


def test_api_token_required_when_configured(client, isolated_settings):
    isolated_settings.API_ACCESS_TOKEN = "secret-token"
    denied = client.get("/api/config/")
    assert denied.status_code == 401 and denied.json()["code"] == "UNAUTHORIZED"
    allowed_query = client.get("/api/config/?token=secret-token")
    assert allowed_query.status_code == 200
    allowed_header = client.get("/api/config/", headers={"x-api-token": "secret-token"})
    assert allowed_header.status_code == 200


def test_ws_rejects_bad_token(client, isolated_settings):
    isolated_settings.API_ACCESS_TOKEN = "secret-token"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/discussion/ws") as ws:
            ws.receive_json()


def test_ssrf_guard_blocks_private_and_invalid_base_urls(client):
    for bad in ("http://169.254.169.254/v1", "http://192.168.1.10/v1", "ftp://example.com/v1", "https://user:pass@example.com/v1"):
        response = client.post("/api/config/update", json={"openai_base_url": bad})
        assert response.status_code == 400 and response.json()["code"] == "MODEL_BASE_URL_INVALID", bad


def test_custom_provider_requires_base_url(client):
    response = client.post("/api/config/update", json={"llm_provider": "custom", "openai_api_key": "sk-x"})
    assert response.status_code == 400 and response.json()["code"] == "MODEL_BASE_URL_REQUIRED"


def test_update_settings_rejects_unknown_keys(client):
    from backend.app.core.config import update_settings
    with pytest.raises(ValueError):
        update_settings({"NOT_A_REAL_FIELD": "1"})


def test_overrun_reset_endpoint(client):
    from datetime import UTC, datetime

    from backend.app.core.errors import AppException
    from backend.app.repositories.database import transaction
    from backend.app.services.usage import reserve

    with transaction(immediate=True) as db:
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", ("res_x", "req_x", "openai", "gpt-4o-mini", "0.5", "provider_overrun", datetime.now(UTC).isoformat()))
    with pytest.raises(AppException) as exc:
        reserve("req_blocked", "openai", "gpt-4o-mini", "hello")
    assert exc.value.code == "BUDGET_EXCEEDED"
    cleared = client.post("/api/config/budget/reset-overrun")
    assert cleared.status_code == 200 and cleared.json()["cleared_reservations"] == 1
    assert reserve("req_ok", "openai", "gpt-4o-mini", "hello")
