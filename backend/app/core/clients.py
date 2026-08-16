from __future__ import annotations

import hashlib
import threading
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException

_lock = threading.RLock()
_cache: dict[tuple[Any, ...], Any] = {}


def _fingerprint(secret: str | None) -> str:
    return hashlib.sha256((secret or "").encode()).hexdigest()[:12]


def clear_client_cache() -> None:
    with _lock: _cache.clear()


def get_chat_client():
    settings = get_settings()
    if settings.USE_LOCAL_LLM:
        key = (settings.CONFIG_REVISION, "local", settings.LOCAL_LLM_URL, settings.LOCAL_LLM_MODEL)
        api_key, base_url, model = "ollama", settings.LOCAL_LLM_URL, settings.LOCAL_LLM_MODEL
    else:
        if not settings.OPENAI_API_KEY: raise AppException("LLM_NOT_CONFIGURED", "请先配置 OpenAI API Key", 400)
        key = (settings.CONFIG_REVISION, settings.LLM_PROVIDER, settings.OPENAI_BASE_URL, settings.OPENAI_MODEL, _fingerprint(settings.OPENAI_API_KEY))
        api_key, base_url, model = settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL, settings.OPENAI_MODEL
    with _lock:
        if key not in _cache:
            try:
                from langchain_openai import ChatOpenAI
                _cache[key] = ChatOpenAI(api_key=api_key, base_url=base_url, model=model, max_tokens=settings.LLM_MAX_OUTPUT_TOKENS)
            except ImportError as exc: raise AppException("LLM_NOT_CONFIGURED", "未安装 langchain-openai", 500) from exc
        return _cache[key]


def get_embeddings_client():
    settings = get_settings()
    if not settings.OPENAI_API_KEY: raise AppException("LLM_NOT_CONFIGURED", "请先配置 OpenAI API Key", 400)
    key = (settings.CONFIG_REVISION, "embeddings", settings.OPENAI_BASE_URL, settings.EMBEDDING_MODEL, _fingerprint(settings.OPENAI_API_KEY))
    with _lock:
        if key not in _cache:
            from langchain_openai import OpenAIEmbeddings
            _cache[key] = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, model=settings.EMBEDDING_MODEL)
        return _cache[key]
