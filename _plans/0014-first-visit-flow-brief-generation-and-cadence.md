# 0014 — Onboarding, nightly brief + email, on-demand rundowns, decoupled collection cadence

**Status:** ✅ Implemented (2026-06-20)
**Date:** 2026-06-20
**Phase:** Build · **Depends on:** [0012](./0012-chat-topic-creation-and-token-budget.md) (create_topic + token budget), [0013](./0013-rate-limiting-and-backoff.md)

> **Shipped (all phases):** P0 single per-user budget (100k/day, hard tier dropped)
> + `system` usage bucket (`SYSTEM_USER_ID`) for background/shared spend ·
> per-task **model router** (`models.relevance_generate`) → xAI **Grok** for story
> relevance (`grok_text`, OpenAI-compatible, Haiku fallback) · **cadence** schema
> (per-topic discover/collect intervals, per-source collect override) + the
> decoupled **`bbv2 tick`** engine (due-based discovery/collection/quickscan,
> hourly) · **`bbv2 nightly`** (briefs for subscribed topics → v1-style "brief
> ready" email, 11pm) · on-demand **shared rundown** (`get_or_build_brief`,
> build-once-per-`(topic,date)`, `POST /api/topics/{slug}/rundown`) · **onboarding**
> (`onboarded_at`, `/me` flag, `POST /api/me/onboarded`, React-Joyride tour +
> canned chat intro) · admin cadence API/UI (`PATCH .../cadence`). 98 pytest pass;
> dashboard build clean. `store.py`/`dashboard_api.py` split (`store_cache`,
> `store_schedule`, `dashboard_favorites`) to hold the 600-line cap.

## Problem

A first-time user lands on an **empty app** — no headlines, no summary — even
after creating/subscribing to a topic, because **briefs are the only thing
Headlines renders** and nothing generates one automatically (only the admin button
/ `bbv2 brief`). Separately, **collection has no cadence control**: `bbv2 collect`
pulls all active sources whenever external cron runs it, so we can't pull crypto
intraday (for the `trader` consumer) while pulling dog-news daily.

## The model

Four independent mechanisms, each with its own trigger. **Data pulls are fully
decoupled from briefs.**

### 1. Decoupled data-pull engine — `bbv2 tick` (frequent cron)

A new idempotent command run by external cron/launchd **hourly** (the finest
collection cadence we expose). Each tick does **due-based** work driven by per-
topic/per-source admin cadences — nothing runs unless it's due, so most ticks are
cheap:

- **Source discovery (per topic):** if a topic's `last_discovered_at` is older than
  its `discover_interval_min`, run discovery for it. (e.g. crypto weekly, Tech News
  monthly.)
- **Story collection (per source, with per-topic default):** if a source's
  `last_collected_at` is older than its **effective** collect interval, pull it +
  quickscan the affected topics. (e.g. crypto Source A hourly, Source B daily; Tech
  News collect daily.)

This is the engine that keeps the archive fresh; the **`trader` app consumes the
crypto topic (and maybe a couple others) via the consumer API**, kept fresh by
setting crypto's collection cadence tight.

**Effective collect interval for a source** = `sources.collect_interval_min`
?? **tightest** `topics.collect_interval_min` among its topics ?? global default.
(A feed shared by crypto + dog-news pulls at the tighter cadence — freshness wins.)

### 1b. Per-task model routing — cheap model for relevance (cost control)

The relevance review (`relevance.classify_batch`, "is this story about the topic?")
is the **highest-volume recurring LLM call** — it runs on every collect, per source,
per new story. It's also the **least quality-sensitive** (binary on-topic/off-topic).
So route it to a **cheaper model** while keeping Anthropic Haiku for user-facing prose.

- Add a thin **per-task model router**: tasks pick a `(provider, model)` by env, not
  a single global model. Prose (chat, briefs/rundowns) → **Haiku**; relevance
  classification (and other cheap structured calls, e.g. keyword expansion) → a cheap
  **xAI Grok** tier (`GROK_API_KEY`; xAI is OpenAI-compatible, so a small client
  reusing the 0013 `httpclient` backoff). Exact Grok model id + price confirmed at
  build time.
- **Fallback:** if Grok errors/unset, fall back to Haiku so collection never breaks.
- `classify_batch` already takes an injectable `generate`, so this is a localized
  change — the router supplies the relevance `generate`.
- Cost is further bounded by: classify only **new** pending items, batch ~20, and
  hourly **due-based** ticks (only crypto-frequent sources run often).

Config: `RELEVANCE_PROVIDER` / `RELEVANCE_MODEL` (default Grok cheap tier),
`GROK_API_KEY`, with Anthropic the default everywhere else.

### 2. Nightly brief + email — `bbv2 nightly` (once a night)

Decoupled from the pull engine: it just reads whatever the tick engine has
collected that day. Each night, for **every topic that has ≥1 subscriber**:

- Build the topic's brief for the coming morning from **that day's stories**
  (`build_brief`, which already skips topics with no recent items).
- Then **email each user** "your morning brief is ready" with a link to
  `/headlines` — same as briefbot v1's morning email. Reuses `digest.py` /
  `notify.py` / Mailgun (`mailgun_config`), retargeted from item-digests to a
  brief-ready notification.

