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
from .store_schedule import SchedulerQueriesMixin
from .store_sessions import SessionQueriesMixin
from .store_spaces import SpaceQueriesMixin
from .store_usage import UsageQueriesMixin
from .store_users import UserQueriesMixin
from .util import ensure_dir, json_dumps, utc_now_iso


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    discover_interval_min INTEGER,
    collect_interval_min INTEGER,
    last_discovered_at TEXT,
    last_briefed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    url TEXT NOT NULL,
    name TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    weight REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    discovered_by TEXT,
    collect_interval_min INTEGER,
    last_collected_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(type, url)
);

CREATE TABLE IF NOT EXISTS topic_sources (
    topic_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    PRIMARY KEY (topic_id, source_id)
);

CREATE TABLE IF NOT EXISTS items (
    item_id TEXT NOT NULL PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    canonical_url TEXT,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    summary TEXT,
    score REAL NOT NULL DEFAULT 0,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS item_topics (
    item_id TEXT NOT NULL,
    topic_id INTEGER NOT NULL,
    relevant INTEGER,
    PRIMARY KEY (item_id, topic_id)
);

CREATE TABLE IF NOT EXISTS feed_cache (
    feed_url TEXT NOT NULL PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS discovered_feeds (
    site_url TEXT NOT NULL PRIMARY KEY,
    feeds_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token TEXT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS token_topics (
    token TEXT NOT NULL,
    topic_slug TEXT NOT NULL,
    PRIMARY KEY (token, topic_slug)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'human',
    status TEXT NOT NULL DEFAULT 'active',
    last_login_at TEXT,
    created_at TEXT NOT NULL
);

-- Backend auth sessions (0019): opaque refresh tokens, revocable, with a rotation
-- chain (replaced_by). The short-lived access JWT is stateless (see authjwt).
CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    refresh_token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    is_revoked INTEGER NOT NULL DEFAULT 0,
    replaced_by TEXT,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

-- Auth audit log (0019): login/refresh/logout/denied/revoked/disabled.
CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

-- User-spaces foundation (0019): blogs/learning/personalization. Existing
-- features stay global for now; per-space scoping is a later plan.
CREATE TABLE IF NOT EXISTS spaces (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT 'personal',
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_membership (
    space_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TEXT NOT NULL,
    PRIMARY KEY (space_id, user_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, topic_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL PRIMARY KEY,
    email_enabled INTEGER NOT NULL DEFAULT 1,
    digest_limit INTEGER NOT NULL DEFAULT 10,
    last_digest_at TEXT,
    onboarded_at TEXT,
    theme TEXT,
    accent TEXT
);

-- Write-once per-user UI flags (tours seen, dismissed banners). Presence = set.
-- Open-ended set keyed by string so a new tour needs no schema change (0018).
CREATE TABLE IF NOT EXISTS user_flags (
    user_id INTEGER NOT NULL,
    flag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, flag)
);

CREATE TABLE IF NOT EXISTS story_feedback (
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    vote INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS briefs (
    id TEXT NOT NULL PRIMARY KEY,
    topic_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    trending_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    model TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(topic_id, date)
);

CREATE TABLE IF NOT EXISTS favorite_folders (
    id TEXT NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS favorite_links (
    id TEXT NOT NULL PRIMARY KEY,
    folder_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    item_id TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(folder_id, url)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT NOT NULL PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    interaction INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);
CREATE INDEX IF NOT EXISTS idx_item_topics_topic ON item_topics(topic_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_user_time ON token_usage(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_events_user_time ON auth_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_space_membership_user ON space_membership(user_id);
"""


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
            ("user_settings", "onboarded_at", "TEXT"),
            ("user_settings", "theme", "TEXT"),
            ("user_settings", "accent", "TEXT"),
            ("api_tokens", "revoked_at", "TEXT"),
            ("users", "status", "TEXT NOT NULL DEFAULT 'active'"),
            ("users", "last_login_at", "TEXT"),
        ):
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # column already exists

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
