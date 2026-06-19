# Reuse map — original briefbot → bbv2

bbv2 reuses the original briefbot by **copying and adapting** modules. The
original lives at `~/Developer/agent/projects/ai-assistant` and is a **live
nightly system — never modify it.** Copy files out, adapt in bbv2.

Original package: `briefbot/` (Python). Stack: FastAPI, SQLite/WAL, feedparser,
beautifulsoup4, requests, pydantic, PyYAML, RapidFuzz, Anthropic LLM, Vite
dashboard, launchd cron.

## Modules

| Original module | bbv2 verdict | Notes |
|---|---|---|
| `util.py` | **copy as-is** | time/json/dir helpers |
| `fetch.py` | **copy** | feed/site fetching with ETag/Last-Modified |
| `normalize.py` | **copy** | item normalization |
| `discover.py` | **copy + adapt** | RSS/Atom autodiscovery from a site URL; reused inside agent discovery. Adapted for precision: require a feed MIME type on `rel=alternate`, and require a feed-like response on path probes |
| `store.py` | **copy + adapt** | keep items/feed_cache/discovered_feeds; **add** users, topics, sources, topic_sources, subscriptions, item_topics, api_tokens |
| `score.py` | **copy + adapt** | ranking; revisit weights per topic |
| `config.py` | **adapt** | env/config; sources move from `sources.yaml` → DB (topics/sources tables) |
| `cli.py` | **adapt** | new commands: topics, sources, discover, subscribe, serve |
| `llm.py` | **copy + adapt** | Anthropic wrapper; reused for discovery reasoning + summaries |
| `cluster.py` | **copy (later)** | storyline clustering for radar views |
| `topics.py` | **reference (later)** | NOTE: original "topics" = rolling keyword *profiles*, **not** our first-class subscription topics — different concept, don't confuse |
| `brief.py`, `executive.py`, `export.py` | **copy + adapt (later)** | per-user daily briefs/digests (phase 6) |
| `opportunity.py`, `resolve.py`, `article.py` | **copy + adapt (later)** | article fetch/extract + opportunity scoring |
| `watchlist.py` | **maybe repurpose** | keyword watchlist → could back per-user keyword alerts |
| `dashboard/` (FastAPI + Vite) | **copy scaffolding (later)** | new UI for topic mgmt + source approval + Headlines; also home of the engagement features (like / favorites / discuss-with-agent via the `/ask` flow) |
| email/mailgun notification (in nightly flow) | **copy + adapt** | send to **each user's** address, not just one; gated by `user_settings` |
| `nightly_briefbot.sh`, `scripts/*launchd*` | **adapt** | two-tier scheduling on the server: hourly collect + nightly brief |

## New in bbv2 (no original to copy)

- **Multi-user model** — users, subscriptions, per-topic visibility scoping.
- **Agent source discovery** — topic → LLM + web search → candidate sources →
  human approval (the original only autodiscovers a feed from a *known* site).
- **Consumer API** — token-auth read API for service accounts (e.g. `trader`).
- **Service accounts** — non-human accounts that subscribe to topics and pull
  via the API.

## Hard rules

- Copying is one-directional: **original → bbv2**. Never edit the original project.
- **bbv2 uses its own database.** Never open, read, or connect to og briefbot's
  DB. We copy *code* and adapt it; data and runtime stay fully separate.
