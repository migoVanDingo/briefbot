"""The `bbv2 tick` engine — decoupled, due-based data pulls.

Run frequently by cron (hourly). On each tick: discover new sources for topics
whose discovery cadence is due, collect from sources whose collection cadence is
due (per-source override ?? tightest topic interval ?? default), then quickscan
only the topics that got new items. Nothing runs unless it's due, so most ticks
are cheap. Briefs/emails are a *separate* job (`bbv2 nightly`).

The discover/collect/relevance callables are injectable so this is offline-testable.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

import requests

from . import config
from .collect import _empty_stats, collect_source
from .store import Store
from .usage import SYSTEM_USER_ID, metered_relevance_generate

log = logging.getLogger("bbv2.scheduler")


def _due(last_iso: str | None, interval_min: int, now: datetime) -> bool:
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= interval_min * 60


def _ran_today(last_iso: str | None, now: datetime) -> bool:
    if not last_iso:
        return False
    try:
        return datetime.fromisoformat(last_iso).date() == now.date()
    except (TypeError, ValueError):
        return False


def _clamp_day(day: int, year: int, month: int) -> int:
    """Clamp a day-of-month to the month's length (e.g. the 31st in Feb → 28/29)."""
    return min(day, calendar.monthrange(year, month)[1])


def _period_matches(period: str, start: date, now: datetime) -> bool:
    """Does today match the recurrence anchored at `start`? day=always, week=same
    weekday, month=same day-of-month (clamped), year=same month+day (clamped)."""
    if period == "day":
        return True
    if period == "week":
        return now.weekday() == start.weekday()
    if period == "month":
        return now.day == _clamp_day(start.day, now.year, now.month)
    if period == "year":
        return now.month == start.month and now.day == _clamp_day(start.day, now.year, start.month)
    return False


def _discover_due(
    topic: Any, now: datetime, window_min: int, default_interval: int
) -> bool:
    """Schedule-aware due check for a topic's discovery (0020): "run every <period>
    starting <date> at <time>". Fires once when `now` is on/after the start date, on
    a matching period day, inside the [at, at+window) time slot, and it hasn't
    already run today. Unconfigured topics (no period) use the env default interval."""
    period = topic["discover_period"] if "discover_period" in topic.keys() else None
    start_raw = topic["discover_start_date"] if "discover_start_date" in topic.keys() else None
    if period and start_raw:
        try:
            start = date.fromisoformat(start_raw)
        except (TypeError, ValueError):
            return _due(topic["last_discovered_at"], default_interval, now)
        if now.date() < start:
            return False  # hasn't started yet
        at_min = int(topic["discover_at_min"] or 0)
        now_min = now.hour * 60 + now.minute
        if not (at_min <= now_min < at_min + window_min):
            return False
        if not _period_matches(period, start, now):
            return False
        return not _ran_today(topic["last_discovered_at"], now)
    interval = topic["discover_interval_min"] or default_interval
    return _due(topic["last_discovered_at"], interval, now)


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
    window = config.scheduler_window_min()
    timeout = config.http_timeout()
    session = requests.Session()
    collect_one = collect_one or collect_source
    # When not injected (tests), the quickscan generator is built per-topic below
    # so its Grok spend is attributed to that topic (metrics, 0021).
    provided_relevance = relevance_generate is not None

    stats: dict[str, int] = {"discovered": 0, "discover_errors": 0, **_empty_stats()}

    # 1) Source discovery — per topic, when due.
    topics = store.topics_for_scheduler()
    id_to_slug = {int(t["id"]): t["slug"] for t in topics}
    for t in topics:
        if not _discover_due(t, now, window, default_discover):
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
            log.warning("discover failed for %s: %s", t["slug"], exc)
        store.set_topic_discovered(t["slug"], now_iso)

    # 2) Story collection — per source, when due.
    touched_ids: set[int] = set()
    for s in store.sources_for_scheduler():
        interval = s["eff_interval"] or default_collect
        if not _due(s["last_collected_at"], interval, now):
            continue
        touched_ids.update(collect_one(store, s, session, timeout, stats))
        store.set_source_collected(s["id"], now_iso)

    # 3) Relevance quickscan — only topics that got new items (Grok, per-topic).
    from .review import quickscan_topic

    reviewed = 0
    for tid in touched_ids:
        slug = id_to_slug.get(tid)
        if not slug:
            continue
        gen = (
            relevance_generate
            if provided_relevance
            else metered_relevance_generate(store, SYSTEM_USER_ID, "relevance", topic_id=tid)
        )
        try:
            quickscan_topic(store, slug, generate=gen)
            reviewed += 1
        except Exception as exc:
            log.warning("quickscan failed for %s: %s", slug, exc)
    stats["reviewed_topics"] = reviewed
    return stats
