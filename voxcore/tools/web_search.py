"""
WebSearch tool.

Uses the SearX public JSON API to return real search result snippets.
Multiple SearX instances are tried in randomized order; on 429 or timeout
the next instance is tried automatically.

Results are capped at ~800 characters total so the LLM receives concise
context with source URLs.

Query normalization:
    Speech recognition occasionally mishears domain-specific terms.
    A small alias table corrects the most common substitutions before the
    query is sent to the search engine.
"""
import logging
import random
import re
import requests

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)

_USER_AGENT = "VoxCore/1.0 (voice assistant; research)"
_PER_REQUEST_TIMEOUT = 5
_MAX_RESULT_CHARS = 800

_DEFAULT_INSTANCES = [
    "https://searx.tiekoetter.com",
    "https://search.sapti.me",
    "https://searx.bndkt.io",
    "https://searx.fmac.xyz",
]

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

    def __init__(self, instances: list | None = None):
        self._instances = instances or list(_DEFAULT_INSTANCES)

    def execute(self, query: str, max_results: int = 3, **kwargs) -> str:
        query = _normalize_query(query)
        logger.info(f"Web search: {query!r}")

        # Randomize instance order to distribute load
        instances = list(self._instances)
        random.shuffle(instances)

        last_error = "all instances failed"

        for instance_url in instances:
            url = f"{instance_url.rstrip('/')}/search"

            for attempt in range(1, 3):  # up to 2 attempts per instance
                try:
                    resp = requests.get(
                        url,
                        params={"q": query, "format": "json", "language": "en"},
                        headers={"User-Agent": _USER_AGENT},
                        timeout=_PER_REQUEST_TIMEOUT,
                    )

                    if resp.status_code == 429:
                        logger.warning(f"429 from {instance_url} — skipping")
                        last_error = f"rate limited by {instance_url}"
                        break  # next instance

                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", [])[:max_results]

                    if not results:
                        logger.info(f"No results from {instance_url}")
                        last_error = f"no results from {instance_url}"
                        break  # next instance (same query won't produce results)

                    return self._format_results(results)

                except requests.exceptions.Timeout:
                    logger.warning(f"{instance_url} timeout (attempt {attempt})")
                    last_error = f"timeout from {instance_url}"
                except Exception as e:
                    logger.warning(f"{instance_url} error: {e}")
                    last_error = str(e)
                    break  # non-retryable, next instance

        logger.error(f"All search instances failed for: {query!r}")
        return f"Search failed: {last_error}"

    def _format_results(self, results: list) -> str:
        """Format search results as a compact numbered list with URLs."""
        lines = ["Top results:"]
        total = len(lines[0])

        for i, result in enumerate(results, 1):
            title = result.get("title", "").strip()
            snippet = result.get("content", "").strip()
            result_url = result.get("url", "").strip()
            entry = f"{i}. {title} — {snippet}"
            if result_url:
                entry += f" ({result_url})"

            if total + len(entry) + 1 > _MAX_RESULT_CHARS:
                budget = _MAX_RESULT_CHARS - total - len(f"{i}. {title} — ") - 1
                if budget > 20:
                    entry = f"{i}. {title} — {snippet[:budget]}…"
                else:
                    break
            lines.append(entry)
            total += len(entry) + 1

        return "\n".join(lines)
