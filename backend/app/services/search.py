from tavily import TavilyClient
from backend.app.core.config import settings

class SearchService:
    def __init__(self):
        self.client = None
        if settings.TAVILY_API_KEY:
            self.client = TavilyClient(api_key=settings.TAVILY_API_KEY)

    async def search(self, query: str, max_results: int = 5):
        if not self.client:
            # Fallback or error if no key
            return [{"title": "No API Key", "content": "Please configure Tavily API Key", "url": "#"}]
        
        try:
            response = self.client.search(query, max_results=max_results)
            return response.get("results", [])
        except Exception as e:
            return [{"title": "Error", "content": str(e), "url": "#"}]

search_service = SearchService()
