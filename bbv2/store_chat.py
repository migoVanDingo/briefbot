"""Conversation + message query methods for the bbv2 `Store`.

Mixed into `Store` (see store.py); operate on `self.conn`. Per-user chat
conversations and their ordered messages (tool-call summaries stored as JSON).
"""

from __future__ import annotations

import sqlite3

from . import ids
from .util import json_dumps, utc_now_iso


class ChatQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    def create_conversation(self, user_id: int) -> str:
        cid = ids.new_id(ids.CONVERSATION)
        now = utc_now_iso()
        self.conn.execute(
            """INSERT INTO conversations (id, user_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (cid, user_id, None, now, now),
        )
        self.conn.commit()
        return cid

    def list_conversations(self, user_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM conversation_messages m
                       WHERE m.conversation_id = c.id) AS message_count
               FROM conversations c
               WHERE c.user_id = ?
               ORDER BY c.updated_at DESC""",
            (user_id,),
        ).fetchall()

    def get_conversation(self, user_id: int, conversation_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()

    def get_messages(self, conversation_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM conversation_messages
               WHERE conversation_id = ? ORDER BY seq ASC""",
            (conversation_id,),
        ).fetchall()

    def append_message(
        self,
        conversation_id: str,
        user_id: int,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> str:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        seq = int(row["m"]) + 1
        mid = ids.new_id(ids.MESSAGE)
        self.conn.execute(
            """INSERT INTO conversation_messages
               (id, conversation_id, user_id, seq, role, content, tool_calls_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                conversation_id,
                user_id,
                seq,
                role,
                content,
                json_dumps(tool_calls) if tool_calls else None,
                utc_now_iso(),
            ),
        )
        self.conn.commit()
        return mid

    def set_conversation_title(
        self, user_id: int, conversation_id: str, title: str
    ) -> None:
        self.conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title, utc_now_iso(), conversation_id, user_id),
        )
        self.conn.commit()

    def touch_conversation(self, conversation_id: str) -> None:
        self.conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), conversation_id),
        )
        self.conn.commit()

    def delete_conversation(self, user_id: int, conversation_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        self.conn.execute(
            "DELETE FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.conn.commit()
        return cur.rowcount > 0
