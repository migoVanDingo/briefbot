# 0010 — Relevance filter, display polish, ratings parity, normalization, sanitization

**Status:** 📋 Planned — captured 2026-06-19 (for tomorrow)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0009](./0009-user-topic-flow-and-roles.md)

Captured from a review of the live app (topic `crypto`). A grab-bag polish +
quality pass. Items are independent — do in any order.

## A. Off-topic story filtering (relevance) — the big one

**Problem:** the `crypto` topic pulls from crypto **aggregator** sources (e.g.
"RSS Crypto — Cryptocurrency News feed aggregator", cryptobriefing) that carry
**non-crypto** stories. Real examples seen, all tagged `(cryptobriefing)`:
- "Pakistan gains significant diplomatic leverage amid Iran war resolution"
- "Endrick makes World Cup debut for Brazil in 3-0 rout of Haiti"
- "Turkey XI announces starting lineup for World Cup match against Paraguay"
- "Falcons eliminate Vitality in IEM Cologne 2026 quarterfinals"
- "Telemetry Report — Claude Code v2.1.143"

**Want:** a heuristic/filter that omits stories unrelated to the topic.

**Approach (decide):**
- **(rec) Relevance score at ingest** in `collect.py` (or a new
  `bbv2/relevance.py`, pure + testable): score each item's title(+summary)
  against the topic's name + keywords (and the discovery query terms). Token
  overlap / keyword match is cheap; drop or flag below a threshold. Store a
  `relevance` score or a `topic` match flag on `item_topics` (or filter before
  `map_item_topic`).
- **Optional LLM tier** (Haiku) only for borderline items — costs per item, so
  gate it (batch, or only when keyword score is ambiguous).
- **Where to apply:** ingest-time drop (cleanest, keeps DB tidy) vs. query-time
  filter (reversible). Lean ingest-time with a configurable threshold.
- Keep it from over-filtering legit on-topic items with odd titles.

## B. Strip HTML from story blurbs (display)

**Problem:** summaries render raw HTML — e.g. `<p>…</p> <p>The post <a href="…">…`
and gist markup show literally on `/stories` (and feed Headlines). See screenshots.
**Fix:** strip tags so only text shows. Two layers:
- **Backend (rec):** add `strip_html` to `util.py` and apply to `summary` in
  `normalize.py` (`normalize_feed_entry`) so stored summaries are clean text.
  (DB was just wiped, so this cleans everything going forward.)
- **Frontend:** also strip/escape on render as defense (React already escapes —
  the issue is the tags are *in the text*, so they show as text once stored clean;
  no `dangerouslySetInnerHTML` anywhere — keep it that way).

## C. Normalize names to Title Case

- **Topics:** capitalize the first letter of each word regardless of input
  (`crypto` → `Crypto`, `world cup` → `World Cup`). Apply at create
  (`moderate_topic`/`create_topic` → set the stored `name`). Slug stays lowercase.
- **Favorites folders:** same Title Case on folder name at create
  (`store.create_folder` / the favorites API). Default `favorites` → display
  "Favorites".
- Add a shared `titlecase()` helper (backend `util.py`); apply server-side at
  storage so it's consistent everywhere.

## D. Ratings + favorites on Headlines (v1 parity)

- On `/headlines` (the brief Sources list **and** the per-topic story tabs), let
  the user **thumbs up / thumbs down** and **favorite** a story — same as
  `/stories`. Reuse `setFeedback` + `addFavorite`.
- The Headlines item endpoints (`/api/briefs` sources, `/api/topics/{slug}/items`)
  return `Item` without `feedback_vote` — either join the user's vote into those
  queries or show the controls without prior state. (Join is nicer.)
- **Note for later:** in v1, **clusters used the ratings** (feedback fed trend
  scoring). We don't have persistent clusters yet (0008 deferral) — when we add
  them, wire `story_feedback` into cluster/trend scoring.

## E. `/headlines` visual polish

The feed list looks very plain (see screenshot). Spice it up — better typography/
spacing, source chips, hover, maybe cards or a cleaner divider rhythm, image
thumbnails once 0010-roadmap "article images" lands. Keep it tasteful, on-theme.

## F. `/chat` layout redesign

Looks bad (see screenshot): the column is **too narrow and centered** with huge
empty margins, sidebar cramped, spacing off. Cause: the chat sits inside
`.content { max-width: 860px }`. Fix: let `/chat` use (most of) the viewport
width, widen the thread, fix sidebar width + message bubble spacing/padding,
align input bar to the thread. Make it feel like a real chat app.

## G. `/stories` fixes

- **Vote icons:** replace the `▲`/`▼` (don't read as vote) with **thumbs up /
  thumbs down** icons. Use **MUI icons** (`@mui/icons-material`) — see decision I.
- **Button text wraps:** "Newest first" wraps to two lines — give the sort toggle
  `white-space: nowrap` + min-width; tidy the filter bar layout.
- **Restore v1 filters:** v1 had search + source + **date range** + cluster + tags
  + sort. Add date range now; **cluster/tags** depend on persistent clusters
  (deferred) — stub or hide until then. Match v1's filter UX.

## H. Input sanitization / XSS on `/stories` + `/favorites`

- **Folders:** sanitize the folder-name input server-side at create (reuse
  `moderation.sanitize_name` — strip tags/control chars, cap length) before
  Title-casing/storing.
- **Stories search:** strip control/HTML chars; it's already a parameterized
  `LIKE` (SQL-safe) but harden the input. Cap length.
- Confirm nothing uses `dangerouslySetInnerHTML`; all user/feed text renders as
  escaped React text. This pairs with B (clean stored summaries).

## I. Decision — bring MUI back (selectively)

User OK'd reintroducing MUI ("nbd, you don't have to use it for everything but you
can"). Plan: add **`@mui/icons-material`** (+ `@mui/material` peer if needed) for
icons (thumbs up/down, star, etc.), used **selectively** — keep the custom CSS
design system for layout/theme; MUI for icons (and any widget that's clearly
better than hand-rolling). Wire MUI theme to our CSS vars / dark-light mode.

## Done when

Off-topic stories are filtered out of a topic; blurbs show clean text; topic +
folder names are Title Case; Headlines has up/down + favorite; `/headlines` looks
good; `/chat` uses proper width/spacing; `/stories` has thumbs icons, no wrapped
buttons, and date filtering; stories/favorites inputs are sanitized.
