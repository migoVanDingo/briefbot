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
        ]
        params: list[Any] = [user_id, user_id]
        if source_name:
            sql.append("AND i.source_name = ?")
            params.append(source_name)
        if search:
            like = f"%{search}%"
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
