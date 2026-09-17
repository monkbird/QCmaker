from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4
from pydantic import SecretStr

from backend.app.core.errors import AppException
from backend.app.models.config_profiles import (
    ConfigDraft, ModelBinding, ProfileSaveRequest, ProfileView, RuntimeSnapshot,
    ServiceDraft,
)
from backend.app.repositories.database import transaction
from backend.app.services.model_providers import get_provider


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _state(db):
    row = db.execute("SELECT active_profile_id, revision, legacy_migrated FROM config_profile_state WHERE id=1").fetchone()
    if row is None:
        db.execute("INSERT INTO config_profile_state(id,active_profile_id,revision,legacy_migrated) VALUES(1,NULL,0,0)")
        return None, 0, 0
    return row[0], int(row[1]), int(row[2])


def _payload(draft: ConfigDraft) -> dict:
    value = draft.model_dump(mode="json", exclude_none=True)
    for service in value.get("services", []):
        service.pop("api_key", None)
    if value.get("search"):
        value["search"].pop("api_key", None)
    return value


def _with_secrets(db, draft: ConfigDraft) -> ConfigDraft:
    result = draft.model_copy(deep=True)
    services = []
    for service in result.services:
        supplied = service.api_key
        if service.credential_id:
            row = db.execute("SELECT provider,base_url,secret FROM config_credentials WHERE credential_id=?", (service.credential_id,)).fetchone()
            if row and row[0] == service.provider and (row[1] or "").rstrip("/") == service.base_url.rstrip("/") and not supplied:
                service.api_key = SecretStr(row[2])
            elif not supplied:
                raise AppException("LLM_KEY_REQUIRED", f"服务 {service.service_id} 的凭据与地址不匹配", 400)
        services.append(service)
    result.services = services
    if result.search and result.search.credential_id and not result.search.api_key:
        row = db.execute("SELECT provider,secret FROM config_credentials WHERE credential_id=?", (result.search.credential_id,)).fetchone()
        if row and row[0] == result.search.provider:
            result.search.api_key = SecretStr(row[1])
        else:
            raise AppException("SEARCH_KEY_REQUIRED", "搜索服务凭据与服务商不匹配", 400)
    return result


def _view(db, profile_id: str, revision: int, active_id: str | None, payload: str) -> ProfileView:
    draft = ConfigDraft.model_validate(json.loads(payload))
    configured = {}
    for service in draft.services:
        if service.credential_id:
            configured[service.credential_id] = bool(db.execute("SELECT 1 FROM config_credentials WHERE credential_id=? AND secret<>''", (service.credential_id,)).fetchone())
    if draft.search and draft.search.credential_id:
        configured[draft.search.credential_id] = bool(db.execute("SELECT 1 FROM config_credentials WHERE credential_id=? AND secret<>''", (draft.search.credential_id,)).fetchone())
    return ProfileView(profile_id=profile_id, config_revision=revision, active=profile_id == active_id, draft=draft, credential_configured=configured)


def list_profiles() -> list[ProfileView]:
    with transaction() as db:
        active, revision, _ = _state(db)
        return [_view(db, row[0], revision, active, row[1]) for row in db.execute("SELECT profile_id,payload_json FROM config_profiles ORDER BY updated_at DESC")]


def has_active_profile() -> bool:
    with transaction() as db:
        active, _, _ = _state(db)
        return bool(active)


