# bbv2 — Roadmap & backlog

Phased build is tracked in [`../_plans/`](../_plans/) (shipped through `0028` —
`0018` theme/tour state in DB, `0019` sessions + RBAC + spaces, `0020` per-topic
scheduling + caps, `0021` admin metrics, `0022` consumer API under `/consumer`,
`0023` durable provisioning pipelines, `0024` topic header images, `0025`
codebase review + fixes, `0026` logging, `0027` metrics expansion, `0028` user
profiles + avatars, `0029` auto-drop dead/blocked feeds). This file holds what's
**left** — backlog and rough edges.

## Next (each its own plan)

- **Settings:** per-user **accent color picker** — the `user_settings.accent`
  column + `PATCH /api/preferences {accent}` already exist (0018); this is now a
  pure frontend task (picker UI → write `accent`, apply as a CSS var).
- **User spaces (build on the 0019 + 0028 foundation):** the **profile** slice
  shipped in `0028` (avatar + personal metrics + blog *stub*). Still pending:
  per-space scoping of topics/headlines, a spaces UI, invites/membership, and the
  real **blog engine** behind the profile stub (`spaces` + `space_membership` +
  capability scoping already in place; existing features are still global).
- ~~**Logo**~~ — done. ~~**Topic header images**~~ — done (0024: per-topic Grok
  Imagine image on the Headlines brief).
- **Per-article images** on story cards — extract `media:content`/`enclosure` when
  present, optional `og:image` scrape fallback (separate from the topic image).
- **Persistent clusters** (the 0014 companion) — promote `cluster.py` results into
  tables; unlocks the **Stories cluster/tag filters** deferred in 0008 Phase 3, and
  better brief/rundown story selection + "what a user cares about" / trending. Plus
  per-article deep summaries (v1's stage-1 fetch+cache). *(Brief cron cadence is now
  done — `bbv2 nightly`; `tick` handles pull cadence.)*
