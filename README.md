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

**Working end-to-end** (plans `0002`–`0015`). Backend (FastAPI + SQLite) +
a Vite/React dashboard with Firebase auth:

- **Ingestion** — topics → agent source discovery (Brave, capped per topic) →
  collect (RSS, capped per source) into bbv2's own SQLite, deduped, prefixed-ULID
  IDs. An off-topic **LLM relevance quickscan** (xAI Grok, cheap) drops noise.
- **Scheduling** — two decoupled cron jobs: **`bbv2 tick`** (hourly, due-based
  per-topic/source discovery + collection) and **`bbv2 nightly`** (11pm, build
  each subscribed topic's brief + email "your morning brief is ready"). Cadence is
  admin-set per topic (discovery + collection) and per source.
- **Dashboard** — `/headlines` (daily brief + on-demand per-topic rundowns),
  `/chat` (agentic, tool-calling, SSE, markdown), `/stories` (filter + vote +
  save), `/favorites` (folders), `/topics` (create → moderated → SSE provision).
- **Chat agent** — creates or subscribes to topics from chat (`create_topic` /
  `subscribe_topic`), searches/summarizes, and personalizes from a per-turn context
  block (subscriptions, token budget, available topics). First-visit onboarding:
  canned greeting + React-Joyride tour; new users' Headlines populate during setup.
- **Roles + guardrails** — owner-only admin (`ADMIN_EMAILS`); tiered topic
  moderation (validation → keyword → Haiku classifier); domain denylist.
- **Resilience + cost control** — all outbound calls retry with exponential
  backoff (`httpclient`); every inbound route is rate-limited (per-user dashboard,
  per-token consumer); a per-user daily **token budget** (default 100k) covers the
  user's own agent work, while background/shared LLM spend goes to a system bucket.
- **Consumer API** — token-auth read API for service accounts (e.g. `trader`).

Run it: see [`CLAUDE.md`](./CLAUDE.md) for commands (`make dev`), and
[`_documentation/architecture.md`](./_documentation/architecture.md) for the big
picture. Phased design lives in [`_plans/`](./_plans/); backlog + ideas in
[`_documentation/roadmap.md`](./_documentation/roadmap.md).

## Relationship to the original briefbot

A clean-room successor to the original briefbot
(`~/Developer/agent/projects/ai-assistant`) — **tech-only, single-profile, a live
nightly system that must never be modified**. bbv2 **copies and adapts** its
modules and adds multi-user, topics/subscriptions, agent source discovery, roles,
guardrails, and a consumer API. See
[`_documentation/reuse-map.md`](./_documentation/reuse-map.md). bbv2 uses its own
database and never touches the original's.

## Stack

Python 3 · FastAPI + uvicorn · SQLite (WAL, per-thread connections) · feedparser /
beautifulsoup4 / requests · Brave Web Search (discovery) · Anthropic **Claude
Haiku** (prose) + **xAI Grok** (relevance) · firebase-admin (auth) · Vite + React +
TypeScript dashboard (Firebase web SDK, react-markdown, react-joyride) ·
cron/launchd on an always-on host (`bbv2 tick` hourly, `bbv2 nightly` at 11pm).
