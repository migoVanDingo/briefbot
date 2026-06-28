"""Durable provisioning-run queries for the bbv2 `Store` (0023).

Mixed into `Store` (see store.py). One row per topic pipeline (discover →…→ ready)
so it survives navigation and is observable from chat + the Topics page.
"""

from __future__ import annotations

import sqlite3

from . import ids
from .util import utc_now_iso

# Window for "recently finished" runs surfaced to the UI (so a just-completed pill
# lingers briefly with its ✓ before the client drops it).
RECENT_WINDOW_S = 300


class ProvisionRunsMixin:
    conn: sqlite3.Connection  # provided by Store

    def create_run(
        self,
        user_id: int,
        topic_slug: str,
        topic_name: str,
        *,
        surface: str = "chat",
        conversation_id: str | None = None,
        message_id: str | None = None,
        stage: str = "discovering",
    ) -> str:
        run_id = ids.new_id(ids.PROVISION)
        now = utc_now_iso()
        self.conn.execute(
            """INSERT INTO provision_runs
               (id, user_id, conversation_id, message_id, surface, topic_slug,
                topic_name, stage, status, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', NULL, ?, ?)""",
            (run_id, user_id, conversation_id, message_id, surface, topic_slug,
             topic_name, stage, now, now),
        )
        self.conn.commit()
        return run_id

    def set_run_stage(self, run_id: str, stage: str) -> None:
        self.conn.execute(
            "UPDATE provision_runs SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, utc_now_iso(), run_id),
        )
        self.conn.commit()

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE provision_runs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, utc_now_iso(), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM provision_runs WHERE id = ?", (run_id,)
        ).fetchone()

    def runs_for_user(self, user_id: int) -> list[sqlite3.Row]:
        """A user's running runs + ones that finished within RECENT_WINDOW_S (so a
        just-completed pill lingers, then the client lets it go)."""
        cutoff = _iso_minus(RECENT_WINDOW_S)
        return self.conn.execute(
            """SELECT * FROM provision_runs
               WHERE user_id = ? AND (status = 'running' OR updated_at >= ?)
               ORDER BY created_at""",
            (user_id, cutoff),
        ).fetchall()

    def runs_for_conversation(self, user_id: int, conversation_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM provision_runs
               WHERE user_id = ? AND conversation_id = ?
               ORDER BY created_at""",
            (user_id, conversation_id),
        ).fetchall()

    def fail_orphaned_runs(self) -> int:
        """On startup: any run still 'running' lost its worker thread (process
        died), so mark it interrupted. Returns the count."""
        cur = self.conn.execute(
            "UPDATE provision_runs SET status = 'error', error = 'interrupted', updated_at = ? "
            "WHERE status = 'running'",
            (utc_now_iso(),),
        )
        self.conn.commit()
        return cur.rowcount

    def reset_orphaned_image_jobs(self) -> int:
        """On startup: a background image gen left 'pending' lost its worker when the
        process died, and nothing else clears it (the atomic claim only fires from a
        non-pending state) — so the topic/avatar would be stuck spinning forever.
        Reset those back to 'none' so they can be re-kicked. Returns the count."""
        n = 0
        for sql in (
            "UPDATE topics SET image_status = 'none' WHERE image_status = 'pending'",
            "UPDATE users SET avatar_status = 'none' WHERE avatar_status = 'pending'",
        ):
            n += self.conn.execute(sql).rowcount
        self.conn.commit()
        return n


def _iso_minus(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).replace(
        microsecond=0
    ).isoformat()
