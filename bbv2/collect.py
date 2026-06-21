"""The collect pipeline: fetch active sources → normalize → dedupe → score →
store → map items to their source's topic(s)."""

from __future__ import annotations

import json
from typing import Any

import requests

from . import config
from .config import http_timeout
from .discover import discover_site_feeds
from .fetch import FetchError, fetch_rss_feed
from .score import compute_score
from .store import Store


def _resolve_feed_urls(
    row: Any, store: Store, session: requests.Session, timeout: int
) -> list[str]:
    """Map a source row to one or more feed URLs to fetch."""
    if row["type"] == "rss":
        return [row["url"]]
    if row["type"] == "site":
        cached = store.get_discovered_feeds(row["url"])
        if cached is not None:
            return cached
        feeds = discover_site_feeds(row["url"], timeout=timeout, session=session)
        store.set_discovered_feeds(row["url"], feeds)
        return feeds
    # hn/arxiv deferred to a later phase.
    return []


def _empty_stats() -> dict[str, int]:
    return {"sources": 0, "feeds": 0, "items": 0, "new": 0, "not_modified": 0, "errors": 0}


def collect_source(
    store: Store,
    row: Any,
    session: requests.Session,
    timeout: int,
    stats: dict[str, int],
) -> set[int]:
    """Collect one source into `stats` (mutated). Returns the topic ids it mapped
    items into — used by the scheduler to quickscan only what changed."""
    stats["sources"] += 1
    src = {
        "id": str(row["id"]),
        "name": row["name"],
        "tags": json.loads(row["tags_json"] or "[]"),
    }
    topic_ids = store.source_topic_ids(row["id"])
    try:
        feed_urls = _resolve_feed_urls(row, store, session, timeout)
    except Exception as exc:  # discovery is best-effort
        stats["errors"] += 1
        print(f"[collect] discover failed for {row['name']}: {exc}")
        return set()

    touched: set[int] = set()
    remaining = config.max_stories_per_source()  # newest-first cap per source
    for feed_url in feed_urls:
        if remaining <= 0:
            break
        stats["feeds"] += 1
        try:
            items, status = fetch_rss_feed(
                src, feed_url, store, session=session, timeout=timeout
            )
        except FetchError as exc:
            stats["errors"] += 1
            print(f"[collect] fetch failed: {exc}")
            continue
        if status == "not_modified":
            stats["not_modified"] += 1
            continue
        for item in items[:remaining]:
            # One bad item / transient DB hiccup must not sink the whole topic.
            try:
                item["score"] = compute_score(item, source_weight=row["weight"])
                item_id, inserted = store.upsert_item(item)
                for tid in topic_ids:
                    store.map_item_topic(item_id, tid)
                    touched.add(tid)
                stats["items"] += 1
                remaining -= 1
                if inserted:
                    stats["new"] += 1
            except Exception as exc:  # noqa: BLE001 - best-effort per item
                stats["errors"] += 1
                print(f"[collect] item failed ({src['name']}): {exc}")
    return touched


def collect(
    store: Store, topic_slug: str | None = None, timeout: int | None = None
) -> dict[str, int]:
    timeout = timeout or http_timeout()
    session = requests.Session()
    stats = _empty_stats()
    for row in store.active_sources(topic_slug):
        collect_source(store, row, session, timeout, stats)
    return stats
