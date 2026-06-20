# 0008 — Port v1's dashboard into bbv2 (+ relocate Topics admin)

**Status:** ✅ Phases 1–6 implemented (2026-06-19); Phase 7 (`/topics` user flow)
deferred to its own plan
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

## Phase 2 — Prefixed ID layer (decision B) ✅ code (2026-06-19)

- [x] **2.1** `bbv2/ids.py` — hand-rolled Crockford-base32 ULID (48-bit time +
      80-bit random, no dep) + `new_id(prefix)` minting `<PREFIX><ULID>` (e.g.
      `SRC01J9…`); prefix constants (`ITM/SRC/TOP/CLU/FAV/FLD/CON/MSG/USR/BRF`).
      `tests/test_ids.py`: shape/charset, prefix, uniqueness, time-sortability.
- [x] **2.2** `item_id` now `new_id(ITEM)` (`bbv2/normalize.py`). Dedupe is by
      `dedupe_key` (UNIQUE) — `store.upsert_item` now returns `(item_id, inserted)`
      with the **canonical** id (existing row's on a duplicate) so `collect` maps
      topics correctly; updated `collect.py` + tests. `pytest` 33 green.
- [~] **2.3** DB wipe **deferred to user's call** — `data/bbv2.db` holds real state
      (1 topic, 19 approved sources, 363 items). Wipe is **not required**: old hash
      IDs and new ULIDs coexist (dedupe unaffected). Keep = no loss, only new items
      get ULIDs; wipe = clean slate but re-discover/approve/collect + re-login.

**Done:** new items carry `ITM…` ULID PKs, dedupe still works, tests pass. Existing
rows keep their legacy hash IDs unless the DB is wiped.

## Phase 3 — Stories (DB browser): backend + page ✅ (2026-06-19)

- [x] **3.1** Store (`store.py`, scoped to subscriptions): `story_sources`,
      `query_stories` (search/source/date/sort, **newest-first default**, joins the
      user's vote), `set_story_feedback`. New `story_feedback` table (per user;
      added via `IF NOT EXISTS` so existing DBs upgrade with no migration).
- [x] **3.2** `dashboard_api.py` (Firebase): `POST /api/stories` (query),
      `GET /api/stories/sources`, `POST /api/stories/feedback` (vote ∈ -1/0/1).
- [x] **3.3** `Stories.tsx`: filter bar (search + source select + sort toggle) +
      results (title, summary, source chip, time, ▲/▼ vote). `api.ts`: `Story` type
      + `storySources`/`queryStories`/`setFeedback`. CSS: `select`, `.story-summary`,
      `.vote-btn`.
- [x] **3.4** `pytest` 34 green (stories query/search/sort/feedback + bad-vote 400);
      `tsc && vite build` clean.

**Deferred** (depend on later phases): **cluster** + **tag** filters → Phase 4
(clusters/tags don't exist yet); the **star→favorite** affordance → Phase 5
(favorites). Note left in code via the filter set.

**Done:** a subscribed user can browse/filter their stories newest-first and vote.

## Phase 4 — Clustering + Brief engine + Headlines page ✅ (2026-06-19)

**Scoping call (family scale — flagged):** ported the clustering *algorithm* as a
**pure in-memory module** (no persistent `clusters`/`cluster_memberships`/events/
purge tables) and built the brief as a **single Haiku reduce call** over the top
items' feed title+summary (skipped v1's per-article fetch + stage-1 JSON cache).
Same user-visible output (title + "what's going on" + trending + sources), far
less machinery. The heavier bits can be added later (see Deferred).

- [x] **4.1** `bbv2/cluster.py` — pure `cluster_items(items, now)` (rapidfuzz
      token-set ratio when available, else Jaccard over title/domain/tag sigs; same
      trend-score shape, minus category/watch-hit terms bbv2 lacks). `test_cluster.py`.
- [x] **4.2** `bbv2/llm.py` — Anthropic Haiku client (`generate_text`,
      `extract_json`), wired to `config` (Haiku default, **not** v1's Opus). The
      brief's `generate` is **injectable** → offline-testable.
- [x] **4.3** `bbv2/brief.py` — `build_brief` (cluster → trending; top-N stories →
      one Haiku call → `{title, summary}`; persist) + `build_all_briefs`. `briefs`
      table `(id ULID, topic_id, date, title, summary, trending_json, sources_json,
      model)` UNIQUE(topic_id,date). CLI **`bbv2 brief [--topic] [--date]`**.
      `test_brief.py` (injected generator, offline).
- [x] **4.4** `GET /api/briefs` → latest brief per subscribed topic + the tab list;
      `POST /api/topics/{slug}/brief` generates on demand (admin/test). Store split:
      dashboard queries moved to `store_dashboard.py` mixin (store.py 655→550, under
      cap).
- [x] **4.5** `Headlines.tsx`: **tabs** (Today + subscribed topics). **Today** =
      brief cards (title + paragraphs + Trending + Sources); per-topic tab = that
      topic's stories newest-first. "Generate brief" button on the admin topic page.
      `pytest` 40 green; `tsc && vite build` clean.

**Deferred:** persistent cluster tables (→ unlocks the Stories cluster/tag filters
from Phase 3); per-article stage-1 deep summaries + cache; brief cadence/cron
(generation is manual via button/CLI for now); markdown rendering (summary is
plain paragraphs by prompt). Live Haiku call is **user-invoked** (not auto-run).

**Done:** `/headlines` shows a real generated brief (title + summary + trending +
sources) once a topic's brief is generated.

## Phase 5 — Favorites + folders ✅ (2026-06-19)

- [x] **5.1** Tables `favorite_folders` (UNIQUE user+name) + `favorite_links`
      (UNIQUE folder+url), ULID PKs, **per user**; auto `favorites` default folder.
      Methods in a focused `store_favorites.py` mixin (FavoriteQueriesMixin).
- [x] **5.2** API: `GET/POST /api/favorites/folders`,
      `GET/POST/DELETE /api/favorites/items` (POST without `folder_id` → default;
      dedup upsert per folder+url; 400/404 validation).
- [x] **5.3** `Favorites.tsx`: folder tabs (with counts) + create-folder form +
      items list with remove. **Star (☆)** added to Stories rows and the Headlines
      brief Sources — saves to the default folder. `api.ts`: `Folder`/`Favorite`
      types + folder/item methods.
- [x] **5.4** `pytest` 41 green (favorites roundtrip: default folder, add, dedup,
      count, create, remove, validation); `tsc && vite build` clean.

**Note:** star saves to the default `favorites` folder; choosing a target folder
at save time (and folder delete/rename) can be a later enhancement.

**Done:** a user can favorite a story into a folder and manage folders.

## Phase 6 — Chat agent (/chat) ✅ (2026-06-19)

- [x] **6.1** Tables `conversations` + `conversation_messages` (per user, ULID
      PKs, per-conversation `seq`). `store_chat.py` mixin (ChatQueriesMixin).
- [x] **6.2** `bbv2/agent.py` — tool-use loop (**Haiku**, max 8 iters), scoped to
      the user, 8 tools: `search_stories`, `get_trending`, `summarize_article`
      (fetch + summarize), `list_folders`, `create_folder`, `add_favorite`,
      `list_favorites`, `remove_favorite`. `llm.anthropic_messages` (tools). Model
      call / title / summarizer all **injectable** → offline-tested.
- [x] **6.3** API: `GET/POST /api/conversations`,
      `GET/PATCH/DELETE /api/conversations/{id}`, **SSE**
      `POST /api/conversations/{id}/messages` (events: token/tool_start/tool_end/
      title/done/error).
- [x] **6.4** `Chat.tsx`: conversation sidebar (+ New chat) + thread + tool-call
      chips; `api.ts` `streamMessage` consumes SSE via `fetch` + `ReadableStream`
      (so the Firebase bearer header can be set). Chat CSS + responsive.
- [x] **6.5** `pytest` 46 green (conversation roundtrip, loop text-only + tool path,
      favorites-via-query, conversations CRUD); `tsc && vite build` clean.

**Scoping vs v1:** non-streaming model call per turn (each turn's text emitted as
one `token` event — same event protocol, robust; true token streaming can layer
on later). Tool set trimmed to bbv2's data (dropped get_related/get_news/rename).
Live chat is **user-invoked** (real Haiku); offline tests inject the model.

**Done:** `/chat` runs the tool-use loop, streams events, persists conversations
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
