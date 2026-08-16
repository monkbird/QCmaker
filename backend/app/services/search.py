from tavily import TavilyClient

from backend.app.core.config import get_settings


class SearchService:
    async def search(self, query: str, max_results: int = 5):
        key = get_settings().TAVILY_API_KEY
        if not key: return []
        try:
            response = TavilyClient(api_key=key).search(query, max_results=max_results)
            return response.get("results", [])
        except Exception: return []

search_service = SearchService()
