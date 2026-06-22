"""Dashboard query methods for the bbv2 `Store`.

Split out of `store.py` to keep that file focused (schema + core ingest/consumer
queries). These methods are mixed into `Store` and operate on `self.conn`:
the Stories browser (search/feedback) and the daily briefs.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .util import json_dumps, utc_now_iso


class DashboardQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    # ---- relevance quickscan (LLM review of item↔topic mappings) ----
    def pending_relevance(self, topic_slug: str, limit: int = 200) -> list[sqlite3.Row]:
        """Items mapped to the topic but not yet relevance-reviewed."""
        return self.conn.execute(
            """SELECT i.item_id, i.title, i.summary FROM items i
               JOIN item_topics it ON it.item_id = i.item_id
               JOIN topics t ON t.id = it.topic_id
               WHERE t.slug = ? AND it.relevant IS NULL
               ORDER BY i.fetched_at DESC LIMIT ?""",
            (topic_slug, limit),
        ).fetchall()

    def set_item_relevance(self, item_id: str, topic_id: int, relevant: int) -> None:
        self.conn.execute(
            "UPDATE item_topics SET relevant = ? WHERE item_id = ? AND topic_id = ?",
            (relevant, item_id, topic_id),
        )
        self.conn.commit()

    # ---- provisioning helpers ----
    def approve_all_candidates(self, topic_slug: str) -> int:
        """Auto-approve every candidate source on a topic (candidate→active).
        Returns how many were flipped."""
        cur = self.conn.execute(
            """UPDATE sources SET status='active'
               WHERE status='candidate' AND id IN (
                 SELECT s.id FROM sources s
                 JOIN topic_sources ts ON ts.source_id = s.id
                 JOIN topics t ON t.id = ts.topic_id
                 WHERE t.slug = ?)""",
            (topic_slug,),
        )
        self.conn.commit()
        return cur.rowcount

    def topic_has_sources(self, topic_slug: str) -> bool:
        row = self.conn.execute(
            """SELECT 1 FROM sources s
               JOIN topic_sources ts ON ts.source_id = s.id
               JOIN topics t ON t.id = ts.topic_id
               WHERE t.slug = ? AND s.status = 'active' LIMIT 1""",
            (topic_slug,),
        ).fetchone()
        return row is not None

    # ---- stories (dashboard browser) ----
    def story_sources(self, user_id: int) -> list[str]:
        """Distinct source names across the user's subscribed topics."""
        rows = self.conn.execute(
            """SELECT DISTINCT i.source_name FROM items i
               JOIN item_topics it ON it.item_id = i.item_id
               JOIN subscriptions sub ON sub.topic_id = it.topic_id
               WHERE sub.user_id = ?
               ORDER BY i.source_name COLLATE NOCASE""",
            (user_id,),
        ).fetchall()
        return [r["source_name"] for r in rows]

    def query_stories(
        self,
        user_id: int,
        *,
        search: str | None = None,
        source_name: str | None = None,
        topic_slug: str | None = None,
        from_iso: str | None = None,
        to_iso: str | None = None,
        order: str = "desc",
        limit: int = 30,
    ) -> list[sqlite3.Row]:
        """Filtered story browse across the user's subscriptions, with the user's
        own feedback vote joined in. Newest-first by default."""
        order_sql = "ASC" if str(order).lower() == "asc" else "DESC"
        sql = [
            "SELECT DISTINCT i.*, f.vote AS feedback_vote",
            "FROM items i",
            "JOIN item_topics it ON it.item_id = i.item_id",
            "JOIN subscriptions sub ON sub.topic_id = it.topic_id",
            "LEFT JOIN story_feedback f ON f.item_id = i.item_id AND f.user_id = ?",
            "WHERE sub.user_id = ?",
            "AND COALESCE(it.relevant, 1) = 1",
        ]
        params: list[Any] = [user_id, user_id]
        if topic_slug:
            sql.append("AND it.topic_id = (SELECT id FROM topics WHERE slug = ?)")
            params.append(topic_slug)
        if source_name:
            sql.append("AND i.source_name = ?")
            params.append(source_name)
        if search:
            # Token AND: every word must appear (title/summary/source), in any
            # order — so "Israeli airstrike Sidon" matches "Israeli airstrike near
            # Sidon …". Fixes the chat agent's search + Stories search.
            for tok in search.split()[:8]:
                like = f"%{tok}%"
                sql.append("AND (i.title LIKE ? OR i.summary LIKE ? OR i.source_name LIKE ?)")
                params.extend([like, like, like])
        if from_iso:
            sql.append("AND COALESCE(i.published_at, i.fetched_at) >= ?")
            params.append(from_iso)
        if to_iso:
            sql.append("AND COALESCE(i.published_at, i.fetched_at) <= ?")
            params.append(to_iso)
        sql.append(
            f"ORDER BY COALESCE(i.published_at, i.fetched_at) {order_sql}, "
            "i.title COLLATE NOCASE"
        )
        sql.append("LIMIT ?")
        params.append(limit)
        return self.conn.execute(" ".join(sql), params).fetchall()

    def set_story_feedback(self, user_id: int, item_id: str, vote: int) -> None:
        """Upsert the user's vote (-1/0/1) on a story."""
        self.conn.execute(
            """INSERT INTO story_feedback (user_id, item_id, vote, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, item_id) DO UPDATE SET
                 vote=excluded.vote, updated_at=excluded.updated_at""",
            (user_id, item_id, int(vote), utc_now_iso()),
        )
        self.conn.commit()

    # ---- briefs (daily summaries) ----
    def upsert_brief(self, brief: dict[str, Any]) -> None:
        """Insert/replace a topic's brief for a date (UNIQUE on topic_id+date)."""
        self.conn.execute(
            """INSERT INTO briefs
               (id, topic_id, date, title, summary, trending_json, sources_json,
                model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(topic_id, date) DO UPDATE SET
                 title=excluded.title, summary=excluded.summary,
                 trending_json=excluded.trending_json,
                 sources_json=excluded.sources_json,
                 model=excluded.model, created_at=excluded.created_at""",
            (
                brief["id"],
                int(brief["topic_id"]),
                brief["date"],
                brief["title"],
                brief["summary"],
                json_dumps(brief.get("trending") or []),
                json_dumps(brief.get("sources") or []),
                brief.get("model"),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def get_brief(self, topic_id: int, date: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM briefs WHERE topic_id = ? AND date = ?", (topic_id, date)
        ).fetchone()

    def latest_brief(self, topic_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM briefs WHERE topic_id = ? ORDER BY date DESC LIMIT 1",
            (topic_id,),
        ).fetchone()

    def recent_briefs(self, topic_id: int, limit: int = 10) -> list[sqlite3.Row]:
        """The most recent briefs for a topic, newest first (days that actually have
        a brief). Backs the Headlines date rail."""
        return self.conn.execute(
            "SELECT * FROM briefs WHERE topic_id = ? ORDER BY date DESC LIMIT ?",
            (topic_id, limit),
        ).fetchall()

