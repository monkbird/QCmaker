from types import SimpleNamespace

import pytest

from backend.app.core.errors import AppException
from backend.app.services import usage


def test_reservation_enforces_budget(client, monkeypatch):
    monkeypatch.setattr(usage, "get_settings", lambda: SimpleNamespace(MAX_BUDGET_USD=0.0, LLM_MAX_OUTPUT_TOKENS=2048))
    with pytest.raises(AppException) as exc: usage.reserve("r1", "openai", "gpt-4o-mini", "hello")
    assert exc.value.code == "BUDGET_EXCEEDED"


def test_unknown_model_uses_auditable_reservation(client):
    reservation = usage.reserve("r2", "openai", "unknown-model", "hello")
    assert reservation
    usage.settle(reservation, "r2", "openai", "unknown-model", 10, 10)
    current = usage.get_usage()
    assert current.unknown_cost is True
    assert current.reserved_usd == 0.25


def test_failed_call_releases_reservation(client, monkeypatch):
    monkeypatch.setattr(usage, "get_settings", lambda: SimpleNamespace(MAX_BUDGET_USD=5.0, LLM_MAX_OUTPUT_TOKENS=10))
    reservation = usage.reserve("r3", "openai", "gpt-4o-mini", "hello")
    usage.release(reservation)
    assert usage.get_usage().reserved_usd == 0