- **HN / arXiv fetchers** — normalizers already exist; wire the source types.
- ~~**Query-angle expansion**~~ — **done**: `discovery.craft_queries` (LLM) turns a
  topic into entity/angle-specific search queries (e.g. Firearms → "Glock new
  models", "gun law changes", "NRA news") + retries up to 3× with fresh angles,
  giving up with a clear message; junk feeds (Wikipedia featured/comments) filtered.

## Ideas to explore (kick around tomorrow)

Bigger directional bets — not yet specced. Each would get its own plan.

- **In-app article reader + agent companion.** Read the story inside the app and
  talk to the agent about it: select text → "what does this mean?", "find related
  stories", "summarize the rest". *Note:* a raw `<iframe>` of the source URL mostly
  won't work — many sites send `X-Frame-Options: DENY` / CSP `frame-ancestors`, and
  embedding third-party pages is an XSS/clickjacking risk. Better path: a **reader
  mode** that extracts the article (we already fetch + strip via `agent._fetch_text`
  / bs4; add a readability pass) and renders it as sanitized in-app content, with
  selection → agent actions. Store **highlights/annotations** per user → a personal
  knowledge base over time.
- **Topic deepening → mini-curriculum.** Once a topic has enough collected data,
  the agent pulls "surrounding" context (adjacent subtopics, foundational concepts,
  key entities) and assembles a short **learning path** — explainers, a reading
  order, check-ins. Leans on persistent clusters (below) + entity extraction; could
  generate per-user, paced over days, and tie into the daily brief.
- **Feedback-driven ranking.** `story_feedback` (👍/👎) is collected but unused —
  feed it into relevance/ranking and brief story-selection (learn what each user
  actually values). Pairs with clusters for "what this user cares about".
- **Richer morning email.** The nightly email is just a "ready" link; include the
  actual brief (title + summary + top stories) so it's useful without opening the app.
- **Push / breaking alerts.** Notify on a high-signal cluster spike in a followed
  topic (beyond the daily cadence).
- **Papers/PDF mode.** The agent already mentions papers — add arXiv/PDF ingest +
  grounded summarize for research-y topics.
- ~~**Admin metrics view.**~~ — **done** (`0021` + `0027`): est. LLM cost by
  model/purpose/topic/day, per-image cost, friendly purpose labels, and a
  per-user drill-down (usage, access frequency, subscriptions, 👍/👎). Still
  open: **collection health** (sources failing/stale) + per-topic freshness.

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
- **Token metering (0012, mostly closed).** Chat, provision **review**, and now the
  discovery **query crafter** (`craft_queries`, metered via the injected `query_gen`)
  are all metered per user/system; image gen is metered per-image (0027). Budget is
  per-`bbv2 serve` process scale — fine for personal use.
- **Rate limiter is single-process (0013, thread-safe as of 0025).**
  `ratelimit.limiter` is in-memory + lock-guarded: resets on restart, not shared
  across workers. Fine for one `bbv2 serve`; a multi-process deploy would need
  shared counters (SQLite/Redis). Outbound backoff is per-call — adequate at this scale.

## Tech debt + security audit

**The 2026-06-20 audit was cleared in plan `0016` (2026-06-21)** — SSRF guard,
env-driven CORS/bind, token revoke, stale-item filter, moderation metering,
logging, the CSS split, the `--surface2` var fix, SSE abort, and the dead-code
removal all shipped (see Done). What remains is deliberately **[accepted]** at
personal scale, plus the always-true "verified good" baseline.

**Verified good (re-confirmed each audit):** parameterized SQL throughout (no
injection), markdown without raw HTML (no XSS — react-markdown, no `rehype-raw`),
HTML-stripped ingest, Firebase-verified auth on every route, owner-only admin
gating, no IDOR, prompt-injection wrapped + fail-closed moderation, secrets
gitignored.

**A second review pass ran 2026-06-27 (plan `0025`)** — verified findings across
security, concurrency, modularity, and frontend/mobile. Fixed: Firebase
`email_verified` gate at exchange (owner-impersonation), thread-safe rate limiter,
chat tool-call exception guard + budget mid-loop recheck, `get_or_build_brief` /
topic-image dedup (atomic claims), `dashboard_api.py` split back under the 600 cap
(`dashboard_briefs.py` + `dashboard_serial.py`), shared `rate_limit_error`/
`story_dict` helpers, and the mobile fixes (onboarding tour anchors, fetch-race
guards, Headlines topic guard, TopicDetail/Stories/Scheduling overflow, collapsible
mobile chat strip). **Structured logging shipped in `0026`** (closes the
observability gap below).

**[accepted] (left at personal scale — revisit if the surface widens):**
- **Consumer-token *hashing*** — tokens are stored plaintext (now revocable). The
  token is a PK+FK and a live trader token exists, so hashing is a risky migration
  for marginal gain at family scale. Hash if the API ever faces untrusted clients.
- **`/me` auto-marks onboarding** on a GET (idempotent, own-user; a smell, harmless).
- **In-memory rate limiter** (now thread-safe + idle-swept) + per-statement
  autocommit — fine for one `bbv2 serve`; needs shared counters only for multi-worker.

**Deferred from the `0025` review (low-value refactors, do when next touched):**
- Move agent tool **bodies** into an `agent_tools.py` registry (schema/impl colocated)
  — `agent.py` is ~573 lines (under cap).
- Extract one `provision_runner.start_run()` to dedupe the provisioning wiring shared
  by `dashboard_api.provision` and `agent._create_topic_events`.
- Split `api.ts` interfaces into `api.types.ts`; `cli.py` `with_store` contextmanager;
  an `llm_errors()` wrapper for the repeated `try/except → HTTPException(400)`.
- Frontend lows: `useAsync`/`useSubscribe` hooks, ≥40px touch targets, Google-signin
  busy guard, Settings number-input clamp, null-url StoryRow renders a link, prune
  dead CSS (`.vote-btn`/`.cadence-*`/`.story-summary`).

## Done (for reference)

Multi-user + settings + email (0005), dashboard + Firebase API (0006/0007),
v1-dashboard port — Headlines/Chat/Stories/Favorites, prefixed ULIDs, brief
engine, chat agent (0008), user topic flow + owner-only roles + guardrails (0009),
relevance filter + HTML-stripped blurbs + Title-cased names + Headlines ratings +
chat layout + Stories thumbs/date filter + input sanitization + MUI icons (0010);
LLM relevance quickscan + full-bleed chat + token search + Stories topic filter +
Favorites search + Topics name/description form + nav reorder (0011); chat-driven
`create_topic` (confirm → streamed provisioning → auto-subscribe) + per-user
token metering + two-tier daily budget + sidebar usage counter + chat avatars (0012);
all-API rate limiting (per-user dashboard + per-token consumer) + shared outbound
exponential backoff (`httpclient`, all third-party calls) (0013); first-visit
onboarding (Joyride) + nightly brief & email (`bbv2 nightly`) + on-demand shared
rundowns + decoupled hourly pull cadence (`bbv2 tick`, per-topic discovery + per-
source/topic collection) + Grok relevance model + single 100k user budget with a
system bucket (0014); chat **markdown** rendering + context-aware onboarding agent
(`_context_block` with subs/usage/available-topics, `subscribe_topic` tool, canned
first-visit greeting fed into context) (0015). Post-0015 hardening: per-thread
SQLite connections (fixed concurrent-write "cannot commit"), brief generated on
topic-add during the initial setup window (account-age gated) with `headline_ready`
signaling, per-topic source cap + per-source story cap + per-item collect
resilience, last-accessed-chat restore, provisioning phrases in chat. **Tech-debt
+ hardening (0016):** SSRF-guarded outbound fetches (`safefetch.safe_get` — private-
IP block, redirect re-validation, body cap; closes streamed-conn-on-retry leak),
env-driven CORS/bind (`ALLOWED_ORIGINS`/`BBV2_SERVE_HOST`), consumer-token revoke,
collect recency-cutoff + newest-first sort, topic-moderation LLM metering, raw-
`requests`-error wrap in `llm`, `print()`→`logging` for cron, dead relevance-keyword
path removed (incl. `keywords_json` column), bulk `approve-all` endpoint, SSE abort-
on-unmount (Chat/TopicsHome), `index.css` split into per-area files + barrel, and
the `--surface2`/`--accent2` CSS-var fix. **Headlines date rail (0017):** dropped
the "Today" aggregate tab (tabs are now just topics); added a left rail of the last
10 calendar days (`GET /topics/{slug}/briefs`) — pick a day to see that day's brief
+ only that day's stories; collapsed the redundant Trending/Sources lists in the
brief card (the story list already shows title + blurb + time). **0018–0028:**
DB-persisted UI state (0018); backend auth sessions + RBAC + spaces foundation
(0019); per-topic scheduling + ingest caps (0020); admin metrics — est. LLM cost +
user engagement (0021); consumer API under `/consumer` (0022); durable provisioning
pipelines that survive navigation (0023); per-topic Grok Imagine header images
(0024); **codebase review + fixes** — `email_verified` gate, thread-safe limiter,
chat tool guard + budget recheck, brief/image dedup, `dashboard_api` split, mobile
fixes (0025); **structured logging** — env-driven level/format, `-v`, LLM/auth/
background instrumentation, global 500 handler (0026); **metrics expansion** —
cost by purpose with friendly labels, per-image cost, per-user drill-down (0027);
**user profiles** — identicon avatars + optional Grok-generated avatar, personal
metrics (tokens/cost per day/week/month/year/all), subscriptions, blog *stub* (0028).
