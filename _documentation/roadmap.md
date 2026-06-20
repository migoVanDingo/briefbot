# bbv2 — Roadmap & backlog

Phased build is tracked in [`../_plans/`](../_plans/) (shipped through `0009`).
This file holds what's **left** — backlog and known rough edges.

## Next (each its own plan)

- **Settings:** per-user **accent color picker** (light accent is hardcoded blue
  now) alongside the existing digest settings.
- **Logo** to replace the `◆` brand-mark.
- **Article images** on cards — extract `media:content`/`enclosure` when present,
  optional `og:image` scrape fallback (v1 never captured these).
- **Persistent clusters** — promote `cluster.py` results into tables; unlocks the
  **Stories cluster/tag filters** deferred in 0008 Phase 3. Plus per-article deep
  summaries (v1's stage-1 fetch+cache) and a **brief cron** cadence (generation is
  manual via button/CLI today).
- **HN / arXiv fetchers** — normalizers already exist; wire the source types.
- **Query-angle expansion** (0009 deferred) — Haiku turns an allowed topic into
  better, safe search angles (e.g. `hacking` → reverse engineering / vuln
  research) to seed discovery.

## Known issues / refinements

- **Language filtering (English).** Discovery/collection surface some non-English
  sources/items. Options: bias Brave to English (`search_lang=en`); per-topic /
  per-user language preference; language-detect items → tag + filter (hide items,
  not necessarily the source).
- **Candidate quality (0004).** Probing can still propose weak feeds (aggregators,
  comment feeds). Consider an LLM ranker/labeler + a feed "health" check (recent,
  real entries) before approving.
- **Feed-URL dedupe.** Treat trailing-slash variants (`/feed` vs `/feed/`) as one.
- **Relevance (0011).** Off-topic stories are dropped by an **LLM quickscan**
  after collect (`bbv2 quickscan`; runs as a provision stage). Pending items show
  until reviewed — run quickscan / re-provision to clean an existing topic. At
  scale, add a cheap pre-filter before the LLM call.
- **Semantic search.** Stories + Favorites search is token-AND (LIKE). Embeddings
  would enable true semantic search; pairs with persistent clusters below.

## Known bugs (pre-0008, low priority — flow changed since)

- **Admin "Approve all"** uses `Promise.all` of approve POSTs → "failed to fetch"
  under the shared SQLite connection. Fix: serialize client-side or add a bulk
  approve endpoint. (The user flow auto-approves server-side, so this only affects
  the admin curation screen.)
- **Stale items in collect** — some feeds carry old `published_at`, so old items
  land in the archive. Fix: a recency filter in `bbv2/collect.py` before upsert.

## Done (for reference)

Multi-user + settings + email (0005), dashboard + Firebase API (0006/0007),
v1-dashboard port — Headlines/Chat/Stories/Favorites, prefixed ULIDs, brief
engine, chat agent (0008), user topic flow + owner-only roles + guardrails (0009),
relevance filter + HTML-stripped blurbs + Title-cased names + Headlines ratings +
chat layout + Stories thumbs/date filter + input sanitization + MUI icons (0010);
LLM relevance quickscan + full-bleed chat + token search + Stories topic filter +
Favorites search + Topics name/description form + nav reorder (0011).
