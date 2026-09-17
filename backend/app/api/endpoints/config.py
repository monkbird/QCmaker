import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends

from backend.app.core.clients import clear_client_cache
from backend.app.core.config import get_settings, update_settings
from backend.app.core.errors import AppException
from backend.app.core.security import outbound_http_clients, validate_outbound_base_url, verify_access_token
from backend.app.models.contracts import BudgetResetResult, ConfigUpdate, ConfigView, ConnectivityCheck, ModelListRequest, ModelListResponse, UsageView
from backend.app.services.model_providers import PROVIDERS, get_provider
from backend.app.services.model_roles import ROLE_LABELS, VALID_ROLES, credential_providers, role_models_view
from backend.app.models.config_profiles import ProfileSaveRequest, ProbeRequest, ProbeReport, ProbeRow
from backend.app.repositories.config_profile_repository import activate as activate_profile, has_active_profile, list_profiles, save_and_activate, resolve_draft, migrate_legacy
from backend.app.core.llm_gateway import probe_target
from backend.app.services.usage import get_usage, reset_provider_overrun

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_access_token)])

@router.get("/profiles")
def profiles():
    migrate_legacy(get_settings())
    rows = list_profiles()
    active = next((p.profile_id for p in rows if p.active), None)
    revision = rows[0].config_revision if rows else get_settings().CONFIG_REVISION
    return {"profiles": rows, "active_profile_id": active, "config_revision": revision}

@router.post("/profiles/save")
def save_profile(request: ProfileSaveRequest):
    clear_client_cache()
    return save_and_activate(request)

@router.post("/profiles/{profile_id}/activate")
def activate_saved_profile(profile_id: str, request: dict):
    result = activate_profile(profile_id, int(request.get("expected_revision", -1)))
    clear_client_cache()
    return result

@router.post("/probe-draft", response_model=ProbeReport)
async def probe_draft(request: ProbeRequest):
    snapshot = resolve_draft(request.draft, request.expected_revision)
    rows = []
    targets = {}
    if snapshot.draft.default_model is not None:
        try:
            from backend.app.services.model_roles import resolve_role_target
            target = resolve_role_target(None, snapshot=snapshot)
            key = (target.provider, target.base_url.rstrip("/"), target.model, target.api_style, target.api_key)
            targets.setdefault(key, []).append(("default", target))
        except AppException as exc:
            rows.append(ProbeRow(role="default", service_id=None, provider=None, base_url=None, model=None, status="missing", code=exc.code, message=exc.message))
    for role in sorted(VALID_ROLES):
        try:
            from backend.app.services.model_roles import resolve_role_target
            target = resolve_role_target(role, snapshot=snapshot)
            key = (target.provider, target.base_url.rstrip("/"), target.model, target.api_style, target.api_key)
            targets.setdefault(key, []).append((role, target))
        except AppException as exc:
            rows.append(ProbeRow(role=role, service_id=None, provider=None, base_url=None, model=None, status="missing", code=exc.code, message=exc.message))
    results = {}
    for key, refs in targets.items():
        try: results[key] = await probe_target(refs[0][1])
        except AppException as exc: results[key] = {"error": exc}
    for key, refs in targets.items():
        result = results[key]
        for role, target in refs:
            error = result.get("error") if isinstance(result, dict) else None
            rows.append(ProbeRow(role=role, service_id=target.service_id, provider=target.provider, base_url=target.base_url, model=target.model, status="failed" if error else "passed", code=error.code if error else None, message=error.message if error else str(result.get("message", "调用成功")), latency_ms=None if error else result.get("latency_ms")))
    rows.sort(key=lambda x: x.role)
    return ProbeReport(draft_version=request.draft_version, config_revision=snapshot.config_revision, passed=bool(rows) and all(row.status == "passed" for row in rows), rows=rows)

_CATALOG = {provider.id: provider for provider in PROVIDERS}


