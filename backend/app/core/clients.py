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


def get_chat_client_for(api_key: str | None, base_url: str, model: str):
    settings = get_settings()
    key = (settings.CONFIG_REVISION, "chat", base_url, model, _fingerprint(api_key))

    def factory():
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=api_key or "ollama", base_url=base_url, model=model)
    return _cache_get_or_create(key, factory)


def get_chat_client():
    from backend.app.services.model_roles import resolve_role_target
    target = resolve_role_target(None)
    return get_chat_client_for(target.api_key, target.base_url, target.model)


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
        return OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=model)
    return _cache_get_or_create(key, factory)
