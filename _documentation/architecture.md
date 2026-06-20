# bbv2 — Architecture

The big picture for bbv2 as built (plans `0002`–`0009`). For commands see
[`../CLAUDE.md`](../CLAUDE.md); for phased design see [`../_plans/`](../_plans/).

## Shape

A Python backend (FastAPI + SQLite, own DB) feeds two HTTP surfaces, plus a
React/TS dashboard:

```
  cron / CLI ──▶ collect ──▶ SQLite (WAL)
                               │
   ┌───────────────────────────┼──────────────────────────┐
   ▼                           ▼                            ▼
 consumer API (api.py)    dashboard API (dashboard_api.py)  dashboard (Vite/React)
 service-token, read      Firebase ID token, read+write     talks to /api/*
 /health /topics /items   /api/*                            Headlines/Chat/Stories/
                                                            Favorites/Topics/Admin
```

Both APIs are served by one `bbv2 serve` process (`cli.cmd_serve`): the
service-token consumer app plus the Firebase-auth dashboard routes, with CORS for
the Vite origin. The dashboard SSE endpoints (chat, provision) run blocking work
in Starlette's threadpool over one shared `Store(check_same_thread=False)` (WAL).

## Layers (keep them separate)

- **Network** — `fetch.py` (RSS, conditional GET), `discover.py` (site→feed
  autodiscovery), `brave.py` (web search), `llm.py` (Anthropic Haiku).
- **Persistence** — `store.py` (schema + core queries) + mixins
  (`store_dashboard`, `store_favorites`, `store_chat`). One SQLite DB, own to bbv2.
- **Pure logic** (no I/O, unit-tested) — `normalize.py`, `score.py`, `cluster.py`,
  `moderation.py`, `relevance.py`, `ratelimit.py`, `denylist.py`, `ids.py`,
  `util.py` (incl. `strip_html`, `titlecase`).
- **Pipelines / orchestration** — `collect.py`, `discovery.py`, `brief.py`,
  `provision.py`, `agent.py`, `digest.py`.
- **Entry points** — `cli.py` (`python -m bbv2 …`), `api.py` (consumer),
  `dashboard_api.py` (`/api/*`), `auth.py` (Firebase verify).
- **Frontend** — `dashboard/` (Vite + React + TS, custom CSS tokens).

## Data model (one SQLite DB)

`topics`, `sources` (status: candidate/active/rejected), `topic_sources`,
`items` (+ `dedupe_key` UNIQUE), `item_topics`, `feed_cache`, `discovered_feeds`,
`api_tokens` + `token_topics`, `users` (role), `subscriptions`, `user_settings`,
`story_feedback`, `briefs`, `favorite_folders` + `favorite_links`,
`conversations` + `conversation_messages`.

**IDs:** PKs are prefixed ULIDs (`ids.py`) — `ITM`/`SRC`/`TOP`/`CLU`/`FAV`/`FLD`/
`CON`/`MSG`/`BRF`. Item dedupe is by `dedupe_key` (`url:` / `fallback:`), so the
ULID PK isn't content-derived; `store.upsert_item` returns the canonical id.

## Key flows

- **Collect** (`collect.py`): active sources → `fetch_rss_feed` → `normalize`
  (HTML-stripped title/summary) → `score` → **relevance filter** (`relevance.py`:
  keep an item for a topic only if it matches that topic's keywords — the name
  plus an LLM-expanded set in `topics.keywords_json`) → `upsert_item` (dedupe) →
  `map_item_topic`. Drops off-topic stories that aggregator sources carry.
- **Discover** (`discovery.py`): topic → Brave queries → site homepages
  (skipping `denylist` domains) → `discover_site_feeds` → candidate sources.
- **Provision** (`provision.py`, user flow): a generator streaming SSE stages
  `discovering → approving → collecting → ready` (discover → `approve_all_candidates`
  → collect). Rate-limited.
- **Brief** (`brief.py`): recent items → `cluster_items` (trending) + top stories
  → one Haiku call → `{title, summary}` → `briefs` table. Run via admin button or
  `bbv2 brief`.
- **Chat** (`agent.py`): Haiku tool-use loop (≤8 iters) over per-user tools
  (search/trending/summarize/favorites), streamed as SSE
  (token/tool_start/tool_end/title/done). Conversations persisted per user.
- **Moderation** (`moderation.py`, at topic create): `validate_slug` +
  `sanitize_name` → keyword denylist → Haiku classifier (injection-hardened,
  allowlists infosec, fail-closed). Denied topics are never persisted.

## Auth & roles

- **Dashboard:** client Firebase ID token → `auth.verify_token`
  (`firebase-admin`, clock-skew 10s) → `dashboard_api.current_user` auto-provisions
  the user (upsert by email) and returns `role`.
- **Owner-only admin:** `current_user` sets `role='admin'` **only** on an
  `ADMIN_EMAILS` (env) match — there is no API/UI/CLI to promote. `require_admin`
  403-gates the curation routes (discover/approve/reject/sources/collect/brief);
  the frontend hides `/admin` and guards the route.
- **Per-user scoping:** stories/headlines are scoped to subscriptions; favorites
  and conversations are per user.
- **Consumer API:** opaque service tokens (`bbv2 token create`) scoped to topic
  slugs; read-only.

## Frontend

`AppShell` (nav + theme) wraps routes: `/headlines` (tabbed brief), `/chat`,
`/stories`, `/favorites`, `/topics` (user flow), `/admin/topics*` (admin-gated).
State: Zustand (`auth`, `toasts`, theme). Theme tokens in `theme.ts` →
injected CSS vars. SSE (chat + provision) is consumed via `fetch` +
`ReadableStream` (`api.streamSSE`) so the Firebase bearer header can be attached.
**MUI** (`@mui/icons-material`) is used **selectively for icons** (nav, buttons,
thumbs/star) — layout/theme stays custom CSS. A shared `StoryRow` (thumbs
up/down + save) renders stories on Stories and Headlines.

## Conventions / invariants

- **og briefbot is never modified**; bbv2 owns its DB. Copy code one-directional.
- **Names are Title-cased** at storage (topics, folders); **feed summaries are
  HTML-stripped** at ingest; user input is sanitized (slug regex / `sanitize_name`).
- **LLM = Claude Haiku** everywhere; live LLM calls are user-invoked (brief, chat,
  moderation). `ANTHROPIC_API_KEY` required for those.
- **600-line cap** per source file (split into modules/mixins as they grow).
- Tests run **offline** — LLM/search/fetch are injected; SSE/agent/brief/moderation
  take stubbed generators.
