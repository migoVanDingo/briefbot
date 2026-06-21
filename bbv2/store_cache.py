"""Feed + discovery cache queries for the bbv2 `Store`.

Mixed into `Store` (see store.py). Conditional-GET headers per feed URL (ETag /
Last-Modified) and the site→feeds autodiscovery cache, so collection avoids
re-fetching and re-probing unchanged sources.
"""

from __future__ import annotations

import json
import sqlite3

from .util import json_dumps, utc_now_iso


class CacheQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

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
