"""User, subscription, and per-user settings queries for the bbv2 `Store`.

Mixed into `Store` (see store.py); operate on `self.conn`. Split out to keep
store.py under the size cap.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from .util import utc_now_iso


class UserQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

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

    def is_recent_user(self, user_id: int, window_s: float) -> bool:
        """True if the account was created within `window_s` — i.e. still in the
        initial setup window. `created_at` is set once (INSERT OR IGNORE), so this
        is stable across re-logins/reloads, unlike the onboarding flag."""
        row = self.conn.execute(
            "SELECT created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not row["created_at"]:
            return False
        try:
            created = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            return False
        return (datetime.now(timezone.utc) - created).total_seconds() < window_s

    def get_user(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    def set_user_role(self, email: str, role: str) -> None:
        self.conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, email))
        self.conn.commit()

    def set_user_status(self, email: str, status: str) -> None:
        """active | disabled. A disabled user is blocked at exchange + every
        request (current_user), and their sessions should be revoked separately."""
        self.conn.execute(
            "UPDATE users SET status = ? WHERE email = ?", (status, email)
        )
        self.conn.commit()

    # ---- profile avatar (0028) ----
    def claim_avatar(self, user_id: int, prompt: str) -> bool:
        """Atomically move a user's avatar to 'pending' from any state, recording the
        prompt. Returns False if a generation is already in flight (status 'pending')
        so a double-submit doesn't fire two (paid) generations."""
        cur = self.conn.execute(
            "UPDATE users SET avatar_status = 'pending', avatar_prompt = ? "
            "WHERE id = ? AND COALESCE(avatar_status, 'none') != 'pending'",
            (prompt, user_id),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def set_avatar(self, user_id: int, path: str | None, status: str) -> None:
        """Record the result of an avatar generation (ready/error) or a reset to the
        default identicon (path=None, status='none')."""
        self.conn.execute(
            "UPDATE users SET avatar_path = ?, avatar_status = ? WHERE id = ?",
            (path, status, user_id),
        )
        self.conn.commit()

    def touch_last_login(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (utc_now_iso(), user_id),
        )
        self.conn.commit()

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
        theme: str | None = None,
        accent: str | None = None,
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
        # theme/accent: explicit "" clears back to "follow OS / default" (NULL);
        # None means "leave unchanged" (matches the other fields' semantics).
        if theme is not None:
            sets.append("theme = ?")
            params.append(theme or None)
        if accent is not None:
            sets.append("accent = ?")
            params.append(accent or None)
        if not sets:
            return
        params.append(user_id)
        self.conn.execute(
            f"UPDATE user_settings SET {', '.join(sets)} WHERE user_id = ?", params
        )
        self.conn.commit()

    # ---- UI flags (write-once "seen" markers — tours, dismissed banners) ----

    def get_user_flags(self, user_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT flag FROM user_flags WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {r["flag"] for r in rows}

    def set_user_flag(self, user_id: int, flag: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO user_flags (user_id, flag, created_at) VALUES (?, ?, ?)",
            (user_id, flag, utc_now_iso()),
        )
        self.conn.commit()

    def clear_user_flag(self, user_id: int, flag: str) -> None:
        self.conn.execute(
            "DELETE FROM user_flags WHERE user_id = ? AND flag = ?", (user_id, flag)
        )
        self.conn.commit()

    def mark_onboarded(self, user_id: int) -> None:
        self.get_user_settings(user_id)  # ensure row exists
        self.conn.execute(
            "UPDATE user_settings SET onboarded_at = ? WHERE user_id = ?",
            (utc_now_iso(), user_id),
        )
        self.conn.commit()

    def is_onboarded(self, user_id: int) -> bool:
        return bool(self.get_user_settings(user_id)["onboarded_at"])

    def users_with_email_enabled(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT u.* FROM users u
               JOIN user_settings s ON s.user_id = u.id
               WHERE s.email_enabled = 1 ORDER BY u.id"""
        ).fetchall()
