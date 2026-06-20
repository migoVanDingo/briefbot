# 0008 — Port v1's dashboard into bbv2 (+ relocate Topics admin)

**Status:** 📋 Planned (2026-06-19)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0007 dashboard API](./0007-dashboard-api.md)

Bring **all of the original briefbot's normal-flow routes and functionality**
into bbv2 under new names, **relocate** the current Topics/source-approval UI to
an `/admin` area (move only — no rewiring yet), add a **stub** `/topics` route for
the future user flow, switch to **prefixed sortable IDs**, and recolor the
light-mode accent. Once parity lands, we start tweaking.

## Route mapping (v1 → v2)

| v1 route | v2 route | What it is |
|---|---|---|
| `/` (briefs) | **`/headlines`** (also `index`) | Daily brief: generated title + "what's going on today" + trending (clusters) + contributing sources |
| `/ask` | **`/chat`** | Agentic Haiku chat w/ tools (search, summarize, favorites) — SSE streaming |
| `/stories` | **`/stories`** | DB-backed story browser: filters, newest-first, feedback votes, star-to-favorite |
| `/favorites` | **`/favorites`** | Folders + favorited links CRUD |
| — (new) | **`/topics`** | **Stub now.** Future user flow (create topic → auto-approve → subscribe) |
| Topics + source approval (current bbv2) | **`/admin/topics`**, `/admin/topics/:slug` | Existing UI **moved verbatim**, still calls existing endpoints |

## Guardrails

- og briefbot **untouched**; bbv2 owns its DB. (We only copy logic out of v1.)
- **Adaptations v1 didn't have to make** — call these out in every ported piece:
  - **Firebase auth** on every new `/api/*` route (reuse the `current_user`
    dependency from 0007). v1 had no auth.
  - **Per-user scoping**: favorites, folders, conversations are **per user**.
    Stories/headlines are scoped to the user's **subscribed topics**.
  - **LLM = Haiku, always.** v1's dashboard backend defaulted to **Opus**
    (`claude-opus-4-1`); bbv2 forces `claude-haiku-4-5-20251001` (cost). Ignore
    v1's model default; route everything through `config.anthropic_model()`.
  - **Briefs in the DB, not markdown files.** v1 wrote `data/briefs/{date}.daily.md`.
    bbv2 is multi-user + per-topic — store briefs in a `briefs` table keyed by
    `(topic, date)` so the landing can compose across a user's subscriptions.

## ID scheme — LOCKED: prefixed ULID

**Decision (confirmed):** every PK is an **uppercase prefix + ULID body, no
separator** — e.g. `SRC01J9Z3K7Q8…`, `TOP01J9Z3K7Q9…` (illustrative; ULID body is
Crockford base32, 26 chars). Time-sortable + self-describing.

> Context: v1 did **not** use ULIDs — it used content-hash `stable_hash` (32/24
> chars) + UUID v4. bbv2 already mirrors v1's item-ID hash. We are **deliberately
> upgrading** to prefixed ULIDs. DB is disposable now (`rm -rf data/`), so no
> migration — just regenerate.

Prefix table (3-letter uppercase):

| Prefix | Entity | | Prefix | Entity |
|---|---|---|---|---|
| `ITM` | item | | `FLD` | favorite folder |
| `SRC` | source | | `CON` | conversation |
| `TOP` | topic | | `MSG` | message |
| `CLU` | cluster | | `USR` | user |
| `FAV` | favorite link | | `BRF` | brief |

The `item_id`/`dedupe_key` split stays: `dedupe_key` remains the content key
(UNIQUE, `url:`/`fallback:` prefixes), the prefixed ULID becomes the PK.

---

## Phase 1 — Routing reshape + Topics→/admin relocation + accent recolor ✅ (2026-06-19)

Frontend-only, low risk, ships immediately. **No backend changes**, no rewiring of
the moved admin UI.

- [x] **1.1** `git mv` `pages/Topics.tsx` + `pages/TopicDetail.tsx` → `pages/admin/`
      (content unchanged except import depth `../`→`../../` and internal links
      `/topics`→`/admin/topics`; title says "Topics (admin)"). Still call the
      existing `discover/approve/reject/sources/items` endpoints.
- [x] **1.2** New page stubs: `pages/Chat.tsx`, `pages/Stories.tsx`,
      `pages/Favorites.tsx`, `pages/TopicsHome.tsx` (titled "coming soon" shells).
      Headlines now also serves `/headlines` (still the index).
- [x] **1.3** `App.tsx` routes: `index`+`headlines`→Headlines, `chat`, `stories`,
      `favorites`, `topics` (stub), `settings`; `admin/topics`, `admin/topics/:slug`.
- [x] **1.4** `AppShell.tsx` nav → **Headlines · Chat · Stories · Favorites ·
      Topics**; right cluster has **Admin** + **Settings** links (role-gating is a
      later plan).
- [x] **1.5** Light-mode accent teal `#0ea5a4` → blue `#2563eb` (`accent2`
      `#60a5fa`). Dark unchanged.
- [x] **1.6** `tsc && vite build` clean (no `lint` script in dashboard; tsc is the
      gate).

