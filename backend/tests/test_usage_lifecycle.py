from datetime import UTC, datetime, timedelta

from backend.app.repositories.database import transaction
from backend.app.services.usage import get_usage, reset_provider_overrun, sweep_stale_reservations


def test_sweep_releases_stale_reservations(client):
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with transaction(immediate=True) as db:
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", ("res_old", "req_old", "openai", "gpt-4o-mini", "0.10", "reserved", old))
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", ("res_new", "req_new", "openai", "gpt-4o-mini", "0.10", "reserved", datetime.now(UTC).isoformat()))
    released = sweep_stale_reservations()
    assert released == 1
    usage = get_usage()
    assert str(usage.reserved_usd) == "0.1"


def test_overrun_blocks_and_reset_unblocks(client):
    from backend.app.core.errors import AppException
    from backend.app.services.usage import reserve

    with transaction(immediate=True) as db:
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", ("res_ovr", "req_ovr", "openai", "gpt-4o-mini", "0.5", "provider_overrun", datetime.now(UTC).isoformat()))
    try:
        reserve("req_blocked", "openai", "gpt-4o-mini", "hello")
        raise AssertionError("expected BUDGET_EXCEEDED")
    except AppException as exc:
        assert exc.code == "BUDGET_EXCEEDED"
    assert reset_provider_overrun() == 1
    reservation = reserve("req_ok", "openai", "gpt-4o-mini", "hello")
    assert reservation


def test_embedding_cost_is_accounted(client):
    from backend.app.services.usage import price_for, reserve_embedding, settle_embedding

    reservation = reserve_embedding("rag_req", "openai", "text-embedding-3-small", ["一段需要向量化的文本" * 100])
    assert reservation
    before = get_usage().known_cost_usd
    settle_embedding(reservation, "rag_req", "openai", "text-embedding-3-small", estimated_tokens=1000)
    after = get_usage().known_cost_usd
    unit = max(price_for("openai", "text-embedding-3-small")["embedding_per_1m"], price_for("openai", "text-embedding-3-small")["input_per_1m"])
    assert after > before and after - before == __import__("decimal").Decimal(str(unit)) / 1000


def test_estimate_tokens_cjk_fallback_counts_full_chars(client, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "tiktoken": raise ImportError("blocked in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    from backend.app.services.usage import estimate_tokens
    tokens = estimate_tokens("设备故障率偏高需要分析" * 10, "unknown-model")
    assert tokens >= 100
