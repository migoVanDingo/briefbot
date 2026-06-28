"""SQLite persistence for bbv2 — topics, sources, items, and caches.

Schema is adapted from the original briefbot's `items`/cache tables, plus the
new topic model (topics, sources, topic_sources, item_topics). bbv2 owns this
database; it never opens the original briefbot's DB.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from .store_cache import CacheQueriesMixin
from .store_chat import ChatQueriesMixin
from .store_consumer import ConsumerTokenMixin
from .store_dashboard import DashboardQueriesMixin
from .store_favorites import FavoriteQueriesMixin
from .store_metrics import MetricsQueriesMixin
from .store_provision import ProvisionRunsMixin
from .store_schedule import SchedulerQueriesMixin
from .store_sessions import SessionQueriesMixin
from .store_spaces import SpaceQueriesMixin
from .schema import SCHEMA_SQL
from .store_usage import UsageQueriesMixin
from .store_users import UserQueriesMixin
from .util import ensure_dir, json_dumps, utc_now_iso


class Store(
    DashboardQueriesMixin,
    FavoriteQueriesMixin,
    ChatQueriesMixin,
    ConsumerTokenMixin,
    UsageQueriesMixin,
    SchedulerQueriesMixin,
    CacheQueriesMixin,
    UserQueriesMixin,
    SessionQueriesMixin,
    SpaceQueriesMixin,
    MetricsQueriesMixin,
    ProvisionRunsMixin,
):
    def __init__(self, db_path: str | Path, check_same_thread: bool = True) -> None:
        path = str(db_path)
        self._path = path
        self._is_memory = path == ":memory:"
        self._check_same_thread = check_same_thread
        self._local = threading.local()
        # Track every per-thread connection so `close_all()` (server shutdown) can
        # release them — otherwise each threadpool worker's connection lives for the
        # whole process. `_new_conn` registers here under the lock.
        self._all_conns: list[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        # The API serves requests on a threadpool. A single shared sqlite connection
        # is NOT safe for concurrent writes (commits interleave → "cannot commit").
        # For a file DB each thread gets its OWN connection (WAL handles concurrency).
        # `:memory:` can't be per-thread (each connection is a separate DB), so it
        # keeps one shared connection — fine for tests.
        self._shared: sqlite3.Connection | None = None
        if self._is_memory:
            self._shared = self._new_conn()
        else:
            ensure_dir(Path(path).parent)
        conn = self.conn  # init this thread's (or the shared) connection
        conn.executescript(SCHEMA_SQL)
        self._migrate()
        conn.commit()

    def _new_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=self._check_same_thread)
        conn.row_factory = sqlite3.Row
        if not self._is_memory:
            # Wait (don't error) up to 5s if another thread holds the write lock.
            conn.execute("PRAGMA busy_timeout=5000")
        with self._conns_lock:
            self._all_conns.append(conn)
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_conn()
            self._local.conn = conn
        return conn

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created (idempotent)."""
        for table, col, decl in (
            ("item_topics", "relevant", "INTEGER"),
            ("topics", "discover_interval_min", "INTEGER"),
            ("topics", "collect_interval_min", "INTEGER"),
            ("topics", "last_discovered_at", "TEXT"),
            ("topics", "last_briefed_at", "TEXT"),
            ("sources", "collect_interval_min", "INTEGER"),
            ("sources", "last_collected_at", "TEXT"),
            # Auto-drop dead/blocked feeds (0029): consecutive droppable-4xx fetch
            # failures + the last error, so a source is disabled after a streak.
            ("sources", "consecutive_failures", "INTEGER NOT NULL DEFAULT 0"),
            ("sources", "last_error", "TEXT"),
            ("sources", "last_error_at", "TEXT"),
            ("user_settings", "onboarded_at", "TEXT"),
            ("user_settings", "theme", "TEXT"),
            ("user_settings", "accent", "TEXT"),
            ("api_tokens", "revoked_at", "TEXT"),
            ("users", "status", "TEXT NOT NULL DEFAULT 'active'"),
            ("users", "last_login_at", "TEXT"),
            ("topics", "discover_period", "TEXT"),
            ("topics", "discover_start_date", "TEXT"),
            ("topics", "discover_at_min", "INTEGER"),
            ("topics", "max_sources", "INTEGER"),
            ("topics", "max_stories_per_source", "INTEGER"),
            ("topics", "image_path", "TEXT"),
            ("topics", "image_status", "TEXT NOT NULL DEFAULT 'none'"),
            ("token_usage", "topic_id", "INTEGER"),
            # User profile avatars (0028): identicon by default; optional Grok image.
            ("users", "avatar_path", "TEXT"),
            ("users", "avatar_status", "TEXT NOT NULL DEFAULT 'none'"),
            ("users", "avatar_prompt", "TEXT"),
        ):
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Indexes on migrated columns must be created AFTER the ALTER above — they
        # can't live in SCHEMA_SQL because that runs before this migration, so on an
        # existing DB the column wouldn't exist yet (would crash Store init).
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_usage_topic ON token_usage(topic_id, created_at)"
        )

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            return
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def close_all(self) -> None:
        """Close every connection opened across threads (server shutdown)."""
        if self._shared is not None:
            self._shared.close()
            return
        with self._conns_lock:
            conns, self._all_conns = self._all_conns, []
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._local = threading.local()

    # ---- topics ----
    def add_topic(self, slug: str, name: str, description: str = "") -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO topics (slug, name, description, created_at) VALUES (?, ?, ?, ?)",
            (slug, name, description, utc_now_iso()),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM topics WHERE slug = ?", (slug,)
        ).fetchone()
        return int(row["id"])

    def get_topic(self, slug: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM topics WHERE slug = ?", (slug,)
        ).fetchone()

    def list_topics(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM topics ORDER BY slug").fetchall()

    def set_topic_image(self, slug: str, image_path: str | None, status: str) -> None:
        """Record a topic's generated header image (0024). status: pending/ready/error."""
        self.conn.execute(
            "UPDATE topics SET image_path = ?, image_status = ? WHERE slug = ?",
            (image_path, status, slug),
        )
        self.conn.commit()

    def claim_topic_image(self, slug: str) -> bool:
        """Atomically move a topic's image from unset → 'pending'. Returns True only
        for the caller that won the claim, so concurrent first-views don't double-fire
        the (paid) image gen. SQLite serializes the UPDATE, closing the TOCTOU."""
        cur = self.conn.execute(
            "UPDATE topics SET image_status = 'pending' "
            "WHERE slug = ? AND (image_status IS NULL OR image_status IN ('', 'none'))",
            (slug,),
        )
        self.conn.commit()
        return cur.rowcount == 1

    # ---- sources ----
    def add_source(
        self,
        type: str,
        url: str,
        name: str,
        tags: list[str] | None = None,
        weight: float = 1.0,
        status: str = "active",
        discovered_by: str | None = None,
    ) -> int:
        self.conn.execute(
            """INSERT OR IGNORE INTO sources
               (type, url, name, tags_json, weight, status, discovered_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                type,
                url,
                name,
                json_dumps(tags or []),
                weight,
                status,
                discovered_by,
                utc_now_iso(),
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM sources WHERE type = ? AND url = ?", (type, url)
        ).fetchone()
        return int(row["id"])

    def link_topic_source(self, topic_id: int, source_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO topic_sources (topic_id, source_id) VALUES (?, ?)",
            (topic_id, source_id),
        )
        self.conn.commit()

    def source_topic_ids(self, source_id: int) -> list[int]:
        rows = self.conn.execute(
            "SELECT topic_id FROM topic_sources WHERE source_id = ?", (source_id,)
        ).fetchall()
        return [int(r["topic_id"]) for r in rows]

    def active_sources(self, topic_slug: str | None = None) -> list[sqlite3.Row]:
        if topic_slug:
            return self.conn.execute(
                """SELECT s.* FROM sources s
                   JOIN topic_sources ts ON ts.source_id = s.id
                   JOIN topics t ON t.id = ts.topic_id
                   WHERE t.slug = ? AND s.status = 'active'""",
                (topic_slug,),
            ).fetchall()
        return self.conn.execute(
            """SELECT DISTINCT s.* FROM sources s
               JOIN topic_sources ts ON ts.source_id = s.id
               WHERE s.status = 'active'"""
        ).fetchall()

    def list_sources(self, topic_slug: str | None = None) -> list[sqlite3.Row]:
        if topic_slug:
            return self.conn.execute(
                """SELECT s.* FROM sources s
                   JOIN topic_sources ts ON ts.source_id = s.id
                   JOIN topics t ON t.id = ts.topic_id
                   WHERE t.slug = ? ORDER BY s.name""",
                (topic_slug,),
            ).fetchall()
        return self.conn.execute("SELECT * FROM sources ORDER BY name").fetchall()

    def list_candidates(self, topic_slug: str | None = None) -> list[sqlite3.Row]:
        if topic_slug:
            return self.conn.execute(
                """SELECT s.* FROM sources s
                   JOIN topic_sources ts ON ts.source_id = s.id
                   JOIN topics t ON t.id = ts.topic_id
                   WHERE t.slug = ? AND s.status = 'candidate'
                   ORDER BY s.created_at""",
                (topic_slug,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM sources WHERE status = 'candidate' ORDER BY created_at"
        ).fetchall()

    def set_source_status(self, source_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE sources SET status = ? WHERE id = ?", (status, source_id)
        )
        self.conn.commit()

    # ---- auto-drop dead/blocked feeds (0029) ----
    def bump_source_failure(self, source_id: int, error: str) -> int:
        """Record a droppable fetch failure: increment the streak + store the error.
        Returns the new consecutive-failure count."""
        self.conn.execute(
            "UPDATE sources SET consecutive_failures = consecutive_failures + 1, "
            "last_error = ?, last_error_at = ? WHERE id = ?",
            (error, utc_now_iso(), source_id),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT consecutive_failures FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return int(row["consecutive_failures"]) if row else 0

    def clear_source_failures(self, source_id: int) -> None:
        """A successful fetch resets the streak (and clears the recorded error)."""
        self.conn.execute(
            "UPDATE sources SET consecutive_failures = 0, last_error = NULL, "
            "last_error_at = NULL WHERE id = ? AND consecutive_failures != 0",
            (source_id,),
        )
        self.conn.commit()

    def disable_source(self, source_id: int, reason: str) -> None:
        """Auto-disable a source (dead/blocked feed). Keeps the row + collected items;
        records why so the admin UI can show it and the owner can re-enable/delete."""
        self.conn.execute(
            "UPDATE sources SET status = 'disabled', last_error = ?, last_error_at = ? "
            "WHERE id = ?",
            (reason, utc_now_iso(), source_id),
        )
        self.conn.commit()

    def delete_source(self, source_id: int) -> bool:
        """Delete a source and its topic links. Already-collected items keep their
        (string) source_id reference and remain. Returns True if a row was removed."""
        self.conn.execute(
            "DELETE FROM topic_sources WHERE source_id = ?", (source_id,)
        )
        cur = self.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def source_urls(self) -> set[str]:
        rows = self.conn.execute("SELECT url FROM sources").fetchall()
        return {r["url"] for r in rows}

    # ---- items ----
    def upsert_item(self, item: dict[str, Any]) -> tuple[str, bool]:
        """Insert an item, deduping by ``dedupe_key`` (UNIQUE).

        Returns ``(item_id, inserted)`` where ``item_id`` is the canonical id in
        the DB — the *existing* row's id on a duplicate, the new id on insert.
        Callers map topics with the returned id (not ``item["item_id"]``), since
        the PK is a fresh ULID that won't match the stored row on a duplicate.
        """
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO items
               (item_id, dedupe_key, canonical_url, source_id, source_name, title,
                url, published_at, fetched_at, summary, score, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["item_id"],
                item["dedupe_key"],
                item.get("canonical_url"),
                str(item["source_id"]),
                item["source_name"],
                item["title"],
                item.get("url"),
                item.get("published_at"),
                item["fetched_at"],
                item.get("summary"),
                float(item.get("score") or 0.0),
                json_dumps(item.get("raw") or {}),
            ),
        )
        self.conn.commit()
        if cur.rowcount == 1:
            return item["item_id"], True
        row = self.conn.execute(
            "SELECT item_id FROM items WHERE dedupe_key = ?", (item["dedupe_key"],)
        ).fetchone()
        return (row["item_id"] if row else item["item_id"]), False

    def map_item_topic(self, item_id: str, topic_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)",
            (item_id, topic_id),
        )
        self.conn.commit()

    def items_for_topic(
        self, topic_slug: str, since_iso: str | None = None, limit: int = 50
    ) -> list[sqlite3.Row]:
        sql = [
            "SELECT i.* FROM items i",
            "JOIN item_topics it ON it.item_id = i.item_id",
            "JOIN topics t ON t.id = it.topic_id",
            "WHERE t.slug = ?",
            "AND COALESCE(it.relevant, 1) = 1",
        ]
        params: list[Any] = [topic_slug]
        if since_iso:
            sql.append("AND COALESCE(i.published_at, i.fetched_at) >= ?")
            params.append(since_iso)
        sql.append("ORDER BY COALESCE(i.published_at, i.fetched_at) DESC LIMIT ?")
        params.append(limit)
        return self.conn.execute(" ".join(sql), params).fetchall()

    def items_for_consumer(
        self, topic_slug: str, since_iso: str | None = None, limit: int = 100
    ) -> list[sqlite3.Row]:
        """Machine-pull query: filter/order by fetched_at (ingestion time),
        ascending, so consumers can checkpoint the last fetched_at they saw."""
        sql = [
            "SELECT i.* FROM items i",
            "JOIN item_topics it ON it.item_id = i.item_id",
            "JOIN topics t ON t.id = it.topic_id",
            "WHERE t.slug = ?",
        ]
        params: list[Any] = [topic_slug]
        if since_iso:
            sql.append("AND i.fetched_at > ?")
            params.append(since_iso)
        sql.append("ORDER BY i.fetched_at ASC LIMIT ?")
        params.append(limit)
        return self.conn.execute(" ".join(sql), params).fetchall()

    # ---- users / subscriptions / settings ----
    def items_for_user(
        self, user_id: int, since_iso: str | None = None, limit: int = 10
    ) -> list[sqlite3.Row]:
        sql = [
            "SELECT DISTINCT i.* FROM items i",
            "JOIN item_topics it ON it.item_id = i.item_id",
            "JOIN subscriptions sub ON sub.topic_id = it.topic_id",
            "WHERE sub.user_id = ?",
            "AND COALESCE(it.relevant, 1) = 1",
        ]
        params: list[Any] = [user_id]
        if since_iso:
            sql.append("AND i.fetched_at > ?")
            params.append(since_iso)
        sql.append("ORDER BY i.fetched_at DESC LIMIT ?")
        params.append(limit)
        return self.conn.execute(" ".join(sql), params).fetchall()
