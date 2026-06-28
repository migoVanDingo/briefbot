# 0021 — Admin metrics dashboard (LLM cost + user engagement)

**Status:** ✅ Implemented (2026-06-22) — backend + Admin → Metrics UI; 157 backend
pytest pass, dashboard tsc/build clean.
**Phase:** Build · **Depends on:** 0019 (RBAC + auth_events + last_login), 0012/0014
(token metering). **Sibling:** [0020 scheduling](./0020-topic-scheduling-config.md).

## Implementation notes / deviations

- **Per-topic attribution covers the relevance quickscan** (Grok — the spend you
  flagged), metered per topic in the scheduler. Brief/rundown/moderation spend is
  recorded with `topic_id=NULL` (counted in totals + by-model + by-day, bucketed
  under "(background)" in by-topic) — full per-topic brief attribution is a small
  follow-up if wanted.
- **Cost is estimated** from `config.llm_prices()` (env-overridable USD/1M);
  `usage.estimate_cost` maps grok→grok price, everything else→haiku. MTD-style
  range (7/30/90d) + a vs-prior-period trend (rising cost shows red).
- **Click beacon**: `story_clicks` table + `POST /api/stories/click` (204);
  `StoryRow` fires `fetch(keepalive)` on link click — best-effort, won't catch
  middle-click/copy-link.
- Metrics routes in `bbv2/dashboard_metrics.py` + `store_metrics.py`; gated by the
  new `metrics:read` capability (owner/admin).

An **Admin → Metrics** tab with two sections: **(A) LLM cost** — a ballpark of
Grok/Haiku spend so the owner can see costs trending up, broken down per model /
topic / day / purpose; and **(B) User engagement** — usage by user (tokens, topics
followed, stories clicked, votes, saves, last seen). Admin-only.

## What already exists (extend, don't rebuild)

- `token_usage` logs **every** Haiku/Grok call: `user_id` (or `0` = system bucket),
  `purpose`, `model`, `input_tokens`, `output_tokens`, `created_at`
  (`usage.meter_usage` → `store.record_usage`). The Grok review spend is here
  (purpose `relevance`, system bucket).
- `users.last_login_at`, `auth_events`, `subscriptions`, `story_feedback`,
  `favorite_links`, `conversations` — all per-user signal already.

## Honest constraint (cost)

xAI/Anthropic expose **no billing API**, so cost is an **estimate** =
`tokens × price-per-1M` from configurable price constants — a **month-to-date
ballpark + trend**, not an invoice. No manual bill entry (per your call); the
goal is "is my Grok spend creeping up?", which token volume answers well.

## What this is NOT

- Not real-time billing or an xAI invoice mirror.
- Not per-user cost attribution for *background* work (system-bucket LLM spend
  isn't any user's — it's reported under "system", not divided across users).

## Decisions (confirmed 2026-06-22)

1. **Estimated cost** from `config` price constants (env-overridable; defaults to
   current public Grok/Haiku prices). Show MTD spend + a this-week-vs-last trend.
2. **`stories clicked` needs new instrumentation** — a fire-and-forget click beacon
   (the only metric not already in a table).
3. **New capability `metrics:read`** (owner + admin) gates the endpoints/tab.

## Phase 1 — Attribution + click instrumentation

1.1 **`token_usage.topic_id`** (nullable, via `_migrate`) + thread it through:
    `meter_usage`/`record_usage` gain an optional `topic_id`; the relevance
    quickscan (`scheduler` → `review.quickscan_topic`, per topic), brief/rundown
    (per topic), and topic moderation/provision pass the topic. Chat stays `NULL`.
1.2 **Click beacon**: `story_clicks` table (`user_id, item_id, created_at`) +
    `POST /api/stories/click {item_id}` (rate-limited, returns 204). `StoryRow`'s
    title link fires `navigator.sendBeacon`/`fetch(keepalive)` on click before the
    new tab opens — non-blocking, best-effort.
1.3 **Price config** (`config.py`): `GROK_PRICE_IN`/`GROK_PRICE_OUT`/
    `HAIKU_PRICE_IN`/`HAIKU_PRICE_OUT` (USD per 1M tokens; sensible defaults).
    `usage.estimate_cost(model, in, out)` → USD.

## Phase 2 — Aggregation queries (store)

2.1 `usage_summary(since_iso)` — totals (calls, in/out tokens, est cost) overall,
    **by model**, **by purpose**, **by topic** (join topics), **by day** (for a
    sparkline). MTD + previous-period for the trend delta.
2.2 `user_engagement()` — per user: tokens used (window + all-time), topics
    subscribed (→ average across users), stories clicked (`story_clicks`), votes
    (`story_feedback`), saves (`favorite_links`), chat turns (`conversation_messages`),
    `last_login_at`. Cheap GROUP BYs; indexed on the hot columns.
2.3 Keep these in a new `store_metrics.py` mixin (store.py cap).

## Phase 3 — Backend API (admin)

3.1 **`GET /api/admin/metrics/llm?range=30d`** (cap `metrics:read`) — the cost
    summary + breakdowns + daily series + trend.
3.2 **`GET /api/admin/metrics/users`** — the engagement table + derived averages
    (avg topics/user, active users in range).
3.3 Add `metrics:read` to `rbac` owner/admin cap sets.

## Phase 4 — Admin UI (Metrics tab)

4.1 Route `/admin/metrics` (capability-gated) + admin-area link; `api.ts` helpers.
4.2 **Cost section**: headline MTD est-cost + trend arrow; a small bar/spark of
    daily tokens; tables "by topic" and "by model/purpose". A range selector
    (7/30/90d). A muted "estimated from token volume — not an invoice" note.
4.3 **Users section**: a sortable table (user · last seen · topics · tokens ·
    clicks · votes · saves · chats) + the derived averages up top.
4.4 Reuse the existing `usage.css`/cards; minimal new CSS.

## Phase 5 — Verify + docs

- **Tests**: `record_usage` with `topic_id` round-trips into `usage_summary` by
  topic; `estimate_cost` math; click beacon writes a row + is rate-limited;
  `metrics:read` gates (non-admin 403); engagement aggregates. Offline.
- Docs: `architecture.md` (metrics + click events), `.env.example` (price knobs),
  `roadmap.md`.

## Done when

The owner opens **Admin → Metrics** and sees, for the last 30 days, an estimated
Grok/Haiku spend with a trend arrow and a per-topic/per-day breakdown (so a
runaway topic is obvious), plus a user table showing tokens, topics followed,
stories clicked, votes, and last-seen — all admin-gated.