So users wake up to a populated Headlines page + an email pointing at it.

### 3. On-demand topic rundown — generated once per topic/day, shared

The Headlines brief and a topic's "rundown" are the **same per-topic-per-day
artifact** (the `briefs` row, keyed `UNIQUE(topic_id, date)`), with two triggers:
nightly pre-generation (above) and **lazy on first visit**.

- When a user opens a topic that has **no summary for today**, synthesize one from
  the **top N articles of that day** (one Haiku call) — the user waits a moment
  (show a "Synthesizing today's rundown…" `LoadingBanner` state).
- **Cache + share:** it's stored per-topic-per-day, so **User A's first visit
  generates it; User B (same topic, later) just reads the cached rundown** — no
  regeneration, regardless of who triggered it. Never regenerated on navigate-away-
  and-back.
- Idempotent: check-then-build on `(topic_id, today)`. Nightly pre-gen means most
  visits never wait.

### 4. First-visit onboarding — agent-led tour (React Joyride)

Gated by a per-user flag (`user_settings.onboarded_at`). On a user's **first
visit** only:

- **Start on `/chat`** (all pages stay — `/headlines`, `/chat`, `/stories`,
  `/topics`, `/favorites`).
- **Agent intro (canned, no LLM call):** Briefbot introduces itself — this is a
  news app; tell it what you want to follow; it can create topics, search stories,
  summarize articles/papers; **anything the site can do, the agent can do.**
- **Guided tour via React Joyride:** scripted steps walking through each page (what
  Headlines/Chat/Stories/Topics/Favorites are for). Copy is **scripted** (reliable,
  zero token cost), not LLM-generated.
- **User names a topic** → the existing **`create_topic` tool (0012)** runs the
  discover→approve→collect→review pipeline (streamed into chat) + auto-subscribes.
- **On completion, generate that topic's brief** so `/headlines` is **hydrated**
  immediately.
- **Mark onboarded** (`onboarded_at`). Returning users skip the tour and land
  normally.

## Data / schema (idempotent `_migrate` ALTERs)

- `topics.discover_interval_min INTEGER` · `topics.last_discovered_at TEXT` — per-
  topic source-discovery cadence.
- `topics.collect_interval_min INTEGER` — per-topic default story-collection cadence.
- `sources.collect_interval_min INTEGER` (override) · `sources.last_collected_at TEXT`.
- `user_settings.onboarded_at TEXT` — onboarding gate.
- Briefs/rundowns reuse the existing `briefs` table (`UNIQUE(topic_id, date)`) —
  the shared-cache key. No per-user brief copies.

## Triggers, summarized

| Surface | Trigger | Scope | Repeat? |
|---|---|---|---|
| Source discovery | `bbv2 tick` when due | per topic | per `discover_interval_min` |
| Story collection | `bbv2 tick` when due | per source (topic default) | per effective interval |
| Daily brief + email | `bbv2 nightly` | per subscribed topic / per user email | nightly |
| Topic rundown | first visit w/o today's summary | per topic/day, **shared** | once/day |
| Onboarding brief | after first topic provisions | the new topic | once |
| Manual | admin button / `bbv2 brief` | per topic | on demand |

Two cron entries, decoupled: **`bbv2 tick`** (hourly: discovery + collection) and
**`bbv2 nightly`** (11pm: briefs + emails). Keeps the single-process CLI+cron model
(0013) — no in-process scheduler thread.

## Admin cadence — API + UI

- `PATCH /api/topics/{slug}/cadence` (admin) — `{discover_interval_min,
  collect_interval_min}`.
- `PATCH /api/sources/{id}/cadence` (admin) — `{collect_interval_min}`.
- Surface `last_discovered_at` / `last_collected_at` (read-only) for visibility.
- **UI** on `/admin/topics` + the sources screen: per-topic discovery + collection
  cadence, per-source collection override, with named **presets** (Hourly=60,
  Daily=1440, Weekly=10080, Monthly≈43200) and env-overridable defaults
  (`DISCOVER_INTERVAL_MIN_DEFAULT`, `COLLECT_INTERVAL_MIN_DEFAULT`). Owner-only
  admin (0009); non-admins never see these.

## Frontend pieces

- **Onboarding gate:** `/me` exposes `onboarded`; false → route to `/chat`, inject
  the canned intro message, start the Joyride tour; `POST /api/me/onboarded` on
  finish.
- **Canned intro:** a scripted first assistant message in the thread (not a server
  LLM turn) — instant + free.
- **Rundown:** on the topic view, fetch-or-build the rundown once; "Synthesizing
  today's rundown…" state while it builds; cached for everyone after.
- **Empty states:** before any brief exists, Headlines shows "Your briefing is
  being prepared," not a blank page.

## Backend pieces

- `bbv2 tick`: due-based discovery + collection (refactor `collect` to pull a
  due-set of sources; add `discover` due-check per topic).
- `bbv2 nightly`: briefs for subscribed topics → per-user "brief ready" email.
- `POST /api/topics/{slug}/rundown` (build-once-then-cache; any authed user;
  metered) and brief surfaced via existing `/briefs`.
