"""
WebSearch tool.

Uses the DuckDuckGo HTML search endpoint to return real result snippets
(titles + descriptions). This is more reliable than the Instant Answer API,
which frequently returns no results for anything outside its knowledge-base.

No API key required.

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

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

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


def _parse_snippets(html: str, max_results: int) -> list[tuple[str, str]]:
    """
    Extract (title, snippet) pairs from DuckDuckGo HTML response.

    DuckDuckGo HTML results follow a consistent structure:
        <a class="result__a" ...>Title</a>
        <a class="result__snippet" ...>Snippet text</a>

    We use simple regex to avoid a BeautifulSoup dependency.
    """
    title_pattern   = re.compile(r'class="result__a"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    tag_strip       = re.compile(r'<[^>]+>')

    titles   = [tag_strip.sub("", t).strip() for t in title_pattern.findall(html)]
    snippets = [tag_strip.sub("", s).strip() for s in snippet_pattern.findall(html)]

    pairs = list(zip(titles, snippets))
    return pairs[:max_results]


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
            response = requests.post(
                _DDG_HTML_URL,
                data={"q": query, "b": "", "kl": "us-en"},
                headers={
                    "User-Agent": _USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=10,
                allow_redirects=True,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Web search request failed: {e}")
            return f"Search failed: {e}"

        pairs = _parse_snippets(response.text, max_results)

        if not pairs:
            logger.info(f"No snippets parsed for query: {query!r}")
            return f"No results found for: {query}"

        # Build a compact numbered list capped at _MAX_RESULT_CHARS
        lines = ["Top results:"]
        total = len(lines[0])
        for i, (title, snippet) in enumerate(pairs, 1):
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
