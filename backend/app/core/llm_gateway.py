from __future__ import annotations

import logging
import time
from uuid import uuid4

from backend.app.core.clients import get_chat_client_for
from backend.app.middleware.pii import pii_redactor
from backend.app.services.model_roles import resolve_role_target
from backend.app.services.usage import mark_dispatched, reserve, settle, validate_max_output_tokens

logger = logging.getLogger(__name__)


async def chat(messages: list[dict[str, str]], role: str | None = None, *, max_output_tokens: int | None = None) -> str:
    from backend.app.repositories.config_profile_repository import active_snapshot
    target = resolve_role_target(role, snapshot=active_snapshot())
    return await invoke_target(messages, target, max_output_tokens=max_output_tokens)


async def invoke_target(messages: list[dict[str, str]], target, *, probe: bool = False, max_output_tokens: int | None = None) -> str:
    if getattr(target, "api_style", "openai") == "anthropic":
        from backend.app.core.errors import AppException
        raise AppException("MODEL_PROTOCOL_UNSUPPORTED", "该服务商暂不支持当前消息协议适配", 400)
    output_limit = validate_max_output_tokens(max_output_tokens)
    safe_messages = [{**message, "content": pii_redactor.redact(message["content"])} for message in messages]
    request_id = f"llm_{uuid4().hex}"
    input_text = "\n".join(m["content"] for m in safe_messages)
    reservation = (reserve(request_id, target.provider, target.model, input_text)
                   if output_limit is None else
                   reserve(request_id, target.provider, target.model, input_text, output_limit))
    mark_dispatched(reservation)
    try:
        client = (get_chat_client_for(target.api_key, target.base_url, target.model,
                                      allow_private=target.provider == "local" or target.api_style == "ollama")
                  if output_limit is None else
                  get_chat_client_for(target.api_key, target.base_url, target.model,
                                      allow_private=target.provider == "local" or target.api_style == "ollama",
                                      max_output_tokens=output_limit))
        result = await client.ainvoke(safe_messages)
    except Exception:
        settle(reservation, request_id, target.provider, target.model, 0, 0, usage_known=False)
        raise
    usage = getattr(result, "usage_metadata", None) or {}
    settle(reservation, request_id, target.provider, target.model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), usage_known=bool(usage))
    return pii_redactor.redact(str(result.content))


async def probe_target(target) -> dict[str, object]:
    started = time.perf_counter()
    from backend.app.core.errors import AppException
    try:
        message = await invoke_target([{"role": "user", "content": "Reply OK"}], target, probe=True)
    except AppException:
        raise
    except Exception as exc:
        raise AppException("LLM_PROBE_FAILED", "模型生成验证失败", 400, {"reason": type(exc).__name__}) from exc
    return {"latency_ms": round((time.perf_counter() - started) * 1000), "message": message}
