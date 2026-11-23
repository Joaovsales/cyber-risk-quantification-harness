"""Optional Tavily web search: the only module in the package that opens a network connection.

Nothing is written to disk and the API key never appears in an error message.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any, Literal, TypedDict

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 60.0


class SearchHit(TypedDict):
    title: str
    url: str
    content: str
    score: float | None


class SearchResult(TypedDict):
    query: str
    results: list[SearchHit]
    answer: str | None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would re-send the Authorization header to the new host."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class SearchError(Exception):
    """HTTP, timeout or JSON fault; the message is plain text and never holds the key."""


def _hits(raw: dict[str, Any]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for item in raw.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith("https://"):  # the report cites https sources only
            continue
        score = item.get("score")
        hits.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": url,
                "content": str(item.get("content") or "").strip(),
                "score": float(score) if isinstance(score, (int, float)) else None,
            }
        )
    return hits


def search(
    query: str,
    *,
    max_results: int = 5,
    depth: Literal["basic", "advanced"] = "basic",
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> SearchResult:
    """POST to Tavily and return the https results; raises :class:`SearchError` on any fault."""
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": depth,
        "include_answer": True,
    }
    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise SearchError(f"Tavily API returned HTTP {exc.code}") from None
    except TimeoutError:
        raise SearchError(f"Tavily API request timed out after {timeout:g} s") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, UnicodeDecodeError):
        raise SearchError("Tavily API request failed") from None

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        raise SearchError("Tavily API returned invalid JSON") from None
    if not isinstance(raw, dict):
        raise SearchError("Tavily API returned an unexpected JSON shape")

    answer = raw.get("answer")
    return {
        "query": query,
        "results": _hits(raw),
        "answer": answer if isinstance(answer, str) and answer.strip() else None,
    }
