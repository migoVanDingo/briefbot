"""SQLite persistence for bbv2 — topics, sources, items, and caches.

Schema is adapted from the original briefbot's `items`/cache tables, plus the
new topic model (topics, sources, topic_sources, item_topics). bbv2 owns this
database; it never opens the original briefbot's DB.
"""

from __future__ import annotations

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

CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_item_topics_topic ON item_topics(topic_id);
"""


class Store:
    def __init__(self, db_path: str | Path) -> None:
        path = str(db_path)
        if path != ":memory:":
            ensure_dir(Path(path).parent)
        self.conn = sqlite3.connect(path)
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

    # ---- items ----
    def upsert_item(self, item: dict[str, Any]) -> bool:
        """Insert an item; returns True if newly inserted, False if a duplicate."""
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
        return cur.rowcount == 1

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
