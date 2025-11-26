from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
import httpx

router = APIRouter()

class ConfigUpdate(BaseModel):
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    use_local_llm: Optional[bool] = None
    local_llm_url: Optional[str] = None
    tavily_api_key: Optional[str] = None
    max_budget_usd: Optional[float] = None

class ConnectivityCheck(BaseModel):
    base_url: str
    api_key: str
    model: str = "gpt-3.5-turbo"

@router.get("/")
async def get_config():
    # In a real app, we might not want to return keys, but for this local tool it's fine
    # or we just return masked versions.
    return {
        "openai_base_url": os.getenv("OPENAI_BASE_URL"),
        "use_local_llm": os.getenv("USE_LOCAL_LLM") == "True",
        "local_llm_url": os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"),
        "max_budget_usd": float(os.getenv("MAX_BUDGET_USD", 5.0)),
        "has_openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "has_tavily_key": bool(os.getenv("TAVILY_API_KEY")),
    }

@router.post("/update")
async def update_config(config: ConfigUpdate):
    # This is a simple implementation that just sets env vars for the process
    # In production, this should write to a .env file or database
    if config.openai_api_key:
        os.environ["OPENAI_API_KEY"] = config.openai_api_key
    if config.openai_base_url:
        os.environ["OPENAI_BASE_URL"] = config.openai_base_url
    if config.use_local_llm is not None:
        os.environ["USE_LOCAL_LLM"] = str(config.use_local_llm)
    if config.local_llm_url:
        os.environ["LOCAL_LLM_URL"] = config.local_llm_url
    if config.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = config.tavily_api_key
    if config.max_budget_usd:
        os.environ["MAX_BUDGET_USD"] = str(config.max_budget_usd)
    
    return {"status": "updated"}

@router.post("/check-connectivity")
async def check_connectivity(check: ConnectivityCheck):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{check.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {check.api_key}"},
                json={
                    "model": check.model,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 5
                },
                timeout=10.0
            )
            response.raise_for_status()
            return {"status": "connected", "latency": response.elapsed.total_seconds()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {str(e)}")
