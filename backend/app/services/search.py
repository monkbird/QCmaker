import asyncio
import logging

from tavily import TavilyClient

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


def _search_sync(query: str, max_results: int) -> list[dict]:
    key = get_settings().TAVILY_API_KEY
    if not key: return []
    try:
        response = TavilyClient(api_key=key).search(query, max_results=max_results)
        return response.get("results", [])
    except Exception:
        logger.warning("tavily search failed; returning empty results", exc_info=True)
        return []


class SearchService:
    async def search(self, query: str, max_results: int = 5):
        if not get_settings().TAVILY_API_KEY: return []
        return await asyncio.to_thread(_search_sync, query, max_results)


search_service = SearchService()
