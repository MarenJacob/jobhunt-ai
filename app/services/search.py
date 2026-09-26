import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ..config import settings

class SearchService:
    async def search(self, query: str, max_results: int = 20):
        if not settings.tavily_api_key:
            return []
        payload = {"api_key": settings.tavily_api_key, "query": query, "search_depth": "advanced", "max_results": max_results, "include_answer": False}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post("https://api.tavily.com/search", json=payload)
            r.raise_for_status()
            return r.json().get("results", [])

    async def fetch_page(self, url: str):
        async with httpx.AsyncClient(follow_redirects=True, timeout=25, headers={"User-Agent": "JobHuntAI/1.0"}) as client:
            r = await client.get(url)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for x in soup(["script", "style", "noscript"]): x.decompose()
        text = " ".join(soup.stripped_strings)
        return text[:30000]

    @staticmethod
    def source_for(url: str):
        return urlparse(url).netloc.lower().replace("www.", "")
