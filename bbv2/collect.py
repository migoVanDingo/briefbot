"""The collect pipeline: fetch active sources → normalize → dedupe → score →
store → map items to their source's topic(s)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from . import config
from .config import http_timeout
from .discover import discover_site_feeds
from .fetch import FetchError, fetch_rss_feed
from .score import compute_score, parse_iso_utc
from .store import Store

log = logging.getLogger("bbv2.collect")


def _published_dt(item: dict[str, Any]) -> datetime | None:
    return parse_iso_utc(item.get("published_at") or item.get("fetched_at"))


def _fresh_newest_first(items: list[dict[str, Any]], max_age_days: int) -> list[dict[str, Any]]:
    """Sort items newest-first (feed order is NOT guaranteed newest) and drop any
    older than the cutoff. Undated items can't be proven stale, so they're kept
    and sorted last."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
        if max_age_days > 0
        else None
    )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    kept: list[tuple[datetime, dict[str, Any]]] = []
    for it in items:
        dt = _published_dt(it)
        if cutoff is not None and dt is not None and dt < cutoff:
            continue
        kept.append((dt or floor, it))
    kept.sort(key=lambda p: p[0], reverse=True)
    return [it for _, it in kept]


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
        log.warning("discover failed for %s: %s", row["name"], exc)
        return set()

    touched: set[int] = set()
    max_age = config.collect_max_age_days()
    # Per-topic story cap (0020): the scheduler precomputes `eff_max_stories`; the
    # direct collect() path resolves it per source; fall back to the env default.
    eff_cap = row["eff_max_stories"] if "eff_max_stories" in row.keys() else None
    if eff_cap is None:
        eff_cap = store.source_max_stories(row["id"])
    remaining = eff_cap or config.max_stories_per_source()  # newest-first cap
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
            log.warning("fetch failed: %s", exc)
            continue
        if status == "not_modified":
            stats["not_modified"] += 1
            continue
        # Sort newest-first and drop stale entries before applying the per-source cap.
        items = _fresh_newest_first(items, max_age)
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
                log.warning("item failed (%s): %s", src["name"], exc)
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
