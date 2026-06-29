"""Durable on-demand discovery-run queries for the bbv2 `Store` (0030).

Mixed into `Store`. One row per agent `find_sources` search; the preview is stored
as JSON so the chat results card re-hydrates after navigation/refresh.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import ids
from .util import utc_now_iso

# How long a finished run lingers in the poll feed (so a just-completed card stays).
RECENT_WINDOW_S = 600


def _iso_minus(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).replace(
        microsecond=0
    ).isoformat()


class DiscoveryRunsMixin:
    conn: sqlite3.Connection  # provided by Store

    def create_discovery_run(
        self,
        user_id: int,
        query: str,
        *,
        conversation_id: str | None = None,
        message_id: str | None = None,
        stage: str = "searching",
    ) -> str:
        run_id = ids.new_id(ids.DISCOVERY)
        now = utc_now_iso()
        self.conn.execute(
            """INSERT INTO discovery_runs
               (id, user_id, conversation_id, message_id, query, stage, status,
                result_json, committed_at, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'running', NULL, NULL, NULL, ?, ?)""",
            (run_id, user_id, conversation_id, message_id, query, stage, now, now),
        )
        self.conn.commit()
        return run_id

    def set_discovery_stage(self, run_id: str, stage: str) -> None:
        self.conn.execute(
            "UPDATE discovery_runs SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, utc_now_iso(), run_id),
        )
        self.conn.commit()

    def finish_discovery_run(
        self, run_id: str, status: str, *, result: dict | None = None, error: str | None = None
    ) -> None:
        self.conn.execute(
            """UPDATE discovery_runs SET status = ?, stage = 'ready',
               result_json = ?, error = ?, updated_at = ? WHERE id = ?""",
            (status, json.dumps(result) if result is not None else None, error,
             utc_now_iso(), run_id),
        )
        self.conn.commit()

    def mark_discovery_committed(self, run_id: str) -> None:
        self.conn.execute(
            "UPDATE discovery_runs SET committed_at = ?, updated_at = ? WHERE id = ?",
            (utc_now_iso(), utc_now_iso(), run_id),
        )
        self.conn.commit()

    def get_discovery_run(self, run_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM discovery_runs WHERE id = ?", (run_id,)
        ).fetchone()

    def discovery_result(self, run_id: str) -> dict[str, Any] | None:
        row = self.get_discovery_run(run_id)
        if not row or not row["result_json"]:
            return None
        return json.loads(row["result_json"])

    def discovery_runs_for_user(self, user_id: int) -> list[sqlite3.Row]:
        cutoff = _iso_minus(RECENT_WINDOW_S)
        return self.conn.execute(
            """SELECT * FROM discovery_runs
               WHERE user_id = ? AND (status = 'running' OR updated_at >= ?)
               ORDER BY created_at""",
            (user_id, cutoff),
        ).fetchall()

    def discovery_runs_for_conversation(
        self, user_id: int, conversation_id: str
    ) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM discovery_runs
               WHERE user_id = ? AND conversation_id = ?
               ORDER BY created_at""",
            (user_id, conversation_id),
        ).fetchall()

    def latest_discovery_with_results(
        self, user_id: int, conversation_id: str
    ) -> sqlite3.Row | None:
        """The most recent finished search WITH results in a conversation (committed
        or not) — used to resolve a source the user references (0031)."""
        return self.conn.execute(
            """SELECT * FROM discovery_runs
               WHERE user_id = ? AND conversation_id = ? AND status = 'done'
                 AND result_json IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, conversation_id),
        ).fetchone()

    def recent_uncommitted_discovery(
        self, user_id: int, conversation_id: str, within_iso: str
    ) -> sqlite3.Row | None:
        """The latest finished, not-yet-committed search since `within_iso` — what
        the agent is injected with so it can discuss found sources (0031)."""
        return self.conn.execute(
            """SELECT * FROM discovery_runs
               WHERE user_id = ? AND conversation_id = ? AND status = 'done'
                 AND committed_at IS NULL AND result_json IS NOT NULL
                 AND updated_at >= ?
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, conversation_id, within_iso),
        ).fetchone()

    def latest_committable_discovery(
        self, user_id: int, conversation_id: str
    ) -> sqlite3.Row | None:
        """The most recent finished, not-yet-committed search in a conversation — the
        target for a conversational 'yes, add them' (0030)."""
        return self.conn.execute(
            """SELECT * FROM discovery_runs
               WHERE user_id = ? AND conversation_id = ? AND status = 'done'
                 AND committed_at IS NULL
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, conversation_id),
        ).fetchone()

    def fail_orphaned_discovery_runs(self) -> int:
        """On startup: any run still 'running' lost its worker (process died)."""
        cur = self.conn.execute(
            "UPDATE discovery_runs SET status = 'error', error = 'interrupted', "
            "updated_at = ? WHERE status = 'running'",
            (utc_now_iso(),),
        )
        self.conn.commit()
        return cur.rowcount
