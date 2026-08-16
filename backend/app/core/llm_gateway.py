from __future__ import annotations

from uuid import uuid4

from backend.app.core.clients import get_chat_client
from backend.app.core.config import get_settings
from backend.app.middleware.pii import pii_redactor
from backend.app.services.usage import release, reserve, settle


async def chat(messages: list[dict[str, str]]) -> str:
    safe_messages = [{**message, "content": pii_redactor.redact(message["content"])} for message in messages]
    settings = get_settings(); provider = "local" if settings.USE_LOCAL_LLM else settings.LLM_PROVIDER; model = settings.LOCAL_LLM_MODEL if settings.USE_LOCAL_LLM else settings.OPENAI_MODEL; request_id = f"llm_{uuid4().hex}"
    reservation_id = reserve(request_id, provider, model, "\n".join(message["content"] for message in safe_messages))
    try:
        result = await get_chat_client().ainvoke(safe_messages)
    except Exception:
        release(reservation_id); raise
    usage = getattr(result, "usage_metadata", None) or {}; known = bool(usage)
    settle(reservation_id, request_id, provider, model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), usage_known=known)
    return str(result.content)
