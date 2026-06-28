"""Opening the Store on an existing (pre-migration) DB must not crash.

Regression for the 0020–0024 deploy: a new index on a migrated column
(`token_usage.topic_id`) lived in SCHEMA_SQL, which runs BEFORE `_migrate` — so on
an existing prod DB the column didn't exist yet and Store init threw. The index now
lives in `_migrate`, after the ALTER.
"""

import sqlite3

from bbv2.store import Store


def test_store_opens_on_pre_topic_id_db(tmp_path):
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    # token_usage as it existed before topic_id was added (0021).
    c.executescript(
        """CREATE TABLE token_usage (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL, purpose TEXT, model TEXT,
             input_tokens INTEGER NOT NULL DEFAULT 0,
             output_tokens INTEGER NOT NULL DEFAULT 0,
             interaction INTEGER NOT NULL DEFAULT 0,
             created_at TEXT NOT NULL);"""
    )
    c.execute(
        "INSERT INTO token_usage (user_id, purpose, created_at) VALUES (1, 'chat', '2026-01-01T00:00:00+00:00')"
    )
    c.commit()
    c.close()

    store = Store(str(db))  # must migrate without crashing
    cols = [r[1] for r in store.conn.execute("PRAGMA table_info(token_usage)")]
    assert "topic_id" in cols  # column was added
    idx = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_token_usage_topic'"
    ).fetchone()
    assert idx is not None  # index was created after the ALTER
    # the pre-existing row is preserved, new column NULL
    assert store.conn.execute("SELECT topic_id FROM token_usage").fetchone()[0] is None
