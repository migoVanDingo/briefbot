"""Auth session + audit queries for the bbv2 `Store` (0019).

Mixed into `Store` (see store.py); operate on `self.conn`. Sessions hold the
opaque refresh token; the short-lived access JWT is stateless. Revocation +
rotation live here so the owner can force a user offline.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from . import ids
from .util import utc_now_iso


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(expires_at: str) -> bool:
    try:
        return datetime.fromisoformat(expires_at) <= _now()
    except (TypeError, ValueError):
        return True


class SessionQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    # ---- sessions ----

    def create_session(
        self,
        user_id: int,
        ip: str | None = None,
        user_agent: str | None = None,
        ttl_s: int = 2_592_000,
    ) -> tuple[str, str]:
        """Create a session, returning (session_id, refresh_token)."""
        sid = ids.new_id(ids.SESSION)
        refresh = secrets.token_urlsafe(32)
        now = _now()
        expires = (now + timedelta(seconds=ttl_s)).isoformat()
        self.conn.execute(
            """INSERT INTO user_sessions
               (id, user_id, refresh_token, expires_at, last_active_at,
                is_revoked, replaced_by, ip, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)""",
            (sid, user_id, refresh, expires, now.isoformat(), ip, user_agent, now.isoformat()),
        )
        self.conn.commit()
        return sid, refresh

    def get_session_by_refresh(self, refresh: str) -> sqlite3.Row | None:
        """An ACTIVE session for this refresh token (not revoked, not expired)."""
        row = self.conn.execute(
            "SELECT * FROM user_sessions WHERE refresh_token = ? AND is_revoked = 0",
            (refresh,),
        ).fetchone()
        if not row or _expired(row["expires_at"]):
            return None
        return row

    def session_active(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT expires_at FROM user_sessions WHERE id = ? AND is_revoked = 0",
            (session_id,),
        ).fetchone()
        return bool(row) and not _expired(row["expires_at"])

    def rotate_session(
        self, refresh: str, ip: str | None, user_agent: str | None, ttl_s: int
    ) -> tuple[int, str, str] | None:
        """Validate `refresh`, mint a NEW session, revoke the old one (linking the
        rotation chain). Returns (user_id, new_session_id, new_refresh) or None."""
        old = self.get_session_by_refresh(refresh)
        if not old:
            return None
        user_id = int(old["user_id"])
        new_sid, new_refresh = self.create_session(user_id, ip, user_agent, ttl_s)
        self.conn.execute(
            "UPDATE user_sessions SET is_revoked = 1, replaced_by = ? WHERE id = ?",
            (new_sid, old["id"]),
        )
        self.conn.commit()
        return user_id, new_sid, new_refresh

    def revoke_session(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE id = ?", (session_id,)
        )
        self.conn.commit()

    def revoke_session_by_refresh(self, refresh: str) -> None:
        self.conn.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE refresh_token = ?", (refresh,)
        )
        self.conn.commit()

    def revoke_user_sessions(self, user_id: int) -> int:
        """Revoke every active session for a user (force-logout). Returns count."""
        cur = self.conn.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE user_id = ? AND is_revoked = 0",
            (user_id,),
        )
        self.conn.commit()
        return cur.rowcount

    def prune_expired_sessions(self) -> None:
        """Opportunistic cleanup of long-dead sessions (bounds table growth)."""
        self.conn.execute(
            "DELETE FROM user_sessions WHERE expires_at < ?", (_now().isoformat(),)
        )
        self.conn.commit()

    # ---- auth audit ----

    def log_auth_event(
        self,
        user_id: int | None,
        event: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO auth_events (user_id, event, ip, user_agent, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, event, ip, user_agent, utc_now_iso()),
        )
        self.conn.commit()

    def list_auth_events(
        self, limit: int = 100, user_id: int | None = None
    ) -> list[sqlite3.Row]:
        if user_id is not None:
            return self.conn.execute(
                "SELECT * FROM auth_events WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM auth_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
