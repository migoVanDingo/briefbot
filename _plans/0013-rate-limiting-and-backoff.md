# 0013 — Rate-limit every API + exponential backoff on outbound calls

**Status:** ✅ Implemented (2026-06-20)
**Date:** 2026-06-20
**Phase:** Build · **Depends on:** [0012](./0012-chat-topic-creation-and-token-budget.md)

> **Shipped:** A shared `httpclient.request_with_backoff` (retry `429` + `5xx`
> incl. Anthropic **529 "overloaded"** + connection errors; honors `Retry-After`;
> exponential backoff + jitter; injectable `sleep`/`rand`) wired into **all**
> outbound calls — `llm.py` (Anthropic, was unprotected), `brave.py` (was
> unprotected), `agent._fetch_text`, and `fetch.py` + `discover.py` (refactored
> off their duplicated 429-only loops) · **inbound** rate limiting on **every**
> route: a router-wide per-user limit on all `/api/*` (`RL_DEFAULT_PER_MIN=120`),
> a tighter chat-send limit (`RL_CHAT_PER_MIN=20`), and a per-token consumer-API
> limit (`RL_CONSUMER_PER_MIN=120`). All env-overridable. 85 pytest pass.

Policy: **rate-limit all APIs and exponentially back off all outbound calls
unless there's a valid reason not to.** Before this, only topic-create/provision
were limited (plus the token budget), the consumer API was unlimited, and only
`fetch`/`discover` backed off — `llm.py` and `brave.py` retried nothing.

## A. Shared outbound backoff (`httpclient.py`)

`request_with_backoff(do_request, *, max_attempts=4, retry_statuses, base_delay,
max_delay, sleep, rand)` calls a request thunk and retries retryable failures:

- Retryable: HTTP `429`, `500/502/503/504`, **`529`** (Anthropic overloaded), and
  `requests.RequestException` (connection errors).
- Honors a numeric `Retry-After`; otherwise exponential backoff
  `base·2^(attempt-1)` + up to 25% jitter, capped at `max_delay` (15s).
- Non-retryable responses (other 4xx) return immediately for the caller to handle.
- `sleep`/`rand` injectable → tests are instant and deterministic.

Applied to every third-party call: `llm.generate_text` / `anthropic_messages`,
`brave.brave_search`, `agent._fetch_text`. `fetch._request_with_retries` and
`discover.discover_site_feeds` were **refactored onto it** (deleting their
hand-rolled 429-only loops — they now also retry 5xx/connection errors).

## B. Inbound rate limits (every route)

Reuses the existing in-memory sliding-window `ratelimit.limiter`.

- **Dashboard** — a router-wide dependency (`_rate_limited`, applied at
  `include_router`) enforces `config.ratelimit_default()` **per user on every
  `/api/*` route**. It `Depends(current_user)` (dependency-cached → no double
  auth). Chat sends additionally enforce `config.ratelimit_chat()` (each costs
  tokens). Existing create (5/hr) / provision (10/hr) caps + the token budget
  remain.
- **Consumer API** — `require_scope` enforces `config.ratelimit_consumer()`
  **per service token**, so `trader`'s poller can't hammer it.

New config (env-overridable): `RL_DEFAULT_PER_MIN=120`, `RL_CHAT_PER_MIN=20`,
`RL_CONSUMER_PER_MIN=120`. Defaults are generous — a backstop against runaway
clients, not a brake on normal use. All return `429` + `Retry-After`.

## Valid reason not to (the one exemption)

`/health` on the consumer API is **not** rate-limited — it's for uptime
monitoring, so throttling it would defeat its purpose. It never authenticates, so
it never reaches the per-token limiter.

## Tests

`test_httpclient.py` (retry-then-succeed, non-retryable returns immediately,
gives up at `max_attempts`, honors numeric `Retry-After`, retries then re-raises
connection errors) · `test_ratelimit_api.py` (dashboard general limit → 429,
consumer per-token limit → 429, `/health` exempt). Existing usage test pinned to
fixed budget values so it's independent of `.env`.

## Done when

Every outbound third-party call retries transient failures with exponential
backoff; every dashboard and consumer route is rate-limited per user/token (with
`/health` exempt); limits and backoff are env-tunable; suite green.

## Deferred

- The limiter is **in-memory, single-process** (resets on restart, not shared
  across workers) — fine for one `bbv2 serve`. A multi-process deploy would need a
  shared store (e.g. SQLite/Redis-backed counters).
- Backoff is per-call (no global circuit breaker / token-bucket across calls to
  the same provider) — adequate at personal scale.
