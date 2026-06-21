"""Slim, generic item scoring: recency x source weight.

Intentionally topic-agnostic (unlike the original briefbot's tech-keyword
scoring). Refine per-topic later if needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dtparser

# Items younger than this get a recency boost that decays to zero at the window.
RECENCY_WINDOW_HOURS = 72.0


def parse_iso_utc(iso_ts: str | None) -> datetime | None:
    """Parse an ISO timestamp into an aware UTC datetime, or None if unparseable.
    Shared by recency scoring and the collect staleness cutoff."""
    if not iso_ts:
        return None
    try:
        dt = dtparser.parse(iso_ts)
    except (TypeError, ValueError, OverflowError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _age_hours(iso_ts: str | None) -> float:
    dt = parse_iso_utc(iso_ts)
    if dt is None:
        return 9999.0
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def compute_score(item: dict[str, Any], source_weight: float = 1.0) -> float:
    """Base 1.0 + linear recency decay over RECENCY_WINDOW_HOURS, x source weight."""
    age = _age_hours(item.get("published_at") or item.get("fetched_at"))
    recency = 0.0
    if age <= RECENCY_WINDOW_HOURS:
        recency = (RECENCY_WINDOW_HOURS - age) / RECENCY_WINDOW_HOURS * 2.0
    score = (1.0 + recency) * max(0.1, float(source_weight or 1.0))
    return round(max(0.0, score), 4)
