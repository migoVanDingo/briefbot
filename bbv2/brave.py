"""Brave Web Search API client (for agent source discovery).

Thin wrapper: one query → a list of {url, title} results. Auth via
`BRAVESEARCH_API_KEY`.
"""

from __future__ import annotations

from typing import Any

import requests

from .config import brave_api_key
from .httpclient import request_with_backoff

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class DiscoveryError(Exception):
    pass


def brave_search(
    query: str,
    count: int = 10,
    api_key: str | None = None,
    session: requests.Session | None = None,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    key = api_key or brave_api_key()
    if not key:
        raise DiscoveryError("BRAVESEARCH_API_KEY is not set")
    sess = session or requests.Session()
    try:
        resp = request_with_backoff(
            lambda: sess.get(
                BRAVE_ENDPOINT,
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
                timeout=timeout,
            )
        )
    except requests.RequestException as exc:
        raise DiscoveryError(f"Brave request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise DiscoveryError(f"Brave HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    results = (data.get("web") or {}).get("results") or []
    return [
        {"url": r.get("url"), "title": r.get("title")}
        for r in results
        if r.get("url")
    ]
