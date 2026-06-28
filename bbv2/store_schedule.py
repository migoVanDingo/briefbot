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
        (smallest) of their topics' `collect_interval_min` ?? NULL (caller defaults),
        and `eff_max_stories` = most-permissive (max) per-topic story cap (0020)."""
        return self.conn.execute(
            """SELECT s.id, s.type, s.url, s.name, s.weight, s.tags_json, s.status,
                      s.collect_interval_min, s.last_collected_at,
                      COALESCE(s.collect_interval_min, MIN(t.collect_interval_min))
                        AS eff_interval,
                      MAX(t.max_stories_per_source) AS eff_max_stories
               FROM sources s
               JOIN topic_sources ts ON ts.source_id = s.id
               JOIN topics t ON t.id = ts.topic_id
               WHERE s.status = 'active'
               GROUP BY s.id""",
        ).fetchall()

    def source_max_stories(self, source_id: int) -> int | None:
        """Most-permissive per-topic story cap across a source's topics, or None
        (caller falls back to the env default). Used by the direct `collect()` path
        where the row has no precomputed `eff_max_stories`."""
        row = self.conn.execute(
            """SELECT MAX(t.max_stories_per_source) AS m
               FROM topic_sources ts JOIN topics t ON t.id = ts.topic_id
               WHERE ts.source_id = ?""",
            (source_id,),
        ).fetchone()
        return row["m"] if row else None

    def topics_for_scheduler(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT id, slug, name, description, discover_interval_min,
                      collect_interval_min, last_discovered_at, last_briefed_at,
                      discover_period, discover_start_date, discover_at_min,
                      max_sources, max_stories_per_source
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

    # ---- write: admin schedule + caps (0020) ----
    def set_topic_schedule(
        self,
        slug: str,
        *,
        discover_period: str | None = None,
        discover_start_date: str | None = None,
        discover_at_min: int | None = None,
        collect_interval_min: int | None = None,
        max_sources: int | None = None,
        max_stories_per_source: int | None = None,
    ) -> None:
        """Update only the fields passed (None = leave unchanged). An empty/invalid
        period or start date clears it (→ default interval); caps use the -1/0
        sentinel to clear; `discover_at_min` accepts -1 to clear."""
        sets: list[str] = []
        params: list = []
        if discover_period is not None:
            sets.append("discover_period = ?")
            params.append(discover_period if discover_period in _PERIODS else None)
        if discover_start_date is not None:
            sets.append("discover_start_date = ?")
            params.append(discover_start_date or None)  # "" → NULL
        if discover_at_min is not None:
            sets.append("discover_at_min = ?")
            params.append(_clear(discover_at_min))
        if collect_interval_min is not None:
            sets.append("collect_interval_min = ?")
            params.append(_norm(collect_interval_min))
        if max_sources is not None:
            sets.append("max_sources = ?")
            params.append(_norm(max_sources))  # caps must be > 0, else default
        if max_stories_per_source is not None:
            sets.append("max_stories_per_source = ?")
            params.append(_norm(max_stories_per_source))
        if not sets:
            return
        params.append(slug)
        self.conn.execute(
            f"UPDATE topics SET {', '.join(sets)} WHERE slug = ?", params
        )
        self.conn.commit()

    _RESET_SQL = (
        "discover_period=NULL, discover_start_date=NULL, discover_at_min=NULL, "
        "discover_interval_min=NULL, collect_interval_min=NULL, "
        "max_sources=NULL, max_stories_per_source=NULL"
    )

    def reset_topic_schedule(self, slug: str) -> None:
        """Drop a topic back to env defaults (interval discovery + NULL caps)."""
        self.conn.execute(
            f"UPDATE topics SET {self._RESET_SQL} WHERE slug = ?", (slug,)
        )
        self.conn.commit()

    def reset_all_schedules(self) -> int:
        """Reset every topic to env defaults. Returns the row count."""
        cur = self.conn.execute(f"UPDATE topics SET {self._RESET_SQL}")
        self.conn.commit()
        return cur.rowcount


_PERIODS = {"day", "week", "month", "year"}


def _norm(v: int | None) -> int | None:
    """Treat None / 0 / negatives as 'no override' (NULL)."""
    if v is None:
        return None
    iv = int(v)
    return iv if iv > 0 else None


def _clear(v: int | None) -> int | None:
    """Like `_norm` but 0 is a valid value (e.g. midnight, weekday Monday); only
    None / negative clears to NULL (the -1 sentinel)."""
    if v is None:
        return None
    iv = int(v)
    return iv if iv >= 0 else None
