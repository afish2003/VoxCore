"""
WebSearch tool.

Uses the SearX public JSON API (searx.tiekoetter.com) to return real search
result snippets. SearX returns structured JSON directly — no HTML scraping,
no regex parsing, no API key required.

Results are capped at ~300 characters total so the LLM receives a concise
context block rather than a wall of text.

Query normalization:
    Speech recognition occasionally mishears domain-specific terms.
    A small alias table corrects the most common substitutions before the
    query is sent to the search engine.
"""
import logging
import re
import requests

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)

_SEARX_URL = "https://searx.tiekoetter.com/search"
_USER_AGENT = "VoxCore/1.0 (voice assistant; research)"

# Maximum total characters returned to the LLM
_MAX_RESULT_CHARS = 300

# ---------------------------------------------------------------------------
# Query normalization — speech-recognition alias corrections
# Keys are uppercase for case-insensitive matching.
# ---------------------------------------------------------------------------
_QUERY_ALIASES: dict[str, str] = {
    "VARLAT":  "VAR Lab",
    "VARLAB":  "VAR Lab",
    "VAR LAT": "VAR Lab",
    "BARRON":  "Behrend",
}


def _normalize_query(query: str) -> str:
    """Replace known speech-recognition mishears with the intended term."""
    normalized = query
    for wrong, correct in _QUERY_ALIASES.items():
        # Case-insensitive whole-word replacement
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        normalized = pattern.sub(correct, normalized)
    if normalized != query:
        logger.info(f"Query normalized: {query!r} -> {normalized!r}")
    return normalized


class WebSearch(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current events, recent news, or specific factual "
        "information that you do not already know. "
        "Do NOT use for jokes, general knowledge, math, or creative tasks."
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
        query = _normalize_query(query)
        logger.info(f"Web search: {query!r}")

        try:
            response = requests.get(
                _SEARX_URL,
                params={"q": query, "format": "json", "language": "en"},
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Web search request failed: {e}")
            return f"Search failed: {e}"

        results = data.get("results", [])[:max_results]

        if not results:
            logger.info(f"No results for query: {query!r}")
            return f"No results found for: {query}"

        # Build a compact numbered list capped at _MAX_RESULT_CHARS
        lines = ["Top results:"]
        total = len(lines[0])
        for i, result in enumerate(results, 1):
            title   = result.get("title", "").strip()
            snippet = result.get("content", "").strip()
            entry = f"{i}. {title} – {snippet}"
            if total + len(entry) > _MAX_RESULT_CHARS:
                # Truncate the snippet to fit within the budget
                budget = _MAX_RESULT_CHARS - total - len(f"{i}. {title} – ") - 1
                if budget > 20:
                    entry = f"{i}. {title} – {snippet[:budget]}…"
                else:
                    break
            lines.append(entry)
            total += len(entry)

        return "\n".join(lines)
