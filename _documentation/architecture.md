# bbv2 — Architecture

The big picture for bbv2 as built (plans `0002`–`0015`). For commands see
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
the Vite origin. The dashboard SSE endpoints (chat, provision) run blocking work in
Starlette's threadpool. `Store` hands each thread its **own** SQLite connection
(thread-local, WAL + `busy_timeout`) — a single shared connection is unsafe for
concurrent writes (interleaved commits raise "cannot commit"). `:memory:` (tests)
keeps one shared connection since each connection is a separate in-memory DB.

## Layers (keep them separate)

- **Network** — `fetch.py` (RSS, conditional GET), `discover.py` (site→feed
  autodiscovery), `brave.py` (web search), `llm.py` (Anthropic Haiku **+ xAI Grok**
  `grok_text`). All outbound calls go through `httpclient.request_with_backoff`
  (retry 429/5xx/529 + connection errors, `Retry-After`-aware, backoff + jitter).
  **User-driven/feed-driven fetches** (RSS, discovery, the chat `summarize_article`
  tool) additionally go through `safefetch.safe_get`: an **SSRF guard** that blocks
  hosts resolving to loopback/link-local/private/reserved IPs (incl.
  `169.254.169.254`), re-validates each redirect hop, and caps the response body
  (`BBV2_ALLOW_PRIVATE_FETCH=true` opts out for dev). `models.relevance_generate`
  routes story relevance to Grok (Haiku fallback); prose (chat/briefs) stays Haiku.
- **Persistence** — `store.py` (schema + migrations + core queries) + mixins
  (`store_dashboard`, `store_favorites`, `store_chat`, `store_consumer`,
  `store_usage`, `store_schedule` (cadence/due), `store_cache` (feed/discovery
  cache)). One SQLite DB, own to bbv2. New columns added via idempotent `ALTER` in
  `_migrate`.
- **Pure logic** (no I/O, unit-tested) — `normalize.py`, `score.py`, `cluster.py`,
  `moderation.py`, `relevance.py`, `ratelimit.py`, `denylist.py`, `ids.py`,
  `util.py` (incl. `strip_html`, `titlecase`). `usage.py` (token-budget + metering
  helpers) sits just above this, over `store` + `llm`.
- **Pipelines / orchestration** — `collect.py`, `discovery.py`, `brief.py`,
  `provision.py`, `agent.py`, `digest.py`, `scheduler.py` (the `tick` engine),
  `nightly.py` (briefs + email). `models.py` routes per-task model choice.
- **Entry points** — `cli.py` (`python -m bbv2 …`), `api.py` (consumer),
  `dashboard_api.py` (`/api/*`), `auth.py` (Firebase verify).
- **Frontend** — `dashboard/` (Vite + React + TS, custom CSS tokens).

## Data model (one SQLite DB)

`topics` (+ cadence: `discover_interval_min`, `collect_interval_min`,
`last_discovered_at`, `last_briefed_at`), `sources` (status + `collect_interval_min`,
`last_collected_at`), `topic_sources`, `items` (+ `dedupe_key` UNIQUE),
`item_topics` (+ `relevant`), `feed_cache`, `discovered_feeds`, `api_tokens`
(+ `revoked_at`) + `token_topics`, `users` (role), `subscriptions`,
`user_settings` (+ `onboarded_at`),
`story_feedback`, `briefs` (UNIQUE `topic_id,date` — also the shared rundown cache),
`favorite_folders` + `favorite_links`, `conversations` + `conversation_messages`,
`token_usage` (per-user + `system` (user_id 0) LLM spend).

**IDs:** PKs are prefixed ULIDs (`ids.py`) — `ITM`/`SRC`/`TOP`/`CLU`/`FAV`/`FLD`/
`CON`/`MSG`/`BRF`. Item dedupe is by `dedupe_key` (`url:` / `fallback:`), so the
ULID PK isn't content-derived; `store.upsert_item` returns the canonical id.

## Key flows

- **Collect** (`collect.py`): active sources → `fetch_rss_feed` → `normalize`
  (HTML-stripped title/summary) → `score` → `upsert_item` (dedupe) →
  `map_item_topic` (with `relevant = NULL`, pending review). Capped at
  `MAX_STORIES_PER_SOURCE` (newest-first, default 7) per source; per-item upserts
  are best-effort (a bad item/transient DB error is counted, not fatal).
