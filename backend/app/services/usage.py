from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.core.errors import AppException
from backend.app.models.contracts import ModelUsage, UsageView
from backend.app.repositories.database import connect, transaction


def _prices() -> list[dict]:
    return json.loads((PROJECT_ROOT / "backend" / "data" / "model_prices.json").read_text(encoding="utf-8"))


def price_for(provider: str, model: str) -> dict:
    records = [item for item in _prices() if item["provider"] == provider and item["model"] == model]
    if not records:
        raise AppException("MODEL_PRICE_UNKNOWN", f"模型 {model} 尚未配置价格", 400)
    return sorted(records, key=lambda item: item["effective_from"])[-1]


def estimate_tokens(text: str, model: str) -> int:
    try:
        import tiktoken
        try: encoding = tiktoken.encoding_for_model(model)
        except KeyError: encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, math.ceil(len(text) / 2))


def reserve(request_id: str, provider: str, model: str, input_text: str) -> str | None:
    if provider == "local": return None
    settings = get_settings(); input_tokens = estimate_tokens(input_text, model)
    try: price = price_for(provider, model)
    except AppException as exc:
        if exc.code != "MODEL_PRICE_UNKNOWN": raise
        price = None
    amount = Decimal(str(getattr(settings, "UNKNOWN_MODEL_RESERVE_USD", 0.25))) if price is None else Decimal(input_tokens) * Decimal(price["input_per_1m"]) / Decimal(1_000_000) + Decimal(settings.LLM_MAX_OUTPUT_TOKENS) * Decimal(price["output_per_1m"]) / Decimal(1_000_000) + Decimal(price["safety_margin_usd"])
    reservation_id = f"res_{uuid4().hex}"
    with transaction(immediate=True) as db:
        used = Decimal(str(db.execute("SELECT COALESCE(SUM(CAST(cost_usd AS REAL)),0) FROM usage_events").fetchone()[0])); held = Decimal(str(db.execute("SELECT COALESCE(SUM(CAST(reserved_usd AS REAL)),0) FROM reservations WHERE status IN ('reserved','usage_unknown')").fetchone()[0]))
        if db.execute("SELECT 1 FROM reservations WHERE status='provider_overrun' LIMIT 1").fetchone(): raise AppException("BUDGET_EXCEEDED", "账目存在供应商超额，外部调用已暂停", 429)
        if used + held + amount > Decimal(str(settings.MAX_BUDGET_USD)): raise AppException("BUDGET_EXCEEDED", "模型预算不足", 429, {"required_usd": str(amount)})
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", (reservation_id, request_id, provider, model, str(amount), "reserved", datetime.now(UTC).isoformat()))
    return reservation_id


def settle(reservation_id: str | None, request_id: str, provider: str, model: str, input_tokens: int, output_tokens: int, embedding_tokens: int = 0, usage_known: bool = True) -> None:
    if provider == "local": return
    if not reservation_id: return
    if not usage_known:
        with transaction(immediate=True) as db: db.execute("UPDATE reservations SET status='usage_unknown' WHERE id=?", (reservation_id,))
        return
    try: price = price_for(provider, model)
    except AppException as exc:
        if exc.code != "MODEL_PRICE_UNKNOWN": raise
        with transaction(immediate=True) as db: db.execute("UPDATE reservations SET status='usage_unknown' WHERE id=?", (reservation_id,))
        return
    cost = (Decimal(input_tokens) * Decimal(price["input_per_1m"]) + Decimal(output_tokens) * Decimal(price["output_per_1m"]) + Decimal(embedding_tokens) * Decimal(price["embedding_per_1m"])) / Decimal(1_000_000)
    with transaction(immediate=True) as db:
        row = db.execute("SELECT reserved_usd FROM reservations WHERE id=?", (reservation_id,)).fetchone(); status = "provider_overrun" if row and cost > Decimal(row[0]) else "settled"
        db.execute("UPDATE reservations SET status=? WHERE id=?", (status, reservation_id)); db.execute("INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?)", (f"use_{uuid4().hex}", request_id, provider, model, input_tokens, output_tokens, embedding_tokens, str(cost), price["effective_from"], datetime.now(UTC).isoformat()))


def release(reservation_id: str | None) -> None:
    if reservation_id:
        with transaction(immediate=True) as db: db.execute("UPDATE reservations SET status='released' WHERE id=? AND status='reserved'", (reservation_id,))


def get_usage() -> UsageView:
    db = connect()
    try:
        reserved = Decimal(str(db.execute("SELECT COALESCE(SUM(CAST(reserved_usd AS REAL)),0) FROM reservations WHERE status IN ('reserved','usage_unknown')").fetchone()[0]))
        known = Decimal(str(db.execute("SELECT COALESCE(SUM(CAST(cost_usd AS REAL)),0) FROM usage_events").fetchone()[0]))
        unknown = bool(db.execute("SELECT 1 FROM reservations WHERE status IN ('usage_unknown','provider_overrun') LIMIT 1").fetchone())
        rows = db.execute("SELECT provider,model,SUM(input_tokens),SUM(output_tokens),SUM(embedding_tokens),SUM(CAST(cost_usd AS REAL)) FROM usage_events GROUP BY provider,model").fetchall()
    finally: db.close()
    budget = Decimal(str(get_settings().MAX_BUDGET_USD)); remaining = max(Decimal("0"), budget - known - reserved)
    return UsageView(budget_usd=budget, reserved_usd=reserved, known_cost_usd=known, remaining_usd=remaining, unknown_cost=unknown, usage_by_model=[ModelUsage(provider=r[0], model=r[1], input_tokens=r[2], output_tokens=r[3], embedding_tokens=r[4], known_cost_usd=Decimal(str(r[5]))) for r in rows])