**Done:** every new route renders (stubs OK), the old Topics/source-approval UI
works unchanged at `/admin/topics`, light accent is blue.

## Phase 2 — Prefixed ID layer (decision B)

- [ ] **2.1** `bbv2/ids.py` — Crockford-base32 ULID + `new_id(prefix)` minting
      `<PREFIX><ULID>` (e.g. `SRC01J9…`); prefix constants per the table above.
      Unit test: sortability + uniqueness + correct prefix.
- [ ] **2.2** Repoint `item_id` generation (normalize/store) to `ITM…`; keep
      `dedupe_key` and the upsert-by-dedupe_key path intact.
- [ ] **2.3** `rm -rf data/` + reseed; verify collect still dedupes.

**Done when:** new items carry `itm_…` PKs, dedupe still works, tests pass.

## Phase 3 — Stories (DB browser): backend + page

- [ ] **3.1** Store queries (adapt v1's, scope to subscribed topics): list sources,
      list clusters, list tags, paginated story query (search/date/source/cluster/
      tags/sort, newest-first default).
- [ ] **3.2** `dashboard_api.py` (Firebase): `POST /api/stories` (query),
      `GET /api/stories/sources|clusters|tags`. Feedback: `POST /api/stories/feedback`
      (+ a `story_feedback` table, per user).
- [ ] **3.3** `Stories.tsx`: filter bar + results list (title, source chip, time,
      summary, vote + star). Wire `api.ts` methods.

**Done when:** a subscribed user can browse/filter their stories newest-first and
vote.

## Phase 4 — Clustering + Brief engine + Headlines page

- [ ] **4.1** Port `cluster.py` (rapidfuzz/Jaccard keyword clustering + trend
      score) → bbv2; `clusters` + `cluster_memberships` tables (prefixed IDs).
      Run as part of collect (or a `cluster` step).
- [ ] **4.2** Port `executive.py` (stage-1 per-article summarize → reduce to a
      narrative) → bbv2, **Haiku**, with the stage-1 cache table. Add a day-title
      generator (v1 had a static heading; bbv2 generates one via Haiku).
- [ ] **4.3** `briefs` table `(topic_id, date, title, summary_md, trending_json,
      sources_json)`. Generation entrypoint: CLI `bbv2 brief [--topic]` (cron-able);
      cadence decided later (default: daily, cached).
- [ ] **4.4** `GET /api/headlines` → compose the signed-in user's brief across
      subscribed topics (title + summary + trending + contributing sources).
- [ ] **4.5** `Headlines.tsx`: render brief (markdown), Trending section, Sources
      list. Tabs across the top = subscribed topics; **only the landing tab shows
      the summary sections**, per-topic tabs show that topic's stories newest-first.

**Done when:** `/headlines` shows a real generated brief + trending + sources.

## Phase 5 — Favorites + folders

- [ ] **5.1** Tables `favorite_folders` + `favorite_links` (per user, prefixed IDs;
      keep v1's `UNIQUE(folder_id, url)` + auto "favorites" default folder).
- [ ] **5.2** API: `GET/POST /api/favorites/folders`, `GET/POST/DELETE
      /api/favorites/items`.
- [ ] **5.3** `Favorites.tsx`: folder tabs + contents + add/remove; star button
      reused on Stories/Headlines.

**Done when:** a user can favorite a story into a folder and manage folders.

## Phase 6 — Chat agent (/chat)

- [ ] **6.1** Tables `conversations` + `conversation_messages` (per user, prefixed
      IDs).
- [ ] **6.2** Port v1's agent loop + tools → bbv2, **Haiku**, scoped to the user:
      `search_items`, `get_trending_topics`, `get_trend_clusters`,
      `get_related_stories`, `summarize_article`, favorites tools
      (create/add/list/remove folder+favorite), `rename_conversation`.
- [ ] **6.3** API: `GET/POST /api/conversations`,
      `GET/PATCH/DELETE /api/conversations/{id}`, **SSE**
      `POST /api/conversations/{id}/messages` (token/tool_start/tool_end/title
      events).
- [ ] **6.4** `Chat.tsx`: conversation sidebar + streaming thread + tool-call chips.

**Done when:** `/chat` streams Haiku answers, runs tools, persists conversations
per user.

## Phase 7 — `/topics` user flow (LATER — stub only now)

Out of scope for this plan beyond the Phase 1 stub. The real flow (create topic →
loading UI → auto-approve discovered sources → collect → subscribe) and admin
role-gating get their own plan once parity lands.

## Notes / deferred

- **User settings** (incl. the accent **color picker**) — deferred per your call;
  light accent is hardcoded blue for now.
- **Logo** to replace the `◆` brand-mark — deferred (cosmetic; do alongside settings
  or as a quick follow-up).
- **Images on cards** — v1 never captured them; feed `media:content`/`enclosure`
  extraction (+ optional `og:image`) is a later polish pass.
- **Role-gating** the Admin area — later plan (link is visible for now).
- **600-line cap** still applies; split pages/hooks as they grow (Stories/Chat will).
