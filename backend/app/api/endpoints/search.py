from fastapi import APIRouter, HTTPException
from backend.app.services.search import search_service

router = APIRouter()

@router.get("/")
async def search(query: str):
    results = await search_service.search(query)
    return {"results": results}