def view() -> ConfigView:
    s = get_settings(); configured = bool(s.LOCAL_LLM_URL) if s.USE_LOCAL_LLM else bool(s.OPENAI_API_KEY)
    return ConfigView(llm_provider="ollama" if s.USE_LOCAL_LLM else s.LLM_PROVIDER, openai_base_url=s.OPENAI_BASE_URL, openai_model=s.OPENAI_MODEL, use_local_llm=s.USE_LOCAL_LLM, local_llm_url=s.LOCAL_LLM_URL, local_llm_model=s.LOCAL_LLM_MODEL, max_budget_usd=s.MAX_BUDGET_USD, has_openai_key=bool(s.OPENAI_API_KEY), has_tavily_key=bool(s.TAVILY_API_KEY), status="ready" if configured else "missing", config_revision=s.CONFIG_REVISION, role_models=role_models_view(), credential_providers=credential_providers())


def _sanitize_role_models(role_models: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for role, target in role_models.items():
        if role not in VALID_ROLES: raise AppException("CONFIG_INVALID", f"未知的角色槽位: {role}", 400)
        target = str(target).strip()
        if not target:
            continue
        if "|" not in target:
            raise AppException("CONFIG_INVALID", "角色分工必须同时指定服务商和模型", 400)
        provider_id, _, model = target.partition("|"); model = model.strip()
        if provider_id not in _CATALOG: raise AppException("PROVIDER_NOT_FOUND", f"角色 {ROLE_LABELS.get(role, role)} 的服务商 {provider_id} 不存在", 404)
        if provider_id != "ollama" and not model: raise AppException("MODEL_BASE_URL_REQUIRED", f"角色 {ROLE_LABELS.get(role, role)} 必须填写模型名称", 400)
        cleaned[role] = f"{provider_id}|{model}"
    return cleaned


def _merge_credentials(updates: dict) -> dict[str, dict]:
    settings = get_settings()
    merged = {str(key): dict(value) for key, value in (json.loads(settings.PROVIDER_CREDENTIALS or "{}").items() if settings.PROVIDER_CREDENTIALS else {})}
    for provider_id, credential in updates.items():
        if provider_id not in _CATALOG: raise AppException("PROVIDER_NOT_FOUND", f"服务商 {provider_id} 不存在", 404)
        entry = merged.setdefault(provider_id, {})
        api_key = getattr(credential, "api_key", None)
        base_url = getattr(credential, "base_url", None)
        old_url = entry.get("base_url") or _CATALOG[provider_id].base_url
        if base_url and base_url.rstrip("/") != old_url.rstrip("/") and entry.get("api_key") and not api_key:
            raise AppException("LLM_KEY_REQUIRED", "变更服务地址时必须填写该地址对应的 API Key", 400)
        if api_key: entry["api_key"] = api_key.strip()
        if base_url: entry["base_url"] = validate_outbound_base_url(base_url.strip(), allow_private=provider_id == "ollama")
    return merged


@router.get("/", response_model=ConfigView)
def get_config(): return view()


@router.post("/update", response_model=ConfigView)
def update_config(config: ConfigUpdate):
    settings = get_settings()
    if has_active_profile() and any(value is not None for value in (
        config.llm_provider, config.openai_api_key, config.openai_base_url,
        config.openai_model, config.use_local_llm, config.local_llm_url,
        config.local_llm_model, config.tavily_api_key, config.role_models,
        config.provider_credentials,
    )):
        raise AppException("CONFIG_PROFILE_REQUIRED", "当前已有活动配置方案，请通过配置方案接口保存模型设置", 409)
    payload = {key.upper(): value for key, value in config.model_dump().items() if value is not None}
    if (not config.llm_provider or config.llm_provider == settings.LLM_PROVIDER) and config.openai_base_url and config.openai_base_url.rstrip("/") != settings.OPENAI_BASE_URL.rstrip("/") and settings.OPENAI_API_KEY and not config.openai_api_key:
        raise AppException("LLM_KEY_REQUIRED", "变更服务地址时必须填写该地址对应的 API Key", 400)
    target_provider = payload.get("LLM_PROVIDER")
    if target_provider is not None:
        try:
            provider = get_provider(target_provider)
        except ValueError as exc:
            raise AppException("PROVIDER_NOT_FOUND", "未找到该模型服务商", 404, {"provider": target_provider}) from exc
        switching = target_provider != "ollama" and target_provider != settings.LLM_PROVIDER
        if switching and not payload.get("OPENAI_BASE_URL"):
            stored_target = json.loads(settings.PROVIDER_CREDENTIALS or "{}").get(target_provider, {})
            payload["OPENAI_BASE_URL"] = stored_target.get("base_url") or provider.base_url
        if switching and not payload.get("OPENAI_API_KEY") and not payload.get("USE_LOCAL_LLM"):
            stored = json.loads(settings.PROVIDER_CREDENTIALS or "{}").get(target_provider, {})
            stored_key = stored.get("api_key") if isinstance(stored, dict) else None
            bound_url = stored.get("base_url") or provider.base_url
            if stored_key and str(payload.get("OPENAI_BASE_URL") or "").rstrip("/") == bound_url.rstrip("/"):
                payload["OPENAI_API_KEY"] = str(stored_key)
            else: raise AppException("LLM_KEY_REQUIRED", "切换模型服务商时必须填写该服务商的 API Key", 400)
        if provider.api_style == "anthropic":
            logger.warning("provider %s relies on the OpenAI-compatible gateway endpoint", target_provider)
        if not _CATALOG[provider.id].base_url and not str(payload.get("OPENAI_BASE_URL") or "").strip():
            raise AppException("MODEL_BASE_URL_REQUIRED", "自定义服务必须同时填写 API 地址", 400)
    if "OPENAI_BASE_URL" in payload:
        payload["OPENAI_BASE_URL"] = validate_outbound_base_url(str(payload["OPENAI_BASE_URL"]))
    if "LOCAL_LLM_URL" in payload:
        payload["LOCAL_LLM_URL"] = validate_outbound_base_url(str(payload["LOCAL_LLM_URL"]), allow_private=True)
    if config.role_models is not None:
        payload["ROLE_MODELS"] = json.dumps(_sanitize_role_models(config.role_models), ensure_ascii=False)
    if config.provider_credentials is not None and config.provider_credentials:
        payload["PROVIDER_CREDENTIALS"] = json.dumps(_merge_credentials(config.provider_credentials), ensure_ascii=False)
    try:
        update_settings(payload)
    except ValueError as exc:
        raise AppException("CONFIG_INVALID", str(exc), 400) from exc
    clear_client_cache()
    from backend.app.core.security import rebuild_rate_limiter
    rebuild_rate_limiter()
    return view()


@router.get("/providers")
def providers(): return {"providers": provider_catalog()}


def provider_catalog():
    from dataclasses import asdict
    return [asdict(provider) for provider in PROVIDERS]


def _bound_key(provider_id: str, base_url: str, explicit_key: str | None):
    if explicit_key:
        return explicit_key
    settings = get_settings()
    stored = json.loads(settings.PROVIDER_CREDENTIALS or "{}").get(provider_id, {})
    if isinstance(stored, dict) and stored.get("api_key"):
        bound = stored.get("base_url") or get_provider(provider_id).base_url
        if base_url.rstrip("/") == bound.rstrip("/"):
            return stored["api_key"]
    if provider_id == settings.LLM_PROVIDER and base_url.rstrip("/") == settings.OPENAI_BASE_URL.rstrip("/"):
        return settings.OPENAI_API_KEY
    return None


@router.post("/models", response_model=ModelListResponse)
async def models(request: ModelListRequest):
    settings = get_settings()
    try:
        provider = get_provider(request.provider)
    except ValueError as exc:
        raise AppException("PROVIDER_NOT_FOUND", "未找到该模型服务商", 404, {"provider": request.provider}) from exc
    stored = json.loads(settings.PROVIDER_CREDENTIALS or "{}").get(request.provider, {})
    default_url = settings.LOCAL_LLM_URL if provider.api_style == "ollama" else (stored.get("base_url") or (settings.OPENAI_BASE_URL if request.provider == settings.LLM_PROVIDER else provider.base_url))
    base_url = validate_outbound_base_url((request.base_url or default_url).rstrip("/"), allow_private=provider.api_style == "ollama")
    api_key = _bound_key(request.provider, base_url, request.api_key)
    if request.credential_id and not request.api_key:
        from backend.app.repositories.database import connect
        db = connect()
        try:
            credential = db.execute('SELECT provider,base_url,secret FROM config_credentials WHERE credential_id=?', (request.credential_id,)).fetchone()
        finally:
            db.close()
        if not credential or credential['provider'] != request.provider or (credential['base_url'] or '').rstrip('/') != base_url.rstrip('/'):
            raise AppException('LLM_KEY_REQUIRED', '服务地址变化，请提供对应密钥', 400)
        api_key = credential['secret']
    if provider.api_style == "ollama":
        url = f"{base_url.removesuffix('/v1')}/api/tags"; headers = {}
    else:
        if not api_key:
            raise AppException("LLM_KEY_REQUIRED", "请先填写该服务商的 API Key，再联网获取模型", 400)
        url = f"{base_url}/models"; headers = {"Authorization": f"Bearer {api_key}"}
        if provider.api_style == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    try:
        sync_client, async_client = outbound_http_clients(provider.api_style == "ollama")
        sync_client.close()
        async with async_client as client:
            response = await client.get(url, headers=headers); response.raise_for_status(); payload = response.json()
        rows = payload.get("models", []) if provider.api_style == "ollama" else payload.get("data", payload.get("models", []))
        names = sorted({str(row.get("name") if provider.api_style == "ollama" else row.get("id") or row.get("name", "")).removeprefix("models/") for row in rows if isinstance(row, dict)})
        names = [name for name in names if name]
        if not names:
            raise AppException("MODEL_LIST_EMPTY", "厂商接口未返回可选模型", 502, {"provider": request.provider})
        return ModelListResponse(models=names[:500], source="remote")
    except AppException:
        raise
    except httpx.HTTPStatusError as exc:
        raise AppException("MODEL_LIST_FAILED", "厂商模型列表请求失败，请检查 API Key 和接口地址", 400, {"provider": request.provider, "status_code": exc.response.status_code}) from exc
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise AppException("MODEL_LIST_FAILED", "无法连接厂商模型接口", 502, {"provider": request.provider, "reason": type(exc).__name__}) from exc


@router.post("/check-connectivity")
async def check_connectivity(check: ConnectivityCheck):
    settings = get_settings(); local = check.provider in {"local", "ollama"}; base_url = validate_outbound_base_url(check.base_url or (settings.LOCAL_LLM_URL if local else settings.OPENAI_BASE_URL), allow_private=local); model = check.model or (settings.LOCAL_LLM_MODEL if local else settings.OPENAI_MODEL); api_key = "ollama" if local else _bound_key(check.provider, base_url, check.api_key)
    if not api_key: raise AppException("LLM_NOT_CONFIGURED", "缺少 API Key", 400)
    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
    from uuid import uuid4

    from backend.app.services.usage import mark_dispatched, reserve, settle
    request_id = f"connect_{uuid4().hex}"
    reservation = reserve(request_id, "local" if local else check.provider, model, "ping")
    mark_dispatched(reservation)
    try:
        sync_client, async_client = outbound_http_clients(local)
        sync_client.close()
        async with async_client as client:
            if local: response = await client.get(f"{base_url.removesuffix('/v1')}/api/tags")
            else: response = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
            response.raise_for_status()
        usage = {} if local else response.json().get("usage", {})
        settle(reservation, request_id, "local" if local else check.provider, model, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), usage_known=bool(usage))
        return {"status": "connected", "latency_ms": round((time.perf_counter() - started) * 1000), "model": model, "message": "连接成功"}
    except Exception as exc:
        settle(reservation, request_id, "local" if local else check.provider, model, 0, 0, usage_known=False)
        if isinstance(exc, AppException): raise
        raise AppException("LLM_CONNECT_FAILED", "模型连接失败", 400, {"reason": type(exc).__name__}) from exc


@router.get("/usage", response_model=UsageView)
def usage(): return get_usage()


@router.post("/budget/reset-overrun", response_model=BudgetResetResult)
def budget_reset_overrun(): 
    cleared = reset_provider_overrun()
    logger.warning("provider_overrun holds cleared by admin: %s", cleared)
    return BudgetResetResult(cleared_reservations=cleared)
