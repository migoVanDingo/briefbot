# 0001 — bbv2 — Design

**Status:** Design (awaiting review)
**Date:** 2026-06-19
**Phase:** Design

## What this is

**bbv2** is a small, multi-user, **topic-driven news-intelligence platform**. A
user picks topics they care about; an **agent web-searches to propose sources**
for each topic; the user approves them; ingestion runs on a **cron** (like the
original briefbot) into a shared, deduped archive. Each user sees only items from
topics they subscribe to. bbv2 also exposes a **consumer API** so other apps
(e.g. the `trader` project, as a service account) can pull items by topic.

Scale: **personal** — me + my mom + my brother (a handful of accounts). Keep auth
and tenancy lightweight; this is not a public SaaS.

## Relationship to the original briefbot

bbv2 is a **clean-room project** that **reuses code from the original briefbot by
copying and adapting it** — the original (`~/Developer/agent/projects/ai-assistant`)
is a live nightly system and **must not be modified**. What to copy vs. build new
is tracked in [`_documentation/reuse-map.md`](../_documentation/reuse-map.md).

Original briefbot is **tech-only and single-profile**; bbv2 adds: multiple users +
subscriptions, topics as first-class entities, **agent-driven source discovery**,
and a consumer API. The ingestion/storage/LLM internals are largely reusable.

## Stack

Match the original so copied code drops in cleanly:

- Python 3 + **FastAPI** + **uvicorn**
- **SQLite** (WAL) to start
- `feedparser`, `beautifulsoup4`, `requests`, `pydantic`, `PyYAML`, `RapidFuzz`
- **Anthropic** for LLM (summaries, discovery reasoning)
- **Brave Search API** for agent source discovery
- **Email** notifications per user (reuse the original's mailgun integration)
- Vite dashboard later (reuse the original's dashboard scaffolding)
- Cron via `cron`/launchd on the always-on home server

## Data model (multi-user-lite)

```
users(id, name, email, role)          role: human | service
topics(id, slug, name, description)   shared, global
sources(id, type, url, name, tags, weight, status, discovered_by, created_at)
                                      type: rss | site | hn | arxiv
                                      status: candidate | active | rejected
topic_sources(topic_id, source_id)    M:N — a source can feed many topics
subscriptions(user_id, topic_id)
items(item_id, dedupe_key, url, title, body, source_id, published_at, …)  global, deduped
item_topics(item_id, topic_id)        which topic(s) surfaced an item
api_tokens(token, user_id)            service accounts (e.g. trader)
user_settings(user_id, email_enabled, brief_cadence, headline_digest, …)
favorites(user_id, item_id, collection)   saved items, organized into folders
likes(user_id, item_id)
```

**Visibility rule:** a user sees an item iff there's an `item_topics` row for a
topic they're subscribed to. No shared subscription → no shared data; shared
topic → same underlying items. Items are stored once regardless.

## Agent-driven source discovery (the headline feature)

1. User creates/selects a **topic** (e.g. "crypto regulation").
2. A **discovery job** uses an LLM + web search to propose candidate sources
   (RSS feeds, blogs, news sites, subreddits…). The original's `discover.py`
   resolves a site URL → its RSS/Atom feed; we reuse it to turn proposals into
   concrete feed URLs.
3. Candidates are stored `status='candidate'`.
4. User **reviews and approves** candidates (dashboard/CLI) → `status='active'`.
   Human-in-the-loop keeps source quality high and avoids junk feeds.
5. Active sources join the topic; the next ingestion run picks them up.

*Decision needed:* web-search backend — Anthropic tool-use web search vs. a
dedicated API (Brave/SerpAPI/Tavily). Affects cost + quality.

## Ingestion & cadence (two-tier)

Reuse the original's `collect` pipeline (fetch → normalize → dedupe → score →
upsert), extended to **map each item to its source's topic(s)** via `item_topics`.
Runs on the server over the union of `active` sources with ≥1 subscriber.

**Decouple cheap collection from expensive synthesis:**

- **Collect** (cheap, frequent — start **hourly**, configurable): fetch/dedupe/
  store + refresh the dynamic **Headlines** feed. No LLM. Feeds are polled with
  conditional GETs (ETag/Last-Modified), so most hourly polls are near-no-ops and
  polite. Hourly also gives `trader` good news timestamp granularity.
- **Daily brief** (expensive, nightly): the LLM-synthesized brief, as in og
  briefbot. This is the only place we spend LLM tokens per run.

**Headlines** = most-recent high-`score` items across a user's subscribed topics,
recomputed each collect — a live section to complement the static daily brief.

## Notifications (per user)

Each user gets emails at **their own** address (reuse the original's mailgun
integration; recipient = `users.email`). Controlled by `user_settings`:
email on/off, brief cadence, optional headline digest. Frequent collection makes
these settings necessary — a user must be able to turn it down or off.

## Engagement (news-app features, like og briefbot)

bbv2 is a general news app, so it carries the original's user features, scoped per
user: **like** items, save to **favorites/collections** (folders), and
**discuss an item with the agent** (reuse og briefbot's `/ask` agent flow).
**Trading-specific** features/labels/signals do **not** live here — those belong
to the `trader` project, which only *consumes* bbv2 data.

## Consumer API (for trader and other apps)

Token-authenticated, read-only:

- `GET /topics` — list topics.
- `GET /items?topic=<slug>&since=<iso>&limit=` — items for a topic since a time
  (title, url, extracted body, source, published_at, tags).
- (later) `GET /items/{id}/features` — structured enrichment if we add it.

The `trader` service account subscribes to `crypto` / `markets` / `geopolitics`
and pulls from here. Trading-specific feature extraction stays in `trader`, not
bbv2.

## Build order (phases → own plans 0002+)

1. **Ingestion core** — topics/sources/items schema + copied `collect` pipeline +
   `item_topics` mapping + hourly collect + CLI. Single profile; seed sources by hand.
2. **Consumer API** — token auth + `/topics` + `/items` so trader can read early.
3. **Agent source discovery** — topic → Brave search → candidate sources → approval.
4. **Multi-user + settings** — users/subscriptions/visibility scoping, service
   accounts, `user_settings`, and **per-user email notifications**.
5. **Dashboard** — Headlines feed, topic management, source approval, browsing
   (reuse original UI).
6. **Briefs/LLM** — per-user nightly brief + summaries (reuse `executive`/`brief`).
7. **Engagement** — like, favorites/collections, discuss-with-agent.

This order lets **trader consume crypto/markets/geopolitics items early** (after
phases 1–2) while discovery, multi-user, UI, and engagement land afterward.

## Decisions (resolved)

1. **Discovery web search → Brave Search API** (new key).
2. **Cadence → two-tier:** hourly (configurable) lightweight collect feeding a
   dynamic **Headlines** feed; nightly LLM **daily brief**. Per-user notification
   settings (frequency / off) required because of the frequent collect.
3. **Scope → bbv2 stays a general news app** (incl. like / favorites / discuss-
   with-agent). **Trading-specific** features, labels, and signals live in the
   `trader` project, which only consumes bbv2 data.
