"""SQLite persistence for bbv2 — topics, sources, items, and caches.

Schema is adapted from the original briefbot's `items`/cache tables, plus the
new topic model (topics, sources, topic_sources, item_topics). bbv2 owns this
database; it never opens the original briefbot's DB.
"""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any

from .util import ensure_dir, json_dumps, utc_now_iso


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
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
    created_at TEXT NOT NULL
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
    created_at TEXT NOT NULL
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
    last_digest_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);
CREATE INDEX IF NOT EXISTS idx_item_topics_topic ON item_topics(topic_id);
"""


class Store:
    def __init__(self, db_path: str | Path, check_same_thread: bool = True) -> None:
        path = str(db_path)
        if path != ":memory:":
            ensure_dir(Path(path).parent)
        # The API serves requests on a threadpool; check_same_thread=False lets
        # one connection be shared (reads only, WAL).
        self.conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- feed cache (conditional GET) ----
    def get_feed_cache_headers(self, feed_url: str) -> dict[str, str]:
        row = self.conn.execute(
            "SELECT etag, last_modified FROM feed_cache WHERE feed_url = ?",
            (feed_url,),
        ).fetchone()
        headers: dict[str, str] = {}
        if row:
            if row["etag"]:
                headers["If-None-Match"] = row["etag"]
            if row["last_modified"]:
                headers["If-Modified-Since"] = row["last_modified"]
        return headers

    def set_feed_cache_headers(
        self, feed_url: str, etag: str | None, modified: str | None
    ) -> None:
        self.conn.execute(
            """INSERT INTO feed_cache (feed_url, etag, last_modified, last_checked_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(feed_url) DO UPDATE SET
                 etag=excluded.etag,
                 last_modified=excluded.last_modified,
                 last_checked_at=excluded.last_checked_at""",
            (feed_url, etag, modified, utc_now_iso()),
        )
        self.conn.commit()

    # ---- discovery cache ----
    def get_discovered_feeds(self, site_url: str) -> list[str] | None:
        row = self.conn.execute(
            "SELECT feeds_json FROM discovered_feeds WHERE site_url = ?",
            (site_url,),
        ).fetchone()
        if not row:
            return None
        import json

        return json.loads(row["feeds_json"])

    def set_discovered_feeds(self, site_url: str, feeds: list[str]) -> None:
        self.conn.execute(
            """INSERT INTO discovered_feeds (site_url, feeds_json, discovered_at)
               VALUES (?, ?, ?)
               ON CONFLICT(site_url) DO UPDATE SET
                 feeds_json=excluded.feeds_json,
                 discovered_at=excluded.discovered_at""",
            (site_url, json_dumps(feeds), utc_now_iso()),
        )
        self.conn.commit()

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

    # ---- API tokens (consumer API) ----
    def create_token(self, label: str, topic_slugs: list[str]) -> str:
        token = secrets.token_urlsafe(32)
        self.conn.execute(
            "INSERT INTO api_tokens (token, label, created_at) VALUES (?, ?, ?)",
            (token, label, utc_now_iso()),
        )
        for slug in topic_slugs:
            self.conn.execute(
                "INSERT OR IGNORE INTO token_topics (token, topic_slug) VALUES (?, ?)",
                (token, slug),
            )
        self.conn.commit()
        return token

    def get_token(self, token: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM api_tokens WHERE token = ?", (token,)
        ).fetchone()

    def token_topic_slugs(self, token: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT topic_slug FROM token_topics WHERE token = ? ORDER BY topic_slug",
            (token,),
        ).fetchall()
        return [r["topic_slug"] for r in rows]

    def list_tokens(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self.conn.execute(
            "SELECT token, label, created_at FROM api_tokens ORDER BY created_at"
        ).fetchall():
            out.append(
                {
                    "token": row["token"],
                    "label": row["label"],
                    "created_at": row["created_at"],
                    "topics": self.token_topic_slugs(row["token"]),
                }
            )
        return out

    # ---- users / subscriptions / settings ----
    def add_user(self, name: str, email: str, role: str = "human") -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO users (name, email, role, created_at) VALUES (?, ?, ?, ?)",
            (name, email, role, utc_now_iso()),
        )
        row = self.conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        uid = int(row["id"])
        self.conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (uid,)
        )
        self.conn.commit()
        return uid

    def get_user(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()

    def list_users(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM users ORDER BY name").fetchall()

    def subscribe(self, user_id: int, topic_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO subscriptions (user_id, topic_id) VALUES (?, ?)",
            (user_id, topic_id),
        )
        self.conn.commit()

    def unsubscribe(self, user_id: int, topic_id: int) -> None:
        self.conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND topic_id = ?",
            (user_id, topic_id),
        )
        self.conn.commit()

    def user_subscriptions(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT t.* FROM topics t
               JOIN subscriptions s ON s.topic_id = t.id
               WHERE s.user_id = ? ORDER BY t.slug""",
            (user_id,),
        ).fetchall()

    def get_user_settings(self, user_id: int) -> sqlite3.Row:
        self.conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,)
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()

    def set_user_settings(
        self,
        user_id: int,
        email_enabled: bool | None = None,
        digest_limit: int | None = None,
        last_digest_at: str | None = None,
    ) -> None:
        self.get_user_settings(user_id)  # ensure row exists
        sets: list[str] = []
        params: list[Any] = []
        if email_enabled is not None:
            sets.append("email_enabled = ?")
            params.append(1 if email_enabled else 0)
        if digest_limit is not None:
            sets.append("digest_limit = ?")
            params.append(int(digest_limit))
        if last_digest_at is not None:
            sets.append("last_digest_at = ?")
            params.append(last_digest_at)
        if not sets:
            return
        params.append(user_id)
        self.conn.execute(
            f"UPDATE user_settings SET {', '.join(sets)} WHERE user_id = ?", params
        )
        self.conn.commit()

    def users_with_email_enabled(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT u.* FROM users u
               JOIN user_settings s ON s.user_id = u.id
               WHERE s.email_enabled = 1 ORDER BY u.id"""
        ).fetchall()

    def items_for_user(
        self, user_id: int, since_iso: str | None = None, limit: int = 10
    ) -> list[sqlite3.Row]:
        sql = [
            "SELECT DISTINCT i.* FROM items i",
            "JOIN item_topics it ON it.item_id = i.item_id",
            "JOIN subscriptions sub ON sub.topic_id = it.topic_id",
            "WHERE sub.user_id = ?",
        ]
        params: list[Any] = [user_id]
        if since_iso:
            sql.append("AND i.fetched_at > ?")
            params.append(since_iso)
        sql.append("ORDER BY i.fetched_at DESC LIMIT ?")
        params.append(limit)
        return self.conn.execute(" ".join(sql), params).fetchall()
