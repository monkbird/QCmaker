from __future__ import annotations

import json
from dataclasses import dataclass

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException
from backend.app.services.model_providers import get_provider
from backend.app.models.config_profiles import CapabilityIssue, RuntimeSnapshot

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
    service_id: str | None = None
    api_style: str = "openai"


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


def resolve_role_target(role: str | None, *, snapshot: RuntimeSnapshot | None = None) -> ModelTarget:
    if snapshot is not None:
        if role is not None and role not in VALID_ROLES:
            raise AppException("ROLE_MODEL_INVALID", f"未知角色: {role}", 400)
        binding = snapshot.draft.roles.get(role) if role else snapshot.draft.default_model
        if binding is None and role is not None:
            binding = snapshot.draft.default_model
        if binding is None:
            raise AppException("ROLE_MODEL_MISSING", f"角色 {role or 'default'} 未配置模型", 400)
        service = next((s for s in snapshot.draft.services if s.service_id == binding.service_id), None)
        if service is None:
            raise AppException("ROLE_SERVICE_MISSING", f"角色 {role or 'default'} 绑定服务不存在: {binding.service_id}", 400)
        key = service.api_key.get_secret_value() if service.api_key else None
        if service.provider != "ollama" and not key:
            raise AppException("ROLE_MODEL_KEY_MISSING", f"角色 {role or 'default'} 的服务 {service.service_id} 缺少 API Key", 400)
        try: provider = get_provider(service.provider)
        except ValueError as exc: raise AppException("ROLE_MODEL_INVALID", f"服务商不存在: {service.provider}", 400) from exc
        return ModelTarget(provider="local" if provider.api_style == "ollama" else service.provider, base_url=service.base_url, model=binding.model, api_key=key or "ollama", service_id=service.service_id, api_style=provider.api_style)
    settings = get_settings()
    if settings.USE_LOCAL_LLM:
        return ModelTarget(provider="local", base_url=settings.LOCAL_LLM_URL, model=settings.LOCAL_LLM_MODEL, api_key="ollama", api_style="ollama")
    mapping = role_models_view()
    assigned = mapping.get(role or "", "")
    if not assigned or "|" not in assigned:
        api_key = settings.OPENAI_API_KEY or None
        if not api_key: raise AppException("LLM_NOT_CONFIGURED", "请先配置 OpenAI API Key", 400)
        return ModelTarget(provider=settings.LLM_PROVIDER, base_url=settings.OPENAI_BASE_URL, model=settings.OPENAI_MODEL, api_key=api_key, api_style=get_provider(settings.LLM_PROVIDER).api_style)
    provider_id, _, model = assigned.partition("|"); model = model.strip()
    if provider_id == "ollama":
        return ModelTarget(provider="local", base_url=settings.LOCAL_LLM_URL, model=model or settings.LOCAL_LLM_MODEL, api_key="ollama", api_style="ollama")
    try:
        catalog = get_provider(provider_id)
    except ValueError as exc:
        raise AppException("ROLE_MODEL_INVALID", f"角色 {role} 配置的模型服务商 {provider_id} 不存在", 400) from exc
    if provider_id == settings.LLM_PROVIDER:
        return ModelTarget(provider=provider_id, base_url=settings.OPENAI_BASE_URL, model=model, api_key=settings.OPENAI_API_KEY or None, api_style=catalog.api_style)
    credentials = parse_json_setting(settings.PROVIDER_CREDENTIALS).get(provider_id, {})
    api_key = credentials.get("api_key") if isinstance(credentials, dict) else None
    if not api_key:
        raise AppException("ROLE_MODEL_KEY_MISSING", f"服务商 {provider_id} 尚未保存 API Key，请在系统配置中填写", 400)
    base_url = credentials.get("base_url") or catalog.base_url
    return ModelTarget(provider=provider_id, base_url=str(base_url), model=model, api_key=str(api_key), api_style=catalog.api_style)


def check_capabilities(roles: list[str], *, snapshot: RuntimeSnapshot | None = None) -> list[CapabilityIssue]:
    issues = []
    for role in roles:
        try: resolve_role_target(role, snapshot=snapshot)
        except AppException as exc: issues.append(CapabilityIssue(role=role, code=exc.code, message=exc.message))
    return issues


def describe_target(role: str | None) -> str:
    from backend.app.repositories.config_profile_repository import active_snapshot
    target = resolve_role_target(role, snapshot=active_snapshot())
    return f"{target.provider}/{target.model}"
