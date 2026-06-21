# 0012 — Chat-driven topic creation + per-user token budget

**Status:** ✅ Implemented (2026-06-20)
**Date:** 2026-06-20
**Phase:** Build · **Depends on:** [0011](./0011-llm-relevance-chat-filters.md)

> **Shipped:** A `create_topic` agent tool (confirm-first) that creates + provisions
> a topic from chat, streaming the discover→approve→collect→review→ready pipeline
> into the thread (reusing `ProvisionPipeline`) and auto-subscribing on ready · a
> `token_usage` table + `store_usage` mixin metering every Anthropic call per user ·
> a two-tier daily budget (`usage.py`): **50k tokens → block chat**, **75k → block
> everything** with a "resets in X" message, all env-overridable · `GET /api/usage`
> + a chat-sidebar counter (interactions + tokens/limit, progress bar, blocked
> state) · user/agent avatar icons on chat messages. 77 pytest pass; dashboard
> build clean. Deferred: metering discovery's `expand_keywords` call; cross-process
> budget (in-DB window is per-DB but the limiter reset is still per-process).

Two product asks: let a user spin up a new topic by **talking to the agent**
(with a confirmation step and a visible waiting state), and **cap LLM spend**
per user so the bill can't blow up.

## A. `create_topic` agent tool (confirm → provision → subscribe)

- New tool in `agent.py` `TOOL_SCHEMAS` (`name`, optional `description`). The
  system prompt instructs the model to **restate the scope and wait for a yes**
  before calling it ("So this topic should cover news about cryptocurrencies and
  related markets?") — never on the turn the user first mentions it.
- `_create_topic_events(...)` (a generator) moderates (`moderate_topic`, reusing
  the create-endpoint path), `add_topic`, then drives `provision_topic`, yielding
  `topic_stage` SSE events per stage; **auto-subscribes** the user on `ready`
  (parity with the Topics page). Returns `(result, summary)` to the model via
  `yield from`. Hard-budget gated (provisioning is the expensive path).
- `run_chat_turn` dispatches `create_topic` to this generator (it emits its own
  `tool_start`/`tool_end`); all other tools keep the inline path.

## B. Waiting state in chat

`Chat.tsx` handles `topic_stage` events by attaching a `topic: {slug, stage,
failed}` to the streaming assistant message and rendering the existing
`ProvisionPipeline` inside the bubble (flashing-blue current, green done, red on
failure) with a "Setting things up…" placeholder until the model's final text.

## C. Token tracking

- `token_usage` table (`user_id, purpose, model, input_tokens, output_tokens,
  interaction, created_at`) + `idx_token_usage_user_time`; `store_usage.py`
  mixin: `record_usage`, `usage_window(user_id, since_iso)` (sums tokens +
  interactions, earliest timestamp for reset math).
- `llm.py` surfaces Anthropic `usage`: `anthropic_messages` returns it (+ model);
  `generate_text` gains an `on_usage(usage, model)` hook. `usage.metered_generate`
  wraps `generate_text` so any injectable `generate` (review, summaries, title,
  moderation) meters to the right user. Each completed chat turn also logs one
  `interaction` marker.

## D. Two-tier daily budget

- `config.token_budget()` → `{enabled, window_s=86400, chat_limit=50_000,
  hard_limit=75_000}` (env: `TOKEN_LIMIT_ENABLED`, `TOKEN_WINDOW_S`,
  `TOKEN_CHAT_LIMIT`, `TOKEN_HARD_LIMIT`).
- `usage.budget_status(store, uid, tier)` — tier `"chat"` blocks at `chat_limit`,
  tier `"all"` blocks at `hard_limit`; returns usage figures + a ready "You've hit
  your … limit — resets in X." message.
- Enforcement: `run_chat_turn` gates the **chat** tier before any model call;
  the create-topic tool, `POST /api/topics`, and `POST .../provision` gate the
  **all** tier (429 + `Retry-After`).

## E. Usage counter (sidebar)

`GET /api/usage` → `{interactions, tokens_used, chat_limit, hard_limit, window_s,
resets_in, enabled, chat_blocked, all_blocked}`. The chat sidebar shows
interactions + tokens/limit with a progress bar (red when over) and disables the
composer with a "Daily chat limit reached" state when `chat_blocked`.

## F. Message icons

User vs. agent avatar (`PersonOutlined` / `SmartToyOutlined`) beside each chat
bubble; `.msg-row` wraps avatar + bubble (`row-reverse` for the user side).

## Tests

`test_usage.py` (record/window aggregation, both budget tiers, disabled = never
block, `/api/usage` counts, `POST /api/topics` 429 over the hard limit) +
`test_chat.py::test_create_topic_tool_streams_stages_and_subscribes` (stubbed
`provision_topic` → stages forwarded, topic created, user auto-subscribed).

## Done when

A user can ask the agent to create a topic, the agent confirms scope first, then
the provisioning pipeline streams live into the chat and the user ends up
subscribed · every Anthropic call is metered per user · chat blocks at 50k/day
and all LLM actions block at 75k/day with a reset message · the sidebar shows
interactions + token usage · chat messages have user/agent icons.

## Deferred

- Meter discovery's `expand_keywords` (one small call, deep in `discover_sources`;
  needs a metered `generate` threaded through). Review/`classify_batch` **is**
  metered via `review_generate`.
- Cross-process accounting: usage rows are in the DB (durable), but a single
  `bbv2 serve` process is assumed; multi-process would need the window read to be
  the source of truth everywhere (it already is) — fine as-is for the personal scale.
