from __future__ import annotations

import hashlib
import threading
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException

_lock = threading.RLock()
_cache: dict[tuple[Any, ...], Any] = {}
_MAX_CACHE_ENTRIES = 16


def _fingerprint(secret: str | None) -> str:
    return hashlib.sha256((secret or "").encode()).hexdigest()[:12]


def clear_client_cache() -> None:
    with _lock: _cache.clear()


def _cache_get_or_create(key: tuple[Any, ...], factory):
    with _lock:
        if key not in _cache:
            if len(_cache) >= _MAX_CACHE_ENTRIES:
                _cache.pop(next(iter(_cache)), None)
            try:
                _cache[key] = factory()
            except ImportError as exc: raise AppException("LLM_NOT_CONFIGURED", "未安装 langchain-openai", 500) from exc
        return _cache[key]


def get_chat_client_for(api_key: str | None, base_url: str, model: str, *, allow_private: bool = False):
    settings = get_settings()
    key = (settings.CONFIG_REVISION, "chat", base_url, model, _fingerprint(api_key), allow_private, settings.LLM_MAX_OUTPUT_TOKENS)

    def factory():
        from langchain_openai import ChatOpenAI

        from backend.app.core.security import outbound_http_clients, validate_outbound_base_url
        validate_outbound_base_url(base_url, allow_private=allow_private)
        sync_client, async_client = outbound_http_clients(allow_private)
        return ChatOpenAI(api_key=api_key or "ollama", base_url=base_url, model=model,
                          max_tokens=settings.LLM_MAX_OUTPUT_TOKENS, max_retries=0,
                          http_client=sync_client, http_async_client=async_client)
    return _cache_get_or_create(key, factory)


def get_chat_client():
    from backend.app.services.model_roles import resolve_role_target
    target = resolve_role_target(None)
    return get_chat_client_for(target.api_key, target.base_url, target.model, allow_private=target.provider == "local")


def get_embeddings_client():
    """Embeddings client; works against the local LLM endpoint when USE_LOCAL_LLM is on."""
    settings = get_settings()
    if settings.USE_LOCAL_LLM:
        api_key, base_url, model = "ollama", settings.LOCAL_LLM_URL, (settings.EMBEDDING_MODEL or settings.LOCAL_LLM_MODEL)
        key = (settings.CONFIG_REVISION, "local-embeddings", base_url, model)
    else:
        if not settings.OPENAI_API_KEY: raise AppException("LLM_NOT_CONFIGURED", "请先配置 OpenAI API Key", 400)
        api_key = settings.OPENAI_API_KEY
        base_url, model = settings.OPENAI_BASE_URL, settings.EMBEDDING_MODEL
        key = (settings.CONFIG_REVISION, "embeddings", base_url, model, _fingerprint(api_key))

    def factory():
        from langchain_openai import OpenAIEmbeddings

        from backend.app.core.security import outbound_http_clients, validate_outbound_base_url
        validate_outbound_base_url(base_url, allow_private=settings.USE_LOCAL_LLM)
        sync_client, async_client = outbound_http_clients(settings.USE_LOCAL_LLM)
        raw = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model,
                               max_retries=0, http_client=sync_client, http_async_client=async_client)
        return AccountedEmbeddings(raw, "local" if settings.USE_LOCAL_LLM else settings.LLM_PROVIDER, model)
    return _cache_get_or_create(key, factory)


class AccountedEmbeddings:
    """All vectorization, including search queries, shares the privacy/budget boundary."""
    def __init__(self, client, provider: str, model: str):
        self.client, self.provider, self.model = client, provider, model

    def _invoke(self, texts: list[str], query: bool):
        from uuid import uuid4

        from backend.app.middleware.pii import pii_redactor
        from backend.app.services.usage import estimate_tokens, mark_dispatched, reserve_embedding, settle, settle_embedding
        safe = [pii_redactor.redact(text) for text in texts]
        request_id = f"emb_{uuid4().hex}"
        reservation = reserve_embedding(request_id, self.provider, self.model, safe)
        mark_dispatched(reservation)
        try:
            result = self.client.embed_query(safe[0]) if query else self.client.embed_documents(safe)
        except Exception:
            # A timeout may occur after the supplier performed work. Keep the hold.
            settle(reservation, request_id, self.provider, self.model, 0, 0, usage_known=False)
            raise
        settle_embedding(reservation, request_id, self.provider, self.model,
                         sum(estimate_tokens(text, self.model) for text in safe))
        return result

    def embed_query(self, text: str):
        return self._invoke([text], True)

    def embed_documents(self, texts: list[str]):
        return self._invoke(texts, False) if texts else []