- **Relevance quickscan** (`review.py` → `relevance.classify_batch`): after
  collect, batches each topic's **pending** items (~20: id + title + blurb) to
  Haiku, which decides which are genuinely on-topic; writes `item_topics.relevant`
  (1/0). Display queries hide `relevant = 0`. Drops the off-topic stories that
  aggregator sources carry. Run as a provision stage and via `bbv2 quickscan`.
- **Discover** (`discovery.py`): topic → Brave queries → site homepages
  (skipping `denylist` domains) → `discover_site_feeds` → candidate sources, capped
  at `MAX_SOURCES_PER_TOPIC` (default 5).
- **Provision** (`provision.py`, user flow): a generator streaming SSE stages
  `discovering → approving → collecting → reviewing → [summarizing] → ready`
  (discover → `approve_all_candidates` → collect → relevance quickscan → optional
  first brief). The caller passes `brief_generate` **only within the user's initial
  setup window** (`store.is_recent_user`, account-age based — reload-proof, default
  24h via `ONBOARD_BRIEF_WINDOW_MIN`) — so every topic added while setting up
  populates the initial Headlines, while later topic-adds defer to nightly +
  on-demand rundowns (no per-add LLM cost). `create_topic` returns `headline_ready`
  so the agent tells the user whether their Headlines is ready now or coming
  overnight. (`onboarded_at`, marked by `/me` on return-with-subscriptions, is now
  only the React-Joyride tour's cross-device guard.) Rate-limited.
- **Tick** (`scheduler.py`, cron **hourly**): decoupled, due-based pull engine —
  per-topic **source discovery** (when `discover_interval_min` due) + per-source
  **collection** (effective interval = source override ?? tightest topic interval
  ?? default) + relevance quickscan of touched topics. Cadence is admin-set;
  nothing runs unless due. Keeps the consumer API (e.g. `trader`'s crypto) fresh.
- **Nightly** (`nightly.py`, cron **11pm**): build briefs for every subscribed
  topic (system-metered), then email each user a v1-style "morning brief ready"
  link. Decoupled from `tick` — it just reads what was collected.
- **Brief** (`brief.py`): recent items → `cluster_items` (trending) + top stories
  → one Haiku call → `{title, summary}` → `briefs` table (UNIQUE `topic_id,date`).
  Run by nightly, admin button, or `bbv2 brief`.
- **Rundown** (`brief.get_or_build_brief`): on-demand per-topic summary built
  **once per `(topic,date)`** and **shared** — the first visitor that day triggers
  it (`POST /api/topics/{slug}/rundown`, system-metered); everyone after reads the
  cache. Headlines shows it atop a topic tab.
- **Headlines** (`pages/Headlines.tsx`, 0017): tabs are the user's **topics** (no
  "Today" aggregate). A left **date rail** lists the **last 10 calendar days**
  (`GET /api/topics/{slug}/briefs`, read-only — never builds); each day with a
  brief shows `MMM D, YYYY — <title…>` and is selectable, empty days render
  disabled. Selecting a day shows that day's brief (title + summary only — the
  trending/sources lists were dropped as redundant with the story list) and **only
  that day's stories** (`/stories` with a `from`/`to` day window). Today is built
  on demand via the rundown endpoint.
- **Onboarding** (first visit): the user lands on `/chat` with a canned Briefbot
  intro, names a topic (→ `create_topic`), and Headlines hydrates. The React-Joyride
  tour shows once per browser (localStorage); `user_settings.onboarded_at` is the
  separate **brief-gate** — marked by `/me` only once the user returns with
  subscriptions, so every topic added during the first session builds the brief.
- **Chat** (`agent.py`, schemas in `agent_tools.py`): Haiku tool-use loop (≤8
  iters) over per-user tools (search/trending/summarize/favorites + **`create_topic`**
  + **`subscribe_topic`** for existing topics), streamed as SSE
  (token/tool_start/tool_end/**topic_stage**/title/done). Each turn the system
  prompt is augmented with a **context block** (`_context_block`: subscriptions,
  token used/limit, other available topics) so the agent personalizes — onboarding
  a subscription-less user or discussing/suggesting topics for a subscribed one. A
  canned **`GREETING`** (served via `/me`) shows on the first-ever chat and is
  prepended to the agent's context on the first message. `create_topic`
  (confirm-first) moderates + creates a topic then drives `provision_topic`,
  streaming `topic_stage` events and auto-subscribing on `ready`. Assistant
  messages render as **markdown** in the UI. Every model call is metered (Token budget).
