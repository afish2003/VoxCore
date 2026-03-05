"""
WebSearch tool.

Uses the SearXNG JSON API to return real search result snippets.
Multiple SearXNG instances are tried with health-aware selection;
unhealthy instances are placed on a per-failure-type cooldown so they
are skipped on subsequent calls until they recover.

Instance selection order:
    1. Healthy instances, shuffled randomly.
    2. If all instances are on cooldown, the one whose cooldown expires
       soonest is tried as a least-bad fallback.

Output is structured JSON so the orchestrator can detect failures:
    Success: {"ok": true,  "query": "...", "results": [...]}
    Failure: {"ok": false, "query": "...", "error": "...", ...}

Query normalization:
    Speech recognition occasionally mishears domain-specific terms.
    A small alias table corrects the most common substitutions before the
    query is sent to the search engine.
"""
import json
import logging
import random
import re
import time

import requests

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)

_USER_AGENT = "VoxCore/1.0 (voice assistant; research)"
_MAX_RESULT_CHARS = 800

# Timeout tuple: (connect_timeout, read_timeout) in seconds
_CONNECT_TIMEOUT = 3
_READ_TIMEOUT = 8

# ---------------------------------------------------------------------------
# Per-failure-type cooldown durations (seconds)
# ---------------------------------------------------------------------------
_COOLDOWN_429_MIN = 300       # 5 min
_COOLDOWN_429_MAX = 900       # 15 min
_COOLDOWN_DNS = 600           # 10 min
_COOLDOWN_TIMEOUT_MIN = 60    # 1 min
_COOLDOWN_TIMEOUT_MAX = 120   # 2 min
_COOLDOWN_OTHER = 120         # 2 min

_DEFAULT_INSTANCES = [
    "http://127.0.0.1:8080",
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
        # Instance health: url -> monotonic timestamp when cooldown expires.
        # Persists for the lifetime of this object (i.e. the whole process).
        self._health: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Instance selection
    # ------------------------------------------------------------------

    def _select_instances(self) -> list[str]:
        """
        Return instances ordered for this request.

        Healthy instances (not on cooldown) come first, shuffled randomly
        to distribute load.  If all instances are on cooldown, the one
        whose cooldown expires soonest is returned as a least-bad fallback.
        """
        now = time.monotonic()
        healthy = []
        sick: list[tuple[float, str]] = []  # (expires_at, url)

        for url in self._instances:
            expires = self._health.get(url, 0.0)
            if now >= expires:
                healthy.append(url)
            else:
                sick.append((expires, url))

        if healthy:
            random.shuffle(healthy)
            return healthy

        # All instances on cooldown — try the one expiring soonest
        sick.sort()
        logger.warning("All search instances on cooldown — trying least-bad")
        return [url for _, url in sick]

    def _cooldown(self, url: str, seconds: float) -> None:
        """Place an instance on cooldown for the given duration."""
        self._health[url] = time.monotonic() + seconds
        logger.info(f"  {url} on cooldown for {seconds:.0f}s")

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, query: str, max_results: int = 3, **kwargs) -> str:
        query = _normalize_query(query)
        logger.info(f"Web search: {query!r}")

        instances = self._select_instances()
        attempted: list[str] = []
        last_error = "all instances failed"

        for instance_url in instances:
            attempted.append(instance_url)
            url = f"{instance_url.rstrip('/')}/search"

            for attempt in range(1, 3):  # up to 2 attempts per instance
                try:
                    resp = requests.get(
                        url,
                        params={"q": query, "format": "json", "language": "en"},
                        headers={"User-Agent": _USER_AGENT},
                        timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                    )

                    if resp.status_code == 429:
                        cd = random.uniform(_COOLDOWN_429_MIN, _COOLDOWN_429_MAX)
                        self._cooldown(instance_url, cd)
                        last_error = f"rate limited by {instance_url}"
                        break  # next instance

                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", [])[:max_results]

                    if not results:
                        logger.info(f"No results from {instance_url}")
                        last_error = f"no results from {instance_url}"
                        break  # next instance

                    return self._success(query, instance_url, results)

                except requests.exceptions.ConnectionError as e:
                    # DNS failures, refused connections, etc.
                    self._cooldown(instance_url, _COOLDOWN_DNS)
                    logger.warning(f"{instance_url} connection error: {e}")
                    last_error = f"connection error from {instance_url}"
                    break  # non-retryable, next instance

                except requests.exceptions.Timeout:
                    logger.warning(f"{instance_url} timeout (attempt {attempt})")
                    last_error = f"timeout from {instance_url}"
                    if attempt >= 2:
                        cd = random.uniform(
                            _COOLDOWN_TIMEOUT_MIN, _COOLDOWN_TIMEOUT_MAX
                        )
                        self._cooldown(instance_url, cd)

                except Exception as e:
                    self._cooldown(instance_url, _COOLDOWN_OTHER)
                    logger.warning(f"{instance_url} error: {e}")
                    last_error = str(e)
                    break  # non-retryable, next instance

        logger.error(f"All search instances failed for: {query!r}")
        return self._failure(query, attempted, last_error)

    # ------------------------------------------------------------------
    # Structured output helpers
    # ------------------------------------------------------------------

    def _success(self, query: str, instance: str, raw_results: list) -> str:
        """Build a structured JSON success response."""
        results = []
        total_chars = 0
        for r in raw_results:
            title = r.get("title", "").strip()
            snippet = r.get("content", "").strip()
            result_url = r.get("url", "").strip()
            entry = {"title": title, "snippet": snippet, "url": result_url}
            entry_len = len(title) + len(snippet) + len(result_url)
            if total_chars + entry_len > _MAX_RESULT_CHARS and results:
                break
            results.append(entry)
            total_chars += entry_len

        return json.dumps(
            {"ok": True, "query": query, "instance": instance, "results": results},
            ensure_ascii=False,
        )

    def _failure(self, query: str, attempted: list, last_error: str) -> str:
        """Build a structured JSON failure response."""
        return json.dumps(
            {
                "ok": False,
                "query": query,
                "error": "all_instances_failed",
                "attempted": attempted,
                "last_error": last_error,
            },
            ensure_ascii=False,
        )
