"""Consumer-API token methods for the bbv2 `Store`.

Split out of store.py (kept under the line cap). Mixed into `Store`; operate on
`self.conn`. These back the service-token read API (`bbv2 token …`, /items).
"""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from .util import utc_now_iso


class ConsumerTokenMixin:
    conn: sqlite3.Connection  # provided by Store

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
        """Look up an *active* token. Revoked tokens return None so auth fails."""
        return self.conn.execute(
            "SELECT * FROM api_tokens WHERE token = ? AND revoked_at IS NULL", (token,)
        ).fetchone()

    def revoke_token(self, token_or_label: str) -> int:
        """Revoke by full token or label. Returns the count revoked (a label may
        cover several). Already-revoked tokens are skipped."""
        rows = self.conn.execute(
            "SELECT token FROM api_tokens WHERE revoked_at IS NULL AND (token = ? OR label = ?)",
            (token_or_label, token_or_label),
        ).fetchall()
        for r in rows:
            self.conn.execute(
                "UPDATE api_tokens SET revoked_at = ? WHERE token = ?",
                (utc_now_iso(), r["token"]),
            )
        self.conn.commit()
        return len(rows)

    def token_topic_slugs(self, token: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT topic_slug FROM token_topics WHERE token = ? ORDER BY topic_slug",
            (token,),
        ).fetchall()
        return [r["topic_slug"] for r in rows]

    def list_tokens(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self.conn.execute(
            "SELECT token, label, created_at, revoked_at FROM api_tokens ORDER BY created_at"
        ).fetchall():
            out.append(
                {
                    "token": row["token"],
                    "label": row["label"],
                    "created_at": row["created_at"],
                    "revoked_at": row["revoked_at"],
                    "topics": self.token_topic_slugs(row["token"]),
                }
            )
        return out
