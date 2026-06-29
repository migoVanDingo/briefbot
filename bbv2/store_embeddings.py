"""Topic embedding index queries for the bbv2 `Store` (0030).

Stores one vector per (topic, day) from that day's brief + one 'meta' vector per
topic from its name+description, and exposes the centroid used for routing. Vectors
are packed float32 BLOBs; cosine/centroid math lives in `embeddings.py`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .util import utc_now_iso

META = "meta"
BRIEF = "brief"


class EmbeddingQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    def upsert_topic_embedding(
        self, topic_id: int, kind: str, date: str, model: str, vector: list[float]
    ) -> None:
        from .embeddings import pack_vector

        self.conn.execute(
            """INSERT INTO topic_embeddings (topic_id, kind, date, model, dim, vector, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(topic_id, kind, date) DO UPDATE SET
                 model=excluded.model, dim=excluded.dim, vector=excluded.vector,
                 created_at=excluded.created_at""",
            (topic_id, kind, date, model, len(vector), pack_vector(vector), utc_now_iso()),
        )
        self.conn.commit()

    def _vectors(self, sql: str, params: tuple) -> list[list[float]]:
        from .embeddings import unpack_vector

        return [unpack_vector(r["vector"]) for r in self.conn.execute(sql, params).fetchall()]

    def topic_meta_vector(self, topic_id: int) -> list[float] | None:
        vs = self._vectors(
            "SELECT vector FROM topic_embeddings WHERE topic_id = ? AND kind = 'meta'",
            (topic_id,),
        )
        return vs[0] if vs else None

    def topic_centroid(self, topic_id: int, days: int) -> list[float] | None:
        """A topic's routing vector: centroid of its brief embeddings over the last
        `days`, else its 'meta' (name+description) vector, else None."""
        from .embeddings import centroid

        since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        vecs = self._vectors(
            "SELECT vector FROM topic_embeddings "
            "WHERE topic_id = ? AND kind = 'brief' AND date >= ? ORDER BY date DESC",
            (topic_id, since),
        )
        c = centroid(vecs)
        return c if c is not None else self.topic_meta_vector(topic_id)

    def briefs_missing_embedding(self, since_date: str) -> list[sqlite3.Row]:
        """Briefs (>= since_date) with no 'brief' embedding yet — the nightly sweep's
        worklist. Keyed off the briefs table, so it catches nightly + on-demand briefs."""
        return self.conn.execute(
            """SELECT b.topic_id AS topic_id, b.date AS date, b.summary AS summary
               FROM briefs b
               LEFT JOIN topic_embeddings e
                 ON e.topic_id = b.topic_id AND e.kind = 'brief' AND e.date = b.date
               WHERE b.date >= ? AND e.topic_id IS NULL
               ORDER BY b.date""",
            (since_date,),
        ).fetchall()

    def topics_missing_meta_embedding(self) -> list[sqlite3.Row]:
        """Topics with no 'meta' vector — for the floor (backfill / topic create)."""
        return self.conn.execute(
            """SELECT t.id AS id, t.slug AS slug, t.name AS name, t.description AS description
               FROM topics t
               LEFT JOIN topic_embeddings e ON e.topic_id = t.id AND e.kind = 'meta'
               WHERE e.topic_id IS NULL""",
        ).fetchall()

    def topics_with_any_embedding(self) -> list[sqlite3.Row]:
        """Topics that have at least one vector (brief or meta) — the routing pool."""
        return self.conn.execute(
            """SELECT DISTINCT t.id AS id, t.slug AS slug, t.name AS name,
                      t.description AS description
               FROM topics t JOIN topic_embeddings e ON e.topic_id = t.id
               ORDER BY t.name""",
        ).fetchall()