- **Token budget** (`usage.py` + `store_usage`): every Anthropic call records a
  `token_usage` row per user; `budget_status` enforces a rolling daily window with
  two tiers — **chat blocks at 50k**, **all LLM actions block at 75k** (env-
  overridable). Gated in `run_chat_turn` (chat tier) and on topic-create / provision
  (all tier → 429). `GET /api/usage` feeds the chat-sidebar counter.
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
  slugs; read-only; rate-limited per token (`/health` exempt). Revocable via
  `bbv2 token revoke <label|token>` (sets `revoked_at`; revoked tokens fail auth).
- **CORS + bind are env-driven** for the Tailscale family deploy: `ALLOWED_ORIGINS`
  (explicit allowlist, never `*` with credentials) and `BBV2_SERVE_HOST`. Logs from
  the unattended `tick`/`nightly` cron go to `BBV2_LOG_DIR` via the `logging` module
  (configured in `cli.main`).

## Frontend

`AppShell` (nav + theme) wraps routes: `/headlines` (tabbed brief), `/chat`,
`/stories`, `/favorites`, `/topics` (user flow), `/admin/topics*` (admin-gated).
State: Zustand (`auth`, `toasts`, theme, `headlinesNav`). Theme tokens in
`theme.ts` → injected CSS vars. **Below the tablet breakpoint (≤768px)** the
topbar collapses to a **hamburger menu** (+ theme toggle): main nav · a dynamic
section (the Headlines topic tabs when on `/headlines`, via the shared
`headlinesNav` store) · settings + sign-out. The page never scrolls horizontally
(long text wraps; only the Headlines date rail scrolls sideways). SSE (chat + provision) is consumed via `fetch` +
`ReadableStream` (`api.streamSSE`) so the Firebase bearer header can be attached.
**MUI** (`@mui/icons-material`) is used **selectively for icons** (nav, buttons,
thumbs/star, chat user/agent avatars) — layout/theme stays custom CSS. A shared
`StoryRow` (thumbs up/down + save) renders stories on Stories and Headlines; a
shared `ProvisionPipeline` renders the provisioning stages on **both** the Topics
page and inside the chat thread (when the agent runs `create_topic`). The chat
sidebar shows a usage counter (interactions + tokens vs. the daily budget).
First-visit **onboarding** (`OnboardingTour`, react-joyride) gates on `me.onboarded`,
lands the user on `/chat` with a canned Briefbot intro, and walks the nav; admins
get per-topic/source **cadence** controls on the topic-detail page. Each page
(Headlines/Stories/Topics/Favorites) also has its own **one-time Joyride
walkthrough** (`PageTour` + `lib/tours`, gated per-page in localStorage),
relaunchable from a subtle ⓘ button by the page title.

## Conventions / invariants

- **og briefbot is never modified**; bbv2 owns its DB. Copy code one-directional.
- **Names are Title-cased** at storage (topics, folders); **feed summaries are
  HTML-stripped** at ingest; user input is sanitized (slug regex / `sanitize_name`).
- **LLM = Claude Haiku** for prose (chat, briefs, rundowns, moderation); **xAI
  Grok** for story relevance classification (cheap, high-volume; Haiku fallback).
  `ANTHROPIC_API_KEY` required; `GROK_API_KEY` optional. **Every call is metered**
  to `token_usage`. A **single per-user daily budget** (default 100k, `usage.py`)
  counts the user's own agent work **+ the provisioning they initiate**; all
  background/shared work (tick, nightly, rundowns) is metered to the **`system`
  bucket** (`SYSTEM_USER_ID = 0`) and never charged to a user.
- **Rate-limit in, back off out.** Every dashboard route is rate-limited per user
  (router-wide default + tighter chat) and every consumer route per token
  (`/health` exempt); every outbound call retries with exponential backoff
  (`httpclient`). Limits/backoff are env-tunable. The limiter is in-memory,
  single-process (one `bbv2 serve`).
- **600-line cap** per source file (split into modules/mixins as they grow).
- Tests run **offline** — LLM/search/fetch are injected; SSE/agent/brief/moderation
  take stubbed generators.

## Deployment

Production runs on a home **Proxmox VM** behind **Tailscale** — `systemd` (the
`bbv2` uvicorn service) ← `nginx` (serves the built dashboard + proxies `/api`) ←
`tailscale serve` (HTTPS on the tailnet), with `cron` driving `bbv2 tick`/`nightly`.
Code ships via **push-to-`main` CI/CD** (a self-hosted GitHub Actions runner on the
VM rebuilds + restarts). The full topology, config/secrets, ops runbook, and
provisioning history live in **[`devops.md`](./devops.md)**.
