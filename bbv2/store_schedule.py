"""Scheduling + cadence queries for the bbv2 `Store`.

Mixed into `Store` (see store.py). Drives the `bbv2 tick` engine: which sources
are due to collect (per-source interval, falling back to the *tightest* of their
topics' intervals) and which topics are due to discover new sources, plus the
admin cadence setters and the nightly brief's "topics with subscribers" query.
"""

from __future__ import annotations

import sqlite3

from .util import utc_now_iso


class SchedulerQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    # ---- read: what's due ----
    def sources_for_scheduler(self) -> list[sqlite3.Row]:
        """Active sources with an `eff_interval` = per-source override ?? tightest
        (smallest) of their topics' `collect_interval_min` ?? NULL (caller defaults)."""
        return self.conn.execute(
            """SELECT s.id, s.type, s.url, s.name, s.weight, s.tags_json, s.status,
                      s.collect_interval_min, s.last_collected_at,
                      COALESCE(s.collect_interval_min, MIN(t.collect_interval_min))
                        AS eff_interval
               FROM sources s
               JOIN topic_sources ts ON ts.source_id = s.id
               JOIN topics t ON t.id = ts.topic_id
               WHERE s.status = 'active'
               GROUP BY s.id""",
        ).fetchall()

    def topics_for_scheduler(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT id, slug, name, description, discover_interval_min,
                      collect_interval_min, last_discovered_at, last_briefed_at
               FROM topics""",
        ).fetchall()

    def topics_with_subscribers(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT DISTINCT t.* FROM topics t
               JOIN subscriptions s ON s.topic_id = t.id
               ORDER BY t.slug""",
        ).fetchall()

    # ---- write: checkpoints ----
    def set_source_collected(self, source_id: int, when_iso: str | None = None) -> None:
        self.conn.execute(
            "UPDATE sources SET last_collected_at = ? WHERE id = ?",
            (when_iso or utc_now_iso(), source_id),
        )
        self.conn.commit()

    def set_topic_discovered(self, slug: str, when_iso: str | None = None) -> None:
        self.conn.execute(
            "UPDATE topics SET last_discovered_at = ? WHERE slug = ?",
            (when_iso or utc_now_iso(), slug),
        )
        self.conn.commit()

    def set_topic_briefed(self, slug: str, when_iso: str | None = None) -> None:
        self.conn.execute(
            "UPDATE topics SET last_briefed_at = ? WHERE slug = ?",
            (when_iso or utc_now_iso(), slug),
        )
        self.conn.commit()

    # ---- write: admin cadence ----
    def set_topic_cadence(
        self,
        slug: str,
        *,
        discover_interval_min: int | None = None,
        collect_interval_min: int | None = None,
    ) -> None:
        """Set a topic's cadences. A value of 0 clears the override (→ default)."""
        self.conn.execute(
            """UPDATE topics
               SET discover_interval_min = ?, collect_interval_min = ?
               WHERE slug = ?""",
            (
                _norm(discover_interval_min),
                _norm(collect_interval_min),
                slug,
            ),
        )
        self.conn.commit()

    def set_source_cadence(self, source_id: int, collect_interval_min: int | None) -> None:
        self.conn.execute(
            "UPDATE sources SET collect_interval_min = ? WHERE id = ?",
            (_norm(collect_interval_min), source_id),
        )
        self.conn.commit()


def _norm(v: int | None) -> int | None:
    """Treat None / 0 / negatives as 'no override' (NULL)."""
    if v is None:
        return None
    iv = int(v)
    return iv if iv > 0 else None
