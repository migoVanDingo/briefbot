# 0011 — LLM relevance quickscan, full-bleed chat, better search/filters

**Status:** ✅ Implemented (2026-06-19)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0010](./0010-relevance-polish-and-parity.md)

> **Shipped:** A LLM quickscan (`review.py` + `relevance.classify_batch`,
> `item_topics.relevant`, provision **reviewing** stage, `bbv2 quickscan`) — the
> keyword filter was removed · B full-bleed `/chat` (fixed shell below a measured
> `--topbar-h`, sidebar on the left edge, full height) · C token-AND search
> (fixes the agent's search/summarize + Stories search) · D Stories topic filter ·
> E Favorites search (`/api/favorites/search`) · F Topics form = Display name +
> Description (auto-slug), nav reorder Headlines·Stories·Topics·Chat·Favorites.
> Idempotent `_migrate` adds new columns to existing DBs (no wipe needed; run
> `bbv2 quickscan` to clean a pre-existing topic). 71 pytest pass; build clean.
> Deferred: semantic search (embeddings), cluster/tag filters (persistent clusters).

Live review of the `crypto` topic: keyword relevance is too weak — aggregator
sources still inject off-topic stories (Israeli airstrikes, World Cup, Taiwan)
that merely mention "crypto". Replace it with an **LLM quickscan** after collect,
plus chat/search/filter fixes.

## A. LLM relevance quickscan (replace keyword filter)

- Drop the keyword filter from `collect.py` (it false-negatives tickers like
  BTCUSDT and false-positives "crypto"-mentioning noise). Collect maps all items.
- `item_topics.relevant INTEGER` (NULL=pending, 1=keep, 0=drop). Display queries
  filter `COALESCE(it.relevant,1)=1` (hide only confirmed-irrelevant).
- `relevance.classify_batch(topic, desc, items, generate)` — send ~20 stories
  (id + title + blurb) to Haiku in one call → `{id: relevant}`. Injection-safe.
- `review.quickscan_topic(store, slug, generate)` — batch the topic's **pending**
  items, classify, set relevance. New provision **stage "reviewing"** runs it
  after collect (discover→approve→collect→**review**→ready). CLI `bbv2 quickscan`.

## B. Chat: full-bleed, left-anchored, full-height

The thread is cramped inside the centered `.content`. Make `/chat` a **fixed,
full-viewport** shell below the topbar: sidebar pinned to the **left edge**, full
height; thread fills the rest; input bar at the bottom. Measure topbar height →
`--topbar-h` so it's robust.

## C. Agent search / Stories search — token matching

`search_stories` returns 0 for real stories because search is a single `LIKE
%query%` (so "Israeli airstrike Sidon" misses "Israeli airstrike **near** Sidon").
Make `query_stories` search **token-based** (each word ANDed, matched in title OR
summary). Fixes the agent's summarize_article/search_stories and Stories search.

## D. Stories filters — topic + date + title (+ later: cluster, semantic)

Add a **topic** dropdown (subscribed topics) to the Stories filter bar (date +
search already there). Cluster + semantic search are deferred (need persistent
clusters / embeddings) — note in roadmap.

## E. Favorites search

A search bar on `/favorites` that searches **all** saved stories (title/url,
token-based) across folders. Backend `search_favorites` + `GET /api/favorites/search`.

## F. Topics form + nav order

- Create form: **Display name** first, then **Description** (placeholder
  "Describe your topic"); **auto-derive the slug** from the name (no slug input).
- Nav order → **Headlines · Stories · Topics · Chat · Favorites**.

## Done when

Off-topic stories are quick-scanned out by the LLM after collect; `/chat` is full
width + height with the sidebar on the left edge; the agent can find/summarize
stories that exist; Stories filters by topic; Favorites has search; the Topics
form leads with Display name + Description and auto-slugs; nav is reordered.
