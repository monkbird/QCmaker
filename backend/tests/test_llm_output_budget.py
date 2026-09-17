import asyncio
import socket
from types import SimpleNamespace

import pytest

from backend.app.core import clients
from backend.app.core import llm_gateway
from backend.app.core.errors import AppException
from backend.app.services import usage

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_ORIGINAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def allow_asyncio_socketpair(monkeypatch):
    # pytest-conftest's offline guard predates asyncio's Windows socketpair fallback.
    monkeypatch.setattr(socket.socket, "connect", _ORIGINAL_CONNECT)


@pytest.mark.asyncio
async def test_invoke_target_default_preserves_configured_limit(monkeypatch):
    calls = {}

    class Result:
        content = "ok"
        usage_metadata = {"input_tokens": 1, "output_tokens": 1}

    class FakeClient:
        async def ainvoke(self, messages):
            calls["messages"] = messages
            return Result()

    monkeypatch.setattr(llm_gateway, "reserve", lambda *args: calls.setdefault("reserve", args) or "r")
    monkeypatch.setattr(llm_gateway, "mark_dispatched", lambda reservation: None)
    monkeypatch.setattr(llm_gateway, "settle", lambda *args, **kwargs: None)
    def get_client(*args, **kwargs):
        calls["client"] = (args, kwargs)
        return FakeClient()
    monkeypatch.setattr(llm_gateway, "get_chat_client_for", get_client)
    target = SimpleNamespace(api_style="openai", provider="openai", model="m", api_key="k", base_url="https://example.com/v1")

    assert await llm_gateway.invoke_target([{"role": "user", "content": "hi"}], target) == "ok"
    assert calls["client"][1] == {"allow_private": False}
    assert calls["reserve"][3] == "hi"


@pytest.mark.asyncio
async def test_invoke_target_explicit_limit_reaches_client_and_reservation(monkeypatch):
    calls = {}

    class Result:
        content = "ok"
        usage_metadata = {"input_tokens": 1, "output_tokens": 3}

    class FakeClient:
        async def ainvoke(self, messages):
            return Result()

    monkeypatch.setattr(llm_gateway, "reserve", lambda *args: calls.setdefault("reserve", args) or "r")
    monkeypatch.setattr(llm_gateway, "mark_dispatched", lambda reservation: None)
    monkeypatch.setattr(llm_gateway, "settle", lambda *args, **kwargs: None)
    def get_client(*args, **kwargs):
        calls["client"] = (args, kwargs)
        return FakeClient()
    monkeypatch.setattr(llm_gateway, "get_chat_client_for", get_client)
    target = SimpleNamespace(api_style="openai", provider="openai", model="m", api_key="k", base_url="https://example.com/v1")

    assert await llm_gateway.invoke_target([{"role": "user", "content": "hi"}], target, max_output_tokens=8192) == "ok"
    assert calls["client"][1]["max_output_tokens"] == 8192
    assert calls["reserve"][4] == 8192


def test_reserve_explicit_limit_changes_known_model_hold(isolated_settings, isolated_storage):
    from backend.app.repositories.database import init_database
    init_database()
    default = usage.reserve("r-default", "openai", "gpt-4o-mini", "hello")
    explicit = usage.reserve("r-explicit", "openai", "gpt-4o-mini", "hello", max_output_tokens=8192)
    from backend.app.repositories.database import connect
    db = connect()
    try:
        amounts = [float(row[0]) for row in db.execute("SELECT reserved_usd FROM reservations ORDER BY request_id").fetchall()]
    finally:
        db.close()
    assert explicit and amounts[1] > amounts[0]


@pytest.mark.asyncio
async def test_output_limit_validation_rejects_non_positive_and_excessive(monkeypatch):
    target = SimpleNamespace(api_style="openai", provider="local", model="m", api_key=None, base_url="http://localhost:11434/v1")
    for value in (0, -1, 1_000_001):
        with pytest.raises(AppException) as exc:
            await llm_gateway.invoke_target([], target, max_output_tokens=value)
        assert exc.value.code == "INVALID_MAX_OUTPUT_TOKENS"


def test_client_cache_key_includes_effective_output_limit(monkeypatch):
    created = []
    monkeypatch.setattr(clients, "get_settings", lambda: SimpleNamespace(CONFIG_REVISION=0, LLM_MAX_OUTPUT_TOKENS=2048))
    monkeypatch.setattr(clients, "_cache_get_or_create", lambda key, factory: created.append((key, factory)) or key)
    first = clients.get_chat_client_for("k", "https://example.com/v1", "m", max_output_tokens=2048)
    second = clients.get_chat_client_for("k", "https://example.com/v1", "m", max_output_tokens=8192)
    assert first != second
    assert first[-1] == 2048
    assert second[-1] == 8192
