"""
WebSearch tool.

Searches the web using the DuckDuckGo Instant Answer API.
No API key required. Results include the best abstract answer and
related topics for the query.

For production use requiring full web results, swap this class for
one backed by Bing Search API, SerpAPI, or any other search provider
by subclassing BaseTool and registering it instead.

Example LLM trigger: "Search for the latest news on..." / "Look up..."
"""
import logging
import requests

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)

_DDG_API_URL = "https://api.duckduckgo.com/"
_USER_AGENT = "VoxCore/1.0 (voice assistant; research)"


class WebSearch(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current information, facts, news, or any topic. "
        "Use this when the user asks about something that may require live or "
        "up-to-date information you don't already know."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of result snippets to return. Default: 3.",
                "default": 3,
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, max_results: int = 3, **kwargs) -> str:
        logger.info(f"Web search: {query!r}")
        try:
            response = requests.get(
                _DDG_API_URL,
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Web search request failed: {e}")
            return f"Search failed: {e}"

        parts = []

        # Best instant answer (e.g. calculations, unit conversions)
        if data.get("Answer"):
            parts.append(data["Answer"])

        # Abstract from a knowledge source (Wikipedia, etc.)
        if data.get("AbstractText"):
            source = data.get("AbstractSource", "")
            text = data["AbstractText"]
            parts.append(f"{text} (Source: {source})" if source else text)

        # Related topic snippets
        for topic in data.get("RelatedTopics", []):
            if len(parts) >= max_results:
                break
            if isinstance(topic, dict) and "Text" in topic:
                parts.append(topic["Text"])

        if parts:
            return "\n\n".join(parts[:max_results])

        logger.info(f"No results for query: {query!r}")
        return f"No results found for: {query}"
