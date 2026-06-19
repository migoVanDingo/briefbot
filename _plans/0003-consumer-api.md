# 0003 — Consumer API

**Status:** Proposed (awaiting review)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0002 ingestion core](./0002-ingestion-core.md) ✅

## Goal

A small **token-authenticated, read-only HTTP API** so other apps — first the
`trader` project, as a service account — can pull items by topic. This is what
unblocks trader to start consuming crypto/markets/geopolitics news.

## Guardrails (unchanged)

og briefbot untouched; bbv2 reads/writes **only its own** `data/bbv2.db`.

## Scope

- **In:** FastAPI app; bearer-token auth; token→topic scoping; `GET /health`,
  `GET /topics`, `GET /items`; a `bbv2 token` CLI to mint/list tokens; a
  `bbv2 serve` command; tests.
- **Out:** writes of any kind; per-user accounts/subscriptions (phase 4 replaces
  token scoping with subscriptions); item enrichment/features (trader-side);
  the dashboard.

## New dependencies

`fastapi`, `uvicorn` (runtime) and `httpx` (tests, for `TestClient`).

## Schema additions (bbv2 DB)

```sql
api_tokens(token PK, label, created_at)
token_topics(token, topic_slug, PRIMARY KEY(token, topic_slug))   -- read scope
```

A token may read only the topics in its `token_topics` scope. (When multi-user
lands in phase 4, tokens attach to a `user_id` and scope comes from
`subscriptions`; `token_topics` is the interim mechanism.)

## Endpoints

| Method | Path | Auth | Returns |
|--------|------|------|---------|
| GET | `/health` | none | `{status:"ok"}` |
| GET | `/topics` | bearer | topics the token may read |
| GET | `/items?topic=<slug>&since=<iso>&limit=<n>` | bearer | items for an in-scope topic |

- **Auth:** `Authorization: Bearer <token>`. Missing/invalid → `401`. Topic not
  in the token's scope → `403`.
- **Item shape:** `item_id, title, url, canonical_url, source_name,
  published_at, fetched_at, summary, score`.
- **`limit`:** default 100, hard cap 500.

## Incremental-pull design (important for trader)

Consumers poll "give me everything new since I last checked." To make that
reliable, `/items` filters and orders by **`fetched_at`** (ingestion time), not
`published_at` — so backdated articles aren't missed:

- `since` filters `fetched_at > since`.
- Results are **ascending** by `fetched_at`.
- The consumer checkpoints the **last `fetched_at`** it received and passes it as
  `since` next time.

(`items_for_topic` from 0002 orders by `COALESCE(published_at, fetched_at)` for
human browsing; the API adds a `fetched_at`-ordered query for machine pulls.)

## CLI additions

```bash
bbv2 token create --label trader --topics crypto,markets,geopolitics   # prints token once
bbv2 token list
bbv2 serve [--host 127.0.0.1] [--port 8080]                            # uvicorn
```

## Module layout

```
bbv2/
  api.py     FastAPI app: routes + bearer-auth dependency (get_token_scope)
  store.py   + create_token / get_token / token_topic_slugs / items_for_consumer
  cli.py     + token create|list, serve
```

Keep `api.py` thin: it validates the token (→ allowed slugs), calls store
queries, and serializes. No business logic beyond scope enforcement.

## Tests (offline, FastAPI TestClient)

- `/health` → 200 without auth.
- No/invalid token → 401.
- Valid token → `/topics` returns only scoped topics.
- `/items?topic=<in-scope>` returns seeded items; out-of-scope topic → 403.
- `since` filtering returns only newer-than-checkpoint items, ascending.

Inject an in-memory `Store` via a FastAPI dependency override; seed a topic, a
scoped token, and a couple items. No network.

## Tasks

- [ ] **1** Add `fastapi`/`uvicorn`/`httpx` to `requirements.txt`.
- [ ] **2** Schema + store methods: `api_tokens`, `token_topics`,
      `create_token`, `token_topic_slugs`, `items_for_consumer(slug, since, limit)`.
- [ ] **3** `bbv2/api.py`: app, bearer-auth dependency, `/health` `/topics` `/items`.
- [ ] **4** CLI: `token create`, `token list`, `serve`.
- [ ] **5** Tests (TestClient) per above.
- [ ] **6** Docs: update `CLAUDE.md` (serve + token commands) and note the API in
      trader's `0017` as the live integration point.

## Done when

`bbv2 token create --label trader --topics crypto` mints a token; `bbv2 serve`
runs; `curl -H "Authorization: Bearer <token>" localhost:8080/items?topic=crypto`
returns scoped items; out-of-scope/invalid-token requests are rejected; tests
pass; og briefbot untouched.

## Notes

- **Brave key:** `BRAVESEARCH_API_KEY` is already in `.env`. It's **not** used in
  0003 — it powers agent source discovery in **0004**.
- This API is the boundary trader consumes; trader does its own trading-specific
  feature extraction on the items it pulls.
