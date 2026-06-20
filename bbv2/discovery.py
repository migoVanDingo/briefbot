"""Agent source discovery: topic → Brave search → candidate feeds.

Search and feed-resolution are injectable callables so this is unit-testable
offline. v1 uses heuristic queries; an LLM query-crafter/ranker can slot in
behind the same interface later.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .brave import DiscoveryError, brave_search
from .config import http_timeout
from .denylist import is_blocked_domain
from .discover import discover_site_feeds
from .store import Store

Searcher = Callable[[str, int], list[dict[str, Any]]]
FeedFinder = Callable[[str], list[str]]


def build_queries(name: str, description: str = "") -> list[str]:
    base = name.strip()
    queries = [
        f"{base} news",
        f"{base} rss feed",
        f"best {base} blogs",
        f"{base} analysis",
    ]
    if description.strip():
        queries.append(f"{description.strip()} news")
    return queries


def _homepage(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


def discover_sources(
    store: Store,
    topic_slug: str,
    *,
    searcher: Searcher | None = None,
    feed_finder: FeedFinder | None = None,
    per_query: int = 8,
    max_candidates: int = 20,
    max_feeds_per_site: int = 2,
) -> dict[str, Any]:
    """Search for sources for a topic and store new candidate feeds.
    Returns stats + the list of added candidate feed URLs."""
    topic = store.get_topic(topic_slug)
    if not topic:
        raise DiscoveryError(f"unknown topic '{topic_slug}'")

    session = requests.Session()
    search = searcher or (lambda q, n: brave_search(q, count=n, session=session))
    find_feeds = feed_finder or (
        lambda site: discover_site_feeds(site, timeout=http_timeout(), session=session)
    )

    topic_id = int(topic["id"])
    existing = store.source_urls()
    seen_homepages: set[str] = set()
    added: list[str] = []
    stats = {"queries": 0, "results": 0, "homepages": 0, "candidates": 0, "errors": 0}

    for query in build_queries(topic["name"], topic["description"] or ""):
        if len(added) >= max_candidates:
            break
        stats["queries"] += 1
        try:
            results = search(query, per_query)
        except DiscoveryError:
            stats["errors"] += 1
            continue
        stats["results"] += len(results)

        for result in results:
            if len(added) >= max_candidates:
                break
            homepage = _homepage(result.get("url") or "")
            if not homepage or homepage in seen_homepages:
                continue
            if is_blocked_domain(homepage):  # never add sketchy domains as sources
                continue
            seen_homepages.add(homepage)
            stats["homepages"] += 1
            try:
                feeds = find_feeds(homepage)
            except Exception:  # discovery is best-effort
                stats["errors"] += 1
                continue
            for feed_url in feeds[:max_feeds_per_site]:
                if feed_url in existing or len(added) >= max_candidates:
                    continue
                name = result.get("title") or urlparse(homepage).netloc
                sid = store.add_source(
                    type="rss",
                    url=feed_url,
                    name=name,
                    status="candidate",
                    discovered_by="brave",
                )
                store.link_topic_source(topic_id, sid)
                existing.add(feed_url)
                added.append(feed_url)
                stats["candidates"] += 1

    return {**stats, "added": added}
