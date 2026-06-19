# briefbot (bbv2)

A small, multi-user, **topic-driven news-intelligence platform**. Pick topics you
care about; an agent web-searches to propose **sources** for each; you approve
them; ingestion runs on a cron into a shared, deduped archive. Each user sees only
items from topics they subscribe to. A token-authenticated **consumer API** lets
other apps (e.g. the `trader` project) pull items by topic.

Scale: personal — a handful of accounts (me, family). Not a public SaaS.

## Status

**Ingestion core working** (plan 0002): seed a topic + sources via CLI and run a
collect into bbv2's own SQLite. See [`CLAUDE.md`](./CLAUDE.md) for commands and
[`_plans/`](./_plans/) for design + phases.

## Relationship to the original briefbot

This is a clean-room successor to the original briefbot
(`~/Developer/agent/projects/ai-assistant`), which is **tech-only, single-profile,
and a live nightly system that must not be modified**. bbv2 **copies and adapts**
its modules and adds multi-user, topics/subscriptions, agent-driven source
discovery, and a consumer API. See
[`_documentation/reuse-map.md`](./_documentation/reuse-map.md).

## Stack (planned)

Python 3 · FastAPI · SQLite (WAL) · feedparser / beautifulsoup4 / requests ·
Anthropic (LLM) · a web-search backend for discovery · Vite dashboard (later) ·
cron on an always-on host.