def save_and_activate(request: ProfileSaveRequest) -> ProfileView:
    with transaction(immediate=True) as db:
        if any(os.environ.get(key) for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "USE_LOCAL_LLM", "LOCAL_LLM_URL", "LOCAL_LLM_MODEL")):
            raise AppException("CONFIG_ENV_OVERRIDE", "环境变量覆盖的模型配置只能在部署环境中修改", 409)
        active, revision, _ = _state(db)
        if request.expected_revision != revision:
            raise AppException("CONFIG_REVISION_CONFLICT", "配置已更新，请刷新后重试", 409)
        draft = request.draft
        profile_id = request.profile_id or f"profile_{uuid4().hex}"
        now = _now()
        for service in draft.services:
            if service.api_key and service.api_key.get_secret_value():
                credential_id = f"cred_{uuid4().hex}"
                db.execute("INSERT INTO config_credentials(credential_id,provider,base_url,secret,created_at,updated_at) VALUES(?,?,?,?,?,?)", (credential_id, service.provider, service.base_url, service.api_key.get_secret_value(), now, now))
                service.credential_id = credential_id
            elif service.credential_id:
                if not db.execute("SELECT 1 FROM config_credentials WHERE credential_id=?", (service.credential_id,)).fetchone():
                    raise AppException("LLM_KEY_REQUIRED", "服务地址对应的 API Key 尚未保存", 400)
        if draft.search and draft.search.api_key and draft.search.api_key.get_secret_value():
            credential_id = f"cred_{uuid4().hex}"
            db.execute("INSERT INTO config_credentials(credential_id,provider,base_url,secret,created_at,updated_at) VALUES(?,?,?,?,?,?)", (credential_id, draft.search.provider, "", draft.search.api_key.get_secret_value(), now, now))
            draft.search.credential_id = credential_id
        payload = _payload(draft)
        exists = db.execute("SELECT 1 FROM config_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if exists:
            db.execute("UPDATE config_profiles SET name=?,payload_json=?,revision=revision+1,updated_at=? WHERE profile_id=?", (draft.name, json.dumps(payload, ensure_ascii=False), now, profile_id))
        else:
            db.execute("INSERT INTO config_profiles(profile_id,name,payload_json,revision,created_at,updated_at) VALUES(?,?,?,?,?,?)", (profile_id, draft.name, json.dumps(payload, ensure_ascii=False), 1, now, now))
        revision += 1
        db.execute("UPDATE config_profile_state SET active_profile_id=?,revision=? WHERE id=1", (profile_id, revision))
        return _view(db, profile_id, revision, profile_id, json.dumps(payload))


def activate(profile_id: str, expected_revision: int) -> ProfileView:
    with transaction(immediate=True) as db:
        active, revision, _ = _state(db)
        if expected_revision != revision:
            raise AppException("CONFIG_REVISION_CONFLICT", "配置已更新，请刷新后重试", 409)
        row = db.execute("SELECT payload_json FROM config_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if not row:
            raise AppException("PROFILE_NOT_FOUND", "配置方案不存在", 404)
        revision += 1
        db.execute("UPDATE config_profile_state SET active_profile_id=?,revision=? WHERE id=1", (profile_id, revision))
        return _view(db, profile_id, revision, profile_id, row[0])


def active_snapshot() -> RuntimeSnapshot | None:
    with transaction() as db:
        active, revision, _ = _state(db)
        if not active:
            return None
        row = db.execute("SELECT payload_json FROM config_profiles WHERE profile_id=?", (active,)).fetchone()
        return RuntimeSnapshot(config_revision=revision, draft=_with_secrets(db, ConfigDraft.model_validate(json.loads(row[0])))) if row else None


def resolve_draft(draft: ConfigDraft, expected_revision: int) -> RuntimeSnapshot:
    with transaction() as db:
        _, revision, _ = _state(db)
        if expected_revision != revision:
            raise AppException("CONFIG_REVISION_CONFLICT", "配置已更新，请刷新后重试", 409)
        return RuntimeSnapshot(config_revision=revision, draft=_with_secrets(db, draft))


def migrate_legacy(settings) -> None:
    from backend.app.services.model_roles import parse_json_setting
    for field in ("ROLE_MODELS", "PROVIDER_CREDENTIALS"):
        raw = getattr(settings, field, "")
        if raw:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise AppException("CONFIG_MIGRATION_INVALID", f"旧配置字段无法解析: {field}", 400) from exc
            if not isinstance(parsed, dict):
                raise AppException("CONFIG_MIGRATION_INVALID", f"旧配置字段必须是对象: {field}", 400)
    with transaction(immediate=True) as db:
        active, revision, migrated = _state(db)
        if migrated:
            return
        # A named profile is already the source of truth.  Mark legacy
        # migration complete without replacing the user's active profile.
        if active or db.execute("SELECT 1 FROM config_profiles LIMIT 1").fetchone():
            db.execute("UPDATE config_profile_state SET legacy_migrated=1 WHERE id=1")
            return
        provider_ids = {"ollama" if settings.USE_LOCAL_LLM else settings.LLM_PROVIDER}
        role_map = parse_json_setting(settings.ROLE_MODELS)
        for value in role_map.values():
            if isinstance(value, str) and "|" in value:
                provider_ids.add(value.split("|", 1)[0])
        credential_map = parse_json_setting(settings.PROVIDER_CREDENTIALS)
        services = []
        bindings = {}
        for provider_id in sorted(provider_ids):
            is_local = provider_id == "ollama"
            entry = credential_map.get(provider_id, {}) if isinstance(credential_map, dict) else {}
            service_id = f"legacy-{provider_id}"
            catalog_url = get_provider(provider_id).base_url
            base_url = settings.LOCAL_LLM_URL if is_local else (entry.get("base_url") or (settings.OPENAI_BASE_URL if provider_id == settings.LLM_PROVIDER else catalog_url))
            service = ServiceDraft(service_id=service_id, provider=provider_id, base_url=base_url, api_key="ollama" if is_local else (entry.get("api_key") or (settings.OPENAI_API_KEY if provider_id == settings.LLM_PROVIDER else None)))
            services.append(service)
            bindings[provider_id] = service_id
        default_provider = "ollama" if settings.USE_LOCAL_LLM else settings.LLM_PROVIDER
        roles = {}
        for role, value in role_map.items():
            if role in {"moderator", "researcher", "analyst", "critic", "writer", "topic", "data", "chart"} and isinstance(value, str) and "|" in value:
                provider_id, model = value.split("|", 1)
                if provider_id in bindings and model.strip(): roles[role] = ModelBinding(service_id=bindings[provider_id], model=model.strip())
        from backend.app.models.config_profiles import SearchBinding
        draft = ConfigDraft(name="现有配置", default_model=ModelBinding(service_id=bindings[default_provider], model=settings.LOCAL_LLM_MODEL if settings.USE_LOCAL_LLM else settings.OPENAI_MODEL), roles=roles, services=services, search=SearchBinding(api_key=settings.TAVILY_API_KEY) if settings.TAVILY_API_KEY else None)
        profile_id = f"profile_{uuid4().hex}"
        now = _now()
        for service in draft.services:
            if service.api_key:
                credential_id = f"cred_{uuid4().hex}"
                db.execute("INSERT INTO config_credentials(credential_id,provider,base_url,secret,created_at,updated_at) VALUES(?,?,?,?,?,?)", (credential_id, service.provider, service.base_url, service.api_key.get_secret_value(), now, now))
                service.credential_id = credential_id
        if draft.search and draft.search.api_key:
            search_credential_id = f"cred_{uuid4().hex}"
            db.execute("INSERT INTO config_credentials(credential_id,provider,base_url,secret,created_at,updated_at) VALUES(?,?,?,?,?,?)", (search_credential_id, "tavily", "", draft.search.api_key.get_secret_value(), now, now))
            draft.search.credential_id = search_credential_id
        payload = _payload(draft)
        db.execute("INSERT INTO config_profiles(profile_id,name,payload_json,revision,created_at,updated_at) VALUES(?,?,?,?,?,?)", (profile_id, draft.name, json.dumps(payload, ensure_ascii=False), 1, now, now))
        db.execute("UPDATE config_profile_state SET active_profile_id=?,revision=revision+1,legacy_migrated=1 WHERE id=1", (profile_id,))
