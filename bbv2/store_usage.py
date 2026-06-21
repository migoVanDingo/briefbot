"""Token-usage accounting for the bbv2 `Store`.

Mixed into `Store` (see store.py); operates on `self.conn`. Records one row per
metered LLM call (plus zero-token marker rows for chat *interactions*), so the
budget logic in `usage.py` can sum a user's spend over a rolling window and the
dashboard can show "N interactions / M tokens used".
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .util import utc_now_iso


class UsageQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    def record_usage(
        self,
        user_id: int,
        purpose: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        *,
        interaction: int = 0,
    ) -> None:
        """Record one LLM call's token spend (and/or a chat-interaction marker)."""
        self.conn.execute(
            """INSERT INTO token_usage
               (user_id, purpose, model, input_tokens, output_tokens, interaction, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                purpose,
                model,
                int(input_tokens or 0),
                int(output_tokens or 0),
                int(interaction or 0),
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def usage_window(self, user_id: int, since_iso: str) -> dict[str, Any]:
        """Aggregate a user's usage at/after `since_iso` (ISO-8601 UTC).

        Returns total input/output/combined tokens, the interaction count, and
        the earliest record timestamp in the window (for computing reset time).
        """
        row = self.conn.execute(
            """SELECT
                 COALESCE(SUM(input_tokens), 0)  AS input_tokens,
                 COALESCE(SUM(output_tokens), 0) AS output_tokens,
                 COALESCE(SUM(interaction), 0)   AS interactions,
                 MIN(created_at)                 AS earliest_at
               FROM token_usage
               WHERE user_id = ? AND created_at >= ?""",
            (user_id, since_iso),
        ).fetchone()
        inp = int(row["input_tokens"]) if row else 0
        out = int(row["output_tokens"]) if row else 0
        return {
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "interactions": int(row["interactions"]) if row else 0,
            "earliest_at": row["earliest_at"] if row else None,
        }