- `onboarded` on `/me` + `POST /api/me/onboarded`.

## Token accounting — user budget vs system bucket (revises 0012)

A single per-user **daily budget of 100k tokens** (was 50k; the 0012 "block
everything at 75k" hard tier is **dropped**). What counts against it:

- **User-driven work** → the initiating user's budget:
  - Agent chat turns + agent tasks (search, summarize, etc.).
  - **`create_topic` and its full pipeline** (discovery + relevance review) — and
    Topics-page provisioning — are **charged to the user who initiated them**.
- **System / background work** → a `system` bucket, charged to no user:
  - Scheduled `bbv2 tick` (collection + discovery) and `bbv2 nightly` (briefs +
    emails) — no user initiated them.
  - **On-demand rundowns** — a *shared* per-topic/day artifact (User A's visit
    generates it, everyone else reads the cache), so the unlucky first viewer is
    **not** personally charged; it's `system`.

Implementation (revises 0012):

- **Drop the hard tier.** One limit, env default `TOKEN_CHAT_LIMIT=100_000`;
  remove `TOKEN_HARD_LIMIT` and the "all"-tier gate on create/provision.
- `record_usage` gains a `system` owner (sentinel `user_id`, e.g. `0`).
  Background/shared paths record there; user-initiated provisioning keeps recording
  to the user (as 0012 already does).
- `budget_status` sums a user's chat/task/**provision** purposes against the single
  limit. The `system` bucket is tracked for **total-bill visibility** (and can get
  its own cap later) but never blocks a user.
- Note: the budget is a **token count**, provider-agnostic — Grok's (cheaper)
  relevance tokens count 1:1 like Haiku's. Fine at 100k/day for occasional
  user-initiated provisioning; could weight by provider cost later if needed.

## Phasing

- **P1 — onboarding + first brief:** onboarding gate + `/chat` canned intro +
  Joyride tour + generate brief after the first topic provisions → Headlines
  populates. Kills the blank-app experience.
- **P2 — nightly brief + email:** `bbv2 nightly` + per-user "brief ready" email
  (reuse digest/Mailgun) + cron entry.
- **P3 — on-demand shared rundown:** build-once-cache per `(topic, date)`.
- **P4 — decoupled collection cadence + model router:** schema, effective-interval
  logic, `bbv2 tick`, admin cadence API + UI (discovery per topic; collection per
  source/topic), and the per-task model router (Grok relevance + Haiku fallback).
- **P0 (alongside P1) — system usage bucket:** route background/pipeline LLM spend
  off the user budget (revises 0012) before the heavier P2–P4 system calls land.

## Resolved decisions

1. **Tutorial library = React Joyride.**
2. **Collection cadence is in scope** (P4), decoupled from briefs: per-topic source
   discovery + per-source/per-topic story collection.
3. **Nightly brief = per subscribed topic**; email per user (v1-style).
4. **Rundown = the per-topic/day brief, shared** (first viewer generates, others
   reuse).
5. **Schedule:** `bbv2 nightly` @ 11pm, `bbv2 tick` hourly.
6. **Cheap model for relevance:** xAI Grok for `classify_batch` (Haiku fallback);
   prose stays Haiku. Per-task model router.
7. **Single user budget = 100k/day** (drop the 75k hard tier). Counts the user's
   agent chat + agent tasks **+ their own `create_topic`/provision pipeline**.
   `system` bucket (no user charged) = scheduled tick collection/discovery, nightly
   briefs/emails, and shared on-demand rundowns. Revises 0012.

## Schedule (confirmed)

- **`bbv2 nightly` at 11pm** host time (configurable) — briefs + "brief ready" email.
- **`bbv2 tick` hourly** (configurable) — due-based discovery + collection. Hourly
  is the finest collection cadence we expose (matches "pull Source A every hour").
- Rundown "top N" ≈ the current brief's `TOP_STORIES`.
- Relevance review → cheap Grok tier; prose (chat/briefs) → Haiku.
- System/background LLM spend → `system` bucket, not any user's budget.

## Persistent clusters — the companion workstream (its own plan)

Brief/rundown quality and personalization both hinge on **persistent clusters**.
Today `cluster.py` computes clusters **ephemerally** per brief (for "trending").
Promoting them into tables unlocks what this plan leans on:

- **Story selection** for briefs/rundowns by storyline (top clusters of the day),
  not just per-item score — better "top N" and a real "what's trending" signal.
- **What a user cares about** — cluster engagement (votes/saves/opens) per user →
  personalized brief ordering and, later, recommendations.
- **Trending** across a topic/day as a first-class, queryable thing.

Treat this as a **parallel plan** (promote `cluster.py` → `clusters` /
`item_clusters` tables, recompute on tick/nightly). 0014 ships against ephemeral
clusters first; story-selection + personalization improve once clusters persist.

## Out of scope / later

- Per-**user** brief *copies* (briefs stay per-topic, shared); personalization is
  ordering/selection on top of shared briefs, via clusters.
- Semantic ranking / embeddings for story selection (roadmap).
