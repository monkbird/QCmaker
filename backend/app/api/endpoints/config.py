import time

import httpx
from fastapi import APIRouter

from backend.app.core.clients import clear_client_cache
from backend.app.core.config import get_settings, update_settings
from backend.app.core.errors import AppException
from backend.app.models.contracts import ConfigUpdate, ConfigView, ConnectivityCheck, ModelListRequest, ModelListResponse, UsageView
from backend.app.services.model_providers import get_provider, provider_catalog
from backend.app.services.usage import get_usage

router = APIRouter()

def view() -> ConfigView:
    s = get_settings(); configured = bool(s.LOCAL_LLM_URL) if s.USE_LOCAL_LLM else bool(s.OPENAI_API_KEY)
    return ConfigView(llm_provider="ollama" if s.USE_LOCAL_LLM else s.LLM_PROVIDER, openai_base_url=s.OPENAI_BASE_URL, openai_model=s.OPENAI_MODEL, use_local_llm=s.USE_LOCAL_LLM, local_llm_url=s.LOCAL_LLM_URL, local_llm_model=s.LOCAL_LLM_MODEL, max_budget_usd=s.MAX_BUDGET_USD, has_openai_key=bool(s.OPENAI_API_KEY), has_tavily_key=bool(s.TAVILY_API_KEY), status="ready" if configured else "missing", config_revision=s.CONFIG_REVISION)

@router.get("/", response_model=ConfigView)
def get_config(): return view()

@router.post("/update", response_model=ConfigView)
def update_config(config: ConfigUpdate):
    settings = get_settings()
    if config.llm_provider and config.llm_provider != "ollama" and config.llm_provider != settings.LLM_PROVIDER and not config.openai_api_key:
        raise AppException("LLM_KEY_REQUIRED", "切换模型服务商时必须填写该服务商的 API Key", 400)
    mapping = {key.upper(): value for key, value in config.model_dump().items()}
    update_settings(mapping); clear_client_cache(); return view()

@router.get("/providers")
def providers(): return {"providers": provider_catalog()}

@router.post("/models", response_model=ModelListResponse)
async def models(request: ModelListRequest):
    settings = get_settings()
    try:
        provider = get_provider(request.provider)
    except ValueError as exc:
        raise AppException("PROVIDER_NOT_FOUND", "未找到该模型服务商", 404, {"provider": request.provider}) from exc
    base_url = (request.base_url or provider.base_url).rstrip("/")
    if not base_url:
        raise AppException("MODEL_BASE_URL_REQUIRED", "请先填写模型服务的 API 地址", 400)
    api_key = request.api_key or (settings.OPENAI_API_KEY if request.provider == settings.LLM_PROVIDER else None)
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
    settings = get_settings(); local = check.provider in {"local", "ollama"}; base_url = check.base_url or (settings.LOCAL_LLM_URL if local else settings.OPENAI_BASE_URL); model = check.model or (settings.LOCAL_LLM_MODEL if local else settings.OPENAI_MODEL); api_key = check.api_key or ("ollama" if local else settings.OPENAI_API_KEY if check.provider == settings.LLM_PROVIDER else None)
    if not api_key: raise AppException("LLM_NOT_CONFIGURED", "缺少 API Key", 400)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if local: response = await client.get(f"{base_url.removesuffix('/v1')}/api/tags")
            else: response = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
            response.raise_for_status()
        return {"status": "connected", "latency_ms": round((time.perf_counter() - started) * 1000), "model": model, "message": "连接成功"}
    except httpx.HTTPError as exc: raise AppException("LLM_CONNECT_FAILED", "模型连接失败", 400, {"reason": type(exc).__name__}) from exc

@router.get("/usage", response_model=UsageView)
def usage(): return get_usage()
