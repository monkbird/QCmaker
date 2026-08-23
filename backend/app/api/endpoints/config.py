import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends

from backend.app.core.clients import clear_client_cache
from backend.app.core.config import get_settings, update_settings
from backend.app.core.errors import AppException
from backend.app.core.security import validate_outbound_base_url, verify_access_token
from backend.app.models.contracts import BudgetResetResult, ConfigUpdate, ConfigView, ConnectivityCheck, ModelListRequest, ModelListResponse, UsageView
from backend.app.services.model_providers import PROVIDERS, get_provider
from backend.app.services.model_roles import ROLE_LABELS, VALID_ROLES, credential_providers, role_models_view
from backend.app.services.usage import get_usage, reset_provider_overrun

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_access_token)])

_CATALOG = {provider.id: provider for provider in PROVIDERS}


def view() -> ConfigView:
    s = get_settings(); configured = bool(s.LOCAL_LLM_URL) if s.USE_LOCAL_LLM else bool(s.OPENAI_API_KEY)
    return ConfigView(llm_provider="ollama" if s.USE_LOCAL_LLM else s.LLM_PROVIDER, openai_base_url=s.OPENAI_BASE_URL, openai_model=s.OPENAI_MODEL, use_local_llm=s.USE_LOCAL_LLM, local_llm_url=s.LOCAL_LLM_URL, local_llm_model=s.LOCAL_LLM_MODEL, max_budget_usd=s.MAX_BUDGET_USD, has_openai_key=bool(s.OPENAI_API_KEY), has_tavily_key=bool(s.TAVILY_API_KEY), status="ready" if configured else "missing", config_revision=s.CONFIG_REVISION, role_models=role_models_view(), credential_providers=credential_providers())


def _sanitize_role_models(role_models: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for role, target in role_models.items():
        if role not in VALID_ROLES: raise AppException("CONFIG_INVALID", f"未知的角色槽位: {role}", 400)
        target = str(target).strip()
        if not target or "|" not in target:
            continue
        provider_id, _, model = target.partition("|"); model = model.strip()
        if provider_id not in _CATALOG: raise AppException("PROVIDER_NOT_FOUND", f"角色 {ROLE_LABELS.get(role, role)} 的服务商 {provider_id} 不存在", 404)
        if provider_id not in {"ollama", "custom"} and not model: raise AppException("MODEL_BASE_URL_REQUIRED", f"角色 {ROLE_LABELS.get(role, role)} 必须填写模型名称", 400)
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
        if api_key: entry["api_key"] = api_key.strip()
        if base_url: entry["base_url"] = validate_outbound_base_url(base_url.strip(), allow_private=provider_id == "ollama")
    return merged


@router.get("/", response_model=ConfigView)
def get_config(): return view()


@router.post("/update", response_model=ConfigView)
def update_config(config: ConfigUpdate):
    settings = get_settings()
    payload = {key.upper(): value for key, value in config.model_dump().items() if value is not None}
    target_provider = payload.get("LLM_PROVIDER")
    if target_provider is not None:
        try:
            provider = get_provider(target_provider)
        except ValueError as exc:
            raise AppException("PROVIDER_NOT_FOUND", "未找到该模型服务商", 404, {"provider": target_provider}) from exc
        switching = target_provider != "ollama" and target_provider != settings.LLM_PROVIDER
        if switching and not payload.get("OPENAI_API_KEY") and not payload.get("USE_LOCAL_LLM"):
            stored = json.loads(settings.PROVIDER_CREDENTIALS or "{}").get(target_provider, {})
            stored_key = stored.get("api_key") if isinstance(stored, dict) else None
            if stored_key: payload["OPENAI_API_KEY"] = str(stored_key)
            else: raise AppException("LLM_KEY_REQUIRED", "切换模型服务商时必须填写该服务商的 API Key", 400)
        if provider.api_style == "anthropic":
            logger.warning("provider %s relies on the OpenAI-compatible gateway endpoint", target_provider)
        if not _CATALOG[provider.id].base_url and not str(payload.get("OPENAI_BASE_URL") or "").strip():
            raise AppException("MODEL_BASE_URL_REQUIRED", "自定义服务必须同时填写 API 地址", 400)
    if "OPENAI_BASE_URL" in payload:
        allow_private = bool(payload.get("USE_LOCAL_LLM", settings.USE_LOCAL_LLM))
        payload["OPENAI_BASE_URL"] = validate_outbound_base_url(str(payload["OPENAI_BASE_URL"]), allow_private=allow_private)
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


@router.post("/models", response_model=ModelListResponse)
async def models(request: ModelListRequest):
    settings = get_settings()
    try:
        provider = get_provider(request.provider)
    except ValueError as exc:
        raise AppException("PROVIDER_NOT_FOUND", "未找到该模型服务商", 404, {"provider": request.provider}) from exc
    base_url = validate_outbound_base_url((request.base_url or provider.base_url).rstrip("/"), allow_private=provider.api_style == "ollama" or settings.USE_LOCAL_LLM)
    stored = json.loads(settings.PROVIDER_CREDENTIALS or "{}").get(request.provider, {})
    api_key = request.api_key or (stored.get("api_key") if isinstance(stored, dict) else None) or (settings.OPENAI_API_KEY if request.provider == settings.LLM_PROVIDER else None)
    if provider.api_style == "ollama":
        url = f"{base_url.removesuffix('/v1')}/api/tags"; headers = {}
    else:
        if not api_key:
            raise AppException("LLM_KEY_REQUIRED", "请先填写该服务商的 API Key，再联网获取模型", 400)
        url = f"{base_url}/models"; headers = {"Authorization": f"Bearer {api_key}"}
        if provider.api_style == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
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
    settings = get_settings(); local = check.provider in {"local", "ollama"}; base_url = validate_outbound_base_url(check.base_url or (settings.LOCAL_LLM_URL if local else settings.OPENAI_BASE_URL), allow_private=local or settings.USE_LOCAL_LLM); model = check.model or (settings.LOCAL_LLM_MODEL if local else settings.OPENAI_MODEL); api_key = check.api_key or ("ollama" if local else settings.OPENAI_API_KEY if check.provider == settings.LLM_PROVIDER else None)
    if not api_key: raise AppException("LLM_NOT_CONFIGURED", "缺少 API Key", 400)
    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if local: response = await client.get(f"{base_url.removesuffix('/v1')}/api/tags")
            else: response = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
            response.raise_for_status()
        return {"status": "connected", "latency_ms": round((time.perf_counter() - started) * 1000), "model": model, "message": "连接成功"}
    except httpx.HTTPError as exc: raise AppException("LLM_CONNECT_FAILED", "模型连接失败", 400, {"reason": type(exc).__name__}) from exc


@router.get("/usage", response_model=UsageView)
def usage(): return get_usage()


@router.post("/budget/reset-overrun", response_model=BudgetResetResult)
def budget_reset_overrun(): 
    cleared = reset_provider_overrun()
    logger.warning("provider_overrun holds cleared by admin: %s", cleared)
    return BudgetResetResult(cleared_reservations=cleared)
