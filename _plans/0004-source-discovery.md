# 0004 — Agent Source Discovery (Brave)

**Status:** ✅ Implemented (2026-06-19)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0002](./0002-ingestion-core.md) ✅, [0003](./0003-consumer-api.md) ✅

> **Done.** 18 tests pass. Verified live against Brave: `discover --topic crypto`
> proposed real feeds (CoinDesk, CNBC, Yahoo Finance, The Block, CoinGecko…);
> approving them and collecting ingested 179 items, 0 errors.
>
> **Precision fixes to `discover.py` (bbv2's copy):** autodiscovery now requires a
> feed MIME type on `rel="alternate"` links (drops hreflang/locale false-
> positives), and the probe path requires a feed-like *response* (a `/feed` URL
> serving HTML is no longer accepted). The human approval step remains the final
> quality gate.

## Goal

For a topic, **web-search via Brave** to propose candidate sources, resolve them
to concrete RSS/Atom feeds (reusing `discover.py`), and store them as
`candidate` sources for **human approval**. Approved candidates become `active`
and the next collect picks them up. Turns "I want a topic" into "here's a vetted
source list" with a human in the loop.

## Guardrails (unchanged)

og briefbot untouched; bbv2 reads/writes only its own `data/bbv2.db`.

## Flow

```
topic (name + description)
  → build search queries (heuristic; LLM-crafted later)
  → Brave web search per query → result URLs
  → dedupe to candidate site homepages (by domain)
  → discover_site_feeds(homepage) → concrete feed URL(s)        [reuses discover.py]
  → store as sources(status='candidate', discovered_by='brave') linked to topic
  → human: `source candidates` → `source approve <id>` / `source reject <id>`
  → approved → status='active' → next collect ingests it
```

Candidates are **not** collected (collect only reads `status='active'`), so
nothing enters the corpus until a human approves it.

## Brave client

`bbv2/brave.py` — thin client over the Brave Web Search API
(`https://api.search.brave.com/res/v1/web/search`), `X-Subscription-Token` from
`BRAVESEARCH_API_KEY`. Returns `[{url, title}]` from `web.results`. Raises
`DiscoveryError` if the key is missing or the request fails.

## Query generation (v1: heuristic)

From the topic name/description, e.g. `"{name} news"`, `"{name} rss feed"`,
`"best {name} blogs"`, `"{name} analysis"`. Small fixed set; capped results per
query. (An LLM query-crafter + candidate ranker is a clean follow-up — see Notes.)

## Schema / store

Reuses existing `sources.status` (`candidate|active|rejected`) and
`discovered_by`. Adds:
- `list_candidates(topic_slug=None)` — sources with `status='candidate'`.
- `set_source_status(source_id, status)` — approve/reject.

Discovery skips feeds already stored as sources (dedupe) and never downgrades an
existing `active` source.

## CLI

```bash
bbv2 discover --topic crypto [--per-query 8] [--max 20]
bbv2 source candidates [--topic crypto]
bbv2 source approve <id>
bbv2 source reject <id>
```

## Module layout

```
bbv2/
  brave.py       Brave Web Search client (+ DiscoveryError)
  discovery.py   orchestrator: queries → search → homepages → feeds → candidates
  store.py       + list_candidates, set_source_status
  cli.py         + discover, source candidates|approve|reject
  config.py      + brave_api_key()
```

## Testability

`discover_sources(store, topic, *, searcher=brave_search, feed_finder=discover_site_feeds, …)`
takes the searcher and feed-finder as injectable callables, so tests run
**offline** with fakes. `brave.py` parsing is tested with a stub session.

## Tasks

- [x] **1** `config.brave_api_key()`; `bbv2/brave.py` client + `DiscoveryError`.
- [x] **2** `bbv2/discovery.py`: query builder + `discover_sources` (dedupe by
      domain, resolve feeds, store candidates linked to topic).
- [x] **3** store: `list_candidates`, `set_source_status`.
- [x] **4** CLI: `discover`, `source candidates|approve|reject`.
- [x] **5** Tests: discovery with injected fakes (candidates added, deduped, not
      active until approved; approve → active) + brave parse with a stub session.
- [x] **6** Docs: update `CLAUDE.md` (discover/approve commands).

## Done when

`bbv2 discover --topic crypto` proposes candidate feeds; `source candidates`
lists them; `source approve <id>` flips one to `active` so `collect` ingests it;
rejected/duplicate feeds don't reappear; tests pass; og briefbot untouched.

## Notes

- **LLM enhancement (deferred):** use Claude to craft better queries from the
  topic and to score/label candidates (quality, relevance) before they're shown
  for approval. v1 is Brave + heuristics + human approval, which is fully
  functional and testable; the LLM step slots in behind the same interface.
- `BRAVESEARCH_API_KEY` is already in `.env`.
