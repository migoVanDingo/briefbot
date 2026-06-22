"""User-spaces queries for the bbv2 `Store` (0019 foundation).

Mixed into `Store` (see store.py); operate on `self.conn`. Spaces are the future
home of blogs/learning/personalization; per-space membership roles feed RBAC
(see rbac.py). Existing features remain global for now.
"""

from __future__ import annotations

import sqlite3

from . import ids
from .util import utc_now_iso


class SpaceQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    def create_space(
        self, owner_user_id: int, type: str, name: str
    ) -> str:
        """Create a space and add the owner as an 'owner' member."""
        sid = ids.new_id(ids.SPACE)
        now = utc_now_iso()
        self.conn.execute(
            "INSERT INTO spaces (id, owner_user_id, type, name, created_at) VALUES (?, ?, ?, ?, ?)",
            (sid, owner_user_id, type, name, now),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO space_membership (space_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
            (sid, owner_user_id, now),
        )
        self.conn.commit()
        return sid

    def add_member(self, space_id: str, user_id: int, role: str = "viewer") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO space_membership (space_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (space_id, user_id, role, utc_now_iso()),
        )
        self.conn.commit()

    def user_space_role(self, space_id: str, user_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT role FROM space_membership WHERE space_id = ? AND user_id = ?",
            (space_id, user_id),
        ).fetchone()
        return row["role"] if row else None

    def get_space(self, space_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM spaces WHERE id = ?", (space_id,)
        ).fetchone()

    def user_spaces(self, user_id: int) -> list[sqlite3.Row]:
        """Spaces the user belongs to, with their membership role, oldest first
        (so the personal space, created at signup, leads the list)."""
        return self.conn.execute(
            """SELECT s.id, s.type, s.name, s.owner_user_id, m.role
               FROM spaces s
               JOIN space_membership m ON m.space_id = s.id
               WHERE m.user_id = ?
               ORDER BY s.created_at""",
            (user_id,),
        ).fetchall()

    def ensure_personal_space(self, user_id: int, display_name: str) -> str:
        """Return the user's personal space, creating it on first login."""
        row = self.conn.execute(
            "SELECT id FROM spaces WHERE owner_user_id = ? AND type = 'personal' LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            return row["id"]
        name = f"{display_name}'s space" if display_name else "Personal space"
        return self.create_space(user_id, "personal", name)
