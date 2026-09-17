from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from backend.app.models.config_profiles import ConfigDraft
from backend.app.repositories.config_profile_repository import resolve_draft
from backend.app.core.errors import AppException
from backend.app.services.search import _search_sync

from backend.app.core.security import verify_access_token
from backend.app.services.search import search_service

router = APIRouter(dependencies=[Depends(verify_access_token)])


@router.get("/")
async def search(query: str = Query(min_length=1, max_length=500)):
    return await search_service.search_with_status(query)

class SearchTestRequest(BaseModel):
    draft: ConfigDraft
    expected_revision: int = Field(ge=0)
    draft_version: int = Field(ge=1)
    query: str = Field(default='quality management', min_length=1, max_length=100)

@router.post('/test')
async def test_search(request: SearchTestRequest):
    runtime = resolve_draft(request.draft, request.expected_revision)
    binding = runtime.draft.search
    if not binding or not binding.api_key:
        return {'status':'not_configured','draft_version':request.draft_version,'config_revision':runtime.config_revision,'results':[]}
    import asyncio
    try:
        results = await asyncio.to_thread(lambda: __import__('tavily').TavilyClient(api_key=binding.api_key.get_secret_value()).search(request.query,max_results=3).get('results',[]))
        return {'status':'success' if results else 'empty','draft_version':request.draft_version,'config_revision':runtime.config_revision,'results':[{'title':r.get('title'),'url':r.get('url')} for r in results if r.get('url')]}
    except Exception:
        return {'status':'failed','draft_version':request.draft_version,'config_revision':runtime.config_revision,'results':[],'error':'搜索服务不可用'}
