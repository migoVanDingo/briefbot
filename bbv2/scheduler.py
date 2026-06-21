"""The `bbv2 tick` engine — decoupled, due-based data pulls.

Run frequently by cron (hourly). On each tick: discover new sources for topics
whose discovery cadence is due, collect from sources whose collection cadence is
due (per-source override ?? tightest topic interval ?? default), then quickscan
only the topics that got new items. Nothing runs unless it's due, so most ticks
are cheap. Briefs/emails are a *separate* job (`bbv2 nightly`).

The discover/collect/relevance callables are injectable so this is offline-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import requests

from . import config
from .collect import _empty_stats, collect_source
from .store import Store
from .usage import SYSTEM_USER_ID, metered_relevance_generate


def _due(last_iso: str | None, interval_min: int, now: datetime) -> bool:
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= interval_min * 60


def tick(
    store: Store,
    *,
    now: datetime | None = None,
    discover_fn: Callable[[Store, str], Any] | None = None,
    collect_one: Callable[..., set] | None = None,
    relevance_generate: Callable[..., str] | None = None,
) -> dict[str, int]:
    """One scheduler tick. Returns aggregate stats."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    default_discover = config.default_discover_interval_min()
    default_collect = config.default_collect_interval_min()
    timeout = config.http_timeout()
    session = requests.Session()
    collect_one = collect_one or collect_source
    if relevance_generate is None:
        relevance_generate = metered_relevance_generate(store, SYSTEM_USER_ID, "relevance")

    stats: dict[str, int] = {"discovered": 0, "discover_errors": 0, **_empty_stats()}

    # 1) Source discovery — per topic, when due.
    topics = store.topics_for_scheduler()
    id_to_slug = {int(t["id"]): t["slug"] for t in topics}
    for t in topics:
        interval = t["discover_interval_min"] or default_discover
        if not _due(t["last_discovered_at"], interval, now):
            continue
        try:
            if discover_fn:
                discover_fn(store, t["slug"])
            else:
                from .discovery import discover_sources

                discover_sources(store, t["slug"])
            stats["discovered"] += 1
        except Exception as exc:  # best-effort
            stats["discover_errors"] += 1
            print(f"[tick] discover failed for {t['slug']}: {exc}")
        store.set_topic_discovered(t["slug"], now_iso)

    # 2) Story collection — per source, when due.
    touched_ids: set[int] = set()
    for s in store.sources_for_scheduler():
        interval = s["eff_interval"] or default_collect
        if not _due(s["last_collected_at"], interval, now):
            continue
        touched_ids.update(collect_one(store, s, session, timeout, stats))
        store.set_source_collected(s["id"], now_iso)

    # 3) Relevance quickscan — only topics that got new items.
    from .review import quickscan_topic

    slugs = [id_to_slug[tid] for tid in touched_ids if tid in id_to_slug]
    for slug in slugs:
        try:
            quickscan_topic(store, slug, generate=relevance_generate)
        except Exception as exc:
            print(f"[tick] quickscan failed for {slug}: {exc}")
    stats["reviewed_topics"] = len(slugs)
    return stats
