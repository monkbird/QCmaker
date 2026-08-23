from fastapi import APIRouter, Depends, Query

from backend.app.core.security import verify_access_token
from backend.app.services.search import search_service

router = APIRouter(dependencies=[Depends(verify_access_token)])


@router.get("/")
async def search(query: str = Query(min_length=1, max_length=500)):
    results = await search_service.search(query)
    return {"results": results}
