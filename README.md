# briefbot (bbv2)

A small, multi-user, **topic-driven news-intelligence platform**. Create topics
you care about; an agent web-searches to propose **sources** for each; ingestion
collects them into a shared, deduped archive. Each user sees only items from
topics they subscribe to, reads a daily **brief**, browses **stories**, saves
**favorites**, and can **chat** with an agent over their archive. A token-
authenticated **consumer API** lets other apps (e.g. the `trader` project) pull
items by topic.

Scale: personal — a handful of accounts (me, family). Not a public SaaS.

## Status

**Working end-to-end** (plans `0002`–`0009`). Backend (FastAPI + SQLite) +
a Vite/React dashboard with Firebase auth:

- **Ingestion** — topics → agent source discovery (Brave) → collect (RSS) into
  bbv2's own SQLite, deduped, prefixed-ULID IDs.
- **Dashboard** — `/headlines` (daily Haiku brief: title + summary + trending +
  sources), `/chat` (agentic Haiku, tool-calling, SSE), `/stories` (filter +
  vote + save), `/favorites` (folders), `/topics` (create → moderated → SSE
  provision pipeline → subscribe).
- **Roles + guardrails** — owner-only admin (`ADMIN_EMAILS`); tiered topic
  moderation (validation → keyword → Haiku classifier), per-user rate limits,
  domain denylist.
- **Consumer API** — token-auth read API for service accounts.

Run it: see [`CLAUDE.md`](./CLAUDE.md) for commands (`make dev`), and
[`_documentation/architecture.md`](./_documentation/architecture.md) for the big
picture. Phased design lives in [`_plans/`](./_plans/).

## Relationship to the original briefbot

A clean-room successor to the original briefbot
(`~/Developer/agent/projects/ai-assistant`) — **tech-only, single-profile, a live
nightly system that must never be modified**. bbv2 **copies and adapts** its
modules and adds multi-user, topics/subscriptions, agent source discovery, roles,
guardrails, and a consumer API. See
[`_documentation/reuse-map.md`](./_documentation/reuse-map.md). bbv2 uses its own
database and never touches the original's.

## Stack

Python 3 · FastAPI + uvicorn · SQLite (WAL) · feedparser / beautifulsoup4 /
requests · Brave Web Search (discovery) · Anthropic **Claude Haiku** (briefs,
chat, moderation) · firebase-admin (auth) · Vite + React + TypeScript dashboard
(Firebase web SDK) · cron/launchd on an always-on host.
