import asyncio
import logging
import time
from backend.app.models.authoring import SearchResponse, SearchSource

from tavily import TavilyClient

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)


def _search_sync(query: str, max_results: int) -> list[dict]:
    key = get_settings().TAVILY_API_KEY
    try:
        from backend.app.repositories.config_profile_repository import active_snapshot
        snap = active_snapshot()
        if snap and snap.draft.search and snap.draft.search.api_key:
            key = snap.draft.search.api_key.get_secret_value()
    except Exception:
        pass
    if not key: return []
    try:
        response = TavilyClient(api_key=key).search(query, max_results=max_results)
        return response.get("results", [])
    except Exception as exc:
        logger.warning("tavily search failed", exc_info=True)
        raise RuntimeError("search provider unavailable") from exc


class SearchService:
    async def search(self, query: str, max_results: int = 5):
        if not get_settings().TAVILY_API_KEY:
            try:
                from backend.app.repositories.config_profile_repository import active_snapshot
                snap = active_snapshot()
                if not (snap and snap.draft.search and snap.draft.search.api_key): return []
            except Exception: return []
        return await asyncio.to_thread(_search_sync, query, max_results)

    async def search_with_status(self, query: str, max_results: int = 5) -> SearchResponse:
        if not get_settings().TAVILY_API_KEY:
            try:
                from backend.app.repositories.config_profile_repository import active_snapshot
                snap = active_snapshot()
                if not (snap and snap.draft.search and snap.draft.search.api_key):
                    return SearchResponse(status='not_configured')
            except Exception:
                return SearchResponse(status='not_configured')
        started = time.monotonic()
        try:
            results = await self.search(query, max_results)
            sources = [SearchSource(title=str(x.get('title') or x.get('url') or '未命名来源'), url=str(x.get('url') or ''), published_at=x.get('published_date'), content=x.get('content')) for x in results if x.get('url')]
            return SearchResponse(status='success' if results else 'empty', results=results, sources=sources, elapsed_ms=int((time.monotonic()-started)*1000))
        except Exception as exc:
            return SearchResponse(status='failed', elapsed_ms=int((time.monotonic()-started)*1000), error=str(exc)[:300])


search_service = SearchService()
