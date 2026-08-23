from __future__ import annotations

import json
from dataclasses import dataclass

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException
from backend.app.services.model_providers import get_provider

VALID_ROLES = {"moderator", "researcher", "analyst", "critic", "writer", "topic", "data", "chart"}

ROLE_LABELS = {
    "moderator": "主持人",
    "researcher": "研究员",
    "analyst": "数据分析师",
    "critic": "反方评审",
    "writer": "成果撰稿人",
    "topic": "选题评估",
    "data": "清洗顾问",
    "chart": "图表顾问",
}


@dataclass(frozen=True)
class ModelTarget:
    provider: str
    base_url: str
    model: str
    api_key: str | None = None


def parse_json_setting(raw: str | None) -> dict:
    if not raw: return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError): return {}


def role_models_view() -> dict[str, str]:
    models = parse_json_setting(get_settings().ROLE_MODELS)
    return {str(role): str(target) for role, target in models.items() if role in VALID_ROLES and isinstance(target, str)}


def credential_providers() -> list[str]:
    credentials = parse_json_setting(get_settings().PROVIDER_CREDENTIALS)
    return sorted(str(pid) for pid, entry in credentials.items() if isinstance(entry, dict) and entry.get("api_key"))


def resolve_role_target(role: str | None) -> ModelTarget:
    settings = get_settings()
    if settings.USE_LOCAL_LLM:
        return ModelTarget(provider="local", base_url=settings.LOCAL_LLM_URL, model=settings.LOCAL_LLM_MODEL, api_key="ollama")
    mapping = role_models_view()
    assigned = mapping.get(role or "", "")
    if not assigned or "|" not in assigned:
        api_key = settings.OPENAI_API_KEY or None
        if not api_key: raise AppException("LLM_NOT_CONFIGURED", "请先配置 OpenAI API Key", 400)
        return ModelTarget(provider=settings.LLM_PROVIDER, base_url=settings.OPENAI_BASE_URL, model=settings.OPENAI_MODEL, api_key=api_key)
    provider_id, _, model = assigned.partition("|"); model = model.strip()
    if provider_id == "ollama":
        return ModelTarget(provider="local", base_url=settings.LOCAL_LLM_URL, model=model or settings.LOCAL_LLM_MODEL, api_key="ollama")
    try:
        catalog = get_provider(provider_id)
    except ValueError as exc:
        raise AppException("ROLE_MODEL_INVALID", f"角色 {role} 配置的模型服务商 {provider_id} 不存在", 400) from exc
    if provider_id == settings.LLM_PROVIDER:
        return ModelTarget(provider=provider_id, base_url=settings.OPENAI_BASE_URL, model=model, api_key=settings.OPENAI_API_KEY or None)
    credentials = parse_json_setting(settings.PROVIDER_CREDENTIALS).get(provider_id, {})
    api_key = credentials.get("api_key") if isinstance(credentials, dict) else None
    if not api_key:
        raise AppException("ROLE_MODEL_KEY_MISSING", f"服务商 {provider_id} 尚未保存 API Key，请在系统配置中填写", 400)
    base_url = credentials.get("base_url") or catalog.base_url
    return ModelTarget(provider=provider_id, base_url=str(base_url), model=model, api_key=str(api_key))


def describe_target(role: str | None) -> str:
    target = resolve_role_target(role)
    return f"{target.provider}/{target.model}"
