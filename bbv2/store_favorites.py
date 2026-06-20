"""Favorites + folders query methods for the bbv2 `Store`.

Mixed into `Store` (see store.py); operate on `self.conn`. Per-user folders (the
default `favorites` folder is auto-created on demand) and links deduped per
folder+url, mirroring the original briefbot's favorites model.
"""

from __future__ import annotations

import sqlite3

from . import ids
from .util import titlecase, utc_now_iso

DEFAULT_FOLDER = "favorites"


def _folder_name(name: str) -> str:
    """Title-case folder names, but keep the internal default ('favorites')."""
    name = (name or "").strip() or DEFAULT_FOLDER
    return name if name.lower() == DEFAULT_FOLDER else titlecase(name)


class FavoriteQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    def create_folder(self, user_id: int, name: str) -> str:
        """Get-or-create a folder by name for a user; returns its id."""
        name = _folder_name(name)
        self.conn.execute(
            """INSERT OR IGNORE INTO favorite_folders (id, user_id, name, created_at)
               VALUES (?, ?, ?, ?)""",
            (ids.new_id(ids.FOLDER), user_id, name, utc_now_iso()),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM favorite_folders WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        return row["id"]

    def ensure_default_folder(self, user_id: int) -> str:
        return self.create_folder(user_id, DEFAULT_FOLDER)

    def list_folders(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT f.id, f.name, f.created_at,
                      (SELECT COUNT(*) FROM favorite_links l WHERE l.folder_id = f.id)
                        AS count
               FROM favorite_folders f
               WHERE f.user_id = ?
               ORDER BY (f.name = 'favorites') DESC, f.name COLLATE NOCASE""",
            (user_id,),
        ).fetchall()

    def get_folder(self, user_id: int, folder_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM favorite_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        ).fetchone()

    def get_folder_by_name(self, user_id: int, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM favorite_folders WHERE user_id = ? AND name = ?",
            (user_id, _folder_name(name)),
        ).fetchone()

    def add_favorite(
        self,
        user_id: int,
        folder_id: str,
        title: str,
        url: str,
        item_id: str | None = None,
    ) -> sqlite3.Row:
        """Save a link into a folder (dedup per folder+url)."""
        self.conn.execute(
            """INSERT INTO favorite_links
               (id, folder_id, user_id, item_id, title, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(folder_id, url) DO UPDATE SET
                 title=excluded.title, item_id=excluded.item_id""",
            (
                ids.new_id(ids.FAVORITE),
                folder_id,
                user_id,
                item_id,
                title,
                url,
                utc_now_iso(),
            ),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT * FROM favorite_links WHERE folder_id = ? AND url = ?",
            (folder_id, url),
        ).fetchone()

    def list_favorites(self, user_id: int, folder_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM favorite_links
               WHERE folder_id = ? AND user_id = ?
               ORDER BY created_at DESC""",
            (folder_id, user_id),
        ).fetchall()

    def search_favorites(
        self, user_id: int, query: str, limit: int = 50
    ) -> list[sqlite3.Row]:
        """Token-AND search across all of a user's saved links (title/url)."""
        sql = ["SELECT * FROM favorite_links WHERE user_id = ?"]
        params: list = [user_id]
        for tok in (query or "").split()[:8]:
            like = f"%{tok}%"
            sql.append("AND (title LIKE ? OR url LIKE ?)")
            params.extend([like, like])
        sql.append("ORDER BY created_at DESC LIMIT ?")
        params.append(limit)
        return self.conn.execute(" ".join(sql), params).fetchall()

    def remove_favorite(self, user_id: int, favorite_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM favorite_links WHERE id = ? AND user_id = ?",
            (favorite_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount > 0
