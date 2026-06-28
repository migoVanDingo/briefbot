"""bbv2 SQLite schema (DDL only).

Extracted from store.py to keep that module under the size cap; store.py
executes this on connect and runs idempotent ALTERs in `_migrate`.
"""

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    discover_interval_min INTEGER,
    collect_interval_min INTEGER,
    last_discovered_at TEXT,
    last_briefed_at TEXT,
    -- Per-topic discovery schedule (0020): "run every <period> starting <date> at
    -- <time>". The weekday / day-of-month is derived from the start date. NULL
    -- period → fall back to the env default interval.
    discover_period TEXT,               -- day | week | month | year
    discover_start_date TEXT,           -- YYYY-MM-DD anchor (UTC)
    discover_at_min INTEGER,            -- time of day to run (minutes into day, UTC)
    -- Per-topic ingest caps (0020): NULL → fall back to the env default.
    max_sources INTEGER,
    max_stories_per_source INTEGER,
    -- Per-topic Grok Imagine header image (0024).
    image_path TEXT,
    image_status TEXT NOT NULL DEFAULT 'none',  -- none | pending | ready | error
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    url TEXT NOT NULL,
    name TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    weight REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    discovered_by TEXT,
    collect_interval_min INTEGER,
    last_collected_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(type, url)
);

CREATE TABLE IF NOT EXISTS topic_sources (
    topic_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    PRIMARY KEY (topic_id, source_id)
);

CREATE TABLE IF NOT EXISTS items (
    item_id TEXT NOT NULL PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    canonical_url TEXT,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    summary TEXT,
    score REAL NOT NULL DEFAULT 0,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS item_topics (
    item_id TEXT NOT NULL,
    topic_id INTEGER NOT NULL,
    relevant INTEGER,
    PRIMARY KEY (item_id, topic_id)
);

CREATE TABLE IF NOT EXISTS feed_cache (
    feed_url TEXT NOT NULL PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS discovered_feeds (
    site_url TEXT NOT NULL PRIMARY KEY,
    feeds_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token TEXT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS token_topics (
    token TEXT NOT NULL,
    topic_slug TEXT NOT NULL,
    PRIMARY KEY (token, topic_slug)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'human',
    status TEXT NOT NULL DEFAULT 'active',
    last_login_at TEXT,
    created_at TEXT NOT NULL
);

-- Backend auth sessions (0019): opaque refresh tokens, revocable, with a rotation
-- chain (replaced_by). The short-lived access JWT is stateless (see authjwt).
CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    refresh_token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    is_revoked INTEGER NOT NULL DEFAULT 0,
    replaced_by TEXT,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

-- Auth audit log (0019): login/refresh/logout/denied/revoked/disabled.
CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

-- User-spaces foundation (0019): blogs/learning/personalization. Existing
-- features stay global for now; per-space scoping is a later plan.
CREATE TABLE IF NOT EXISTS spaces (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT 'personal',
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS space_membership (
    space_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TEXT NOT NULL,
    PRIMARY KEY (space_id, user_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, topic_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL PRIMARY KEY,
    email_enabled INTEGER NOT NULL DEFAULT 1,
    digest_limit INTEGER NOT NULL DEFAULT 10,
    last_digest_at TEXT,
    onboarded_at TEXT,
    theme TEXT,
    accent TEXT
);

-- Write-once per-user UI flags (tours seen, dismissed banners). Presence = set.
-- Open-ended set keyed by string so a new tour needs no schema change (0018).
CREATE TABLE IF NOT EXISTS user_flags (
    user_id INTEGER NOT NULL,
    flag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, flag)
);

CREATE TABLE IF NOT EXISTS story_feedback (
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    vote INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS briefs (
    id TEXT NOT NULL PRIMARY KEY,
    topic_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    trending_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    model TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(topic_id, date)
);

CREATE TABLE IF NOT EXISTS favorite_folders (
    id TEXT NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS favorite_links (
    id TEXT NOT NULL PRIMARY KEY,
    folder_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    item_id TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(folder_id, url)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT NOT NULL PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    interaction INTEGER NOT NULL DEFAULT 0,
    topic_id INTEGER,                   -- per-topic attribution for metrics (0021)
    created_at TEXT NOT NULL
);

-- Durable topic-provisioning runs (0023): a background-job record per pipeline so
-- it survives navigation/refresh and is observable from chat + the Topics page.
CREATE TABLE IF NOT EXISTS provision_runs (
    id TEXT PRIMARY KEY,                 -- PRV…
    user_id INTEGER NOT NULL,
    conversation_id TEXT,                -- chat surface: which conversation
    message_id TEXT,                     -- chat surface: which assistant message
    surface TEXT NOT NULL DEFAULT 'chat',-- chat | topics
    topic_slug TEXT NOT NULL,
    topic_name TEXT NOT NULL,
    stage TEXT,                          -- current stage (discovering…ready)
    status TEXT NOT NULL DEFAULT 'running', -- running | done | error
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Story link clicks — the one engagement signal not already captured (0021).
CREATE TABLE IF NOT EXISTS story_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);
CREATE INDEX IF NOT EXISTS idx_item_topics_topic ON item_topics(topic_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_user_time ON token_usage(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_events_user_time ON auth_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_space_membership_user ON space_membership(user_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_topic ON token_usage(topic_id, created_at);
CREATE INDEX IF NOT EXISTS idx_story_clicks_user ON story_clicks(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_provision_runs_user ON provision_runs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_provision_runs_conv ON provision_runs(conversation_id);
"""
