"""The collect pipeline: fetch active sources → normalize → dedupe → score →
store → map items to their source's topic(s)."""

from __future__ import annotations

import json
from typing import Any

import requests

from .config import http_timeout, relevance_enabled, relevance_min_hits
from .discover import discover_site_feeds
from .fetch import FetchError, fetch_rss_feed
from .relevance import expand_keywords, is_relevant, keyword_tokens
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


def collect(
    store: Store, topic_slug: str | None = None, timeout: int | None = None
) -> dict[str, int]:
    timeout = timeout or http_timeout()
    session = requests.Session()
    stats = {
        "sources": 0,
        "feeds": 0,
        "items": 0,
        "new": 0,
        "not_modified": 0,
        "errors": 0,
        "filtered": 0,
    }

    # Per-topic keyword sets for relevance filtering (lazy-generate missing ones).
    relevance_on = relevance_enabled()
    min_hits = relevance_min_hits()
    kw_by_id: dict[int, set[str]] = {}
    if relevance_on:
        for t in store.list_topics():
            expanded = store.get_topic_keywords(t["slug"])
            if not expanded:
                expanded = expand_keywords(t["name"])
                if expanded:
                    store.set_topic_keywords(t["slug"], expanded)
            kw_by_id[int(t["id"])] = keyword_tokens(
                t["name"], t["description"] or "", expanded
            )

    for row in store.active_sources(topic_slug):
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
            continue

        for feed_url in feed_urls:
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
            for item in items:
                item["score"] = compute_score(item, source_weight=row["weight"])
                # Keep the item only for the topics it's actually relevant to.
                if relevance_on:
                    rel_tids = [
                        tid
                        for tid in topic_ids
                        if is_relevant(
                            item["title"],
                            item.get("summary"),
                            kw_by_id.get(tid, set()),
                            min_hits,
                        )
                    ]
                else:
                    rel_tids = topic_ids
                if not rel_tids:
                    stats["filtered"] += 1
                    continue
                item_id, inserted = store.upsert_item(item)
                for tid in rel_tids:
                    store.map_item_topic(item_id, tid)
                stats["items"] += 1
                if inserted:
                    stats["new"] += 1

    return stats
