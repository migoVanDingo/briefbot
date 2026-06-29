# 0030 — Agent on-demand source discovery + topic embedding index

Let a user ask the chat agent to **go find new sources** for a subject, preview
what's out there, and on confirmation **place those sources into the right
topic(s)** (or a new topic). Routing is **evidence-based**: a per-topic embedding
index (built from each day's brief) scores where a request belongs, and the agent
narrates the decision from those numbers rather than from opinion.

Motivating transcript: "search for journals on multimodal learning in K-12" → the
agent found 0 stories because we'd never pulled a source for it.

## Decisions (locked with the owner)

- **Routing brain = topic embedding index.** Embed each topic's daily brief
  summary; represent a topic as the **centroid of its recent (~30-day) brief
  embeddings** (new topics fall back to name+description). On a `find_sources`
  request, embed the **query** and cosine-rank it against every topic's centroid.
  The agent gets the scores as evidence and decides/narrates.
- **Embeddings = OpenAI `text-embedding-3-small`** (plain HTTP, no SDK — like our
  other LLM calls). New `OPENAI_API_KEY`. Cost is negligible (~pennies/year).
- **No vector DB.** Store vectors in **SQLite** + brute-force cosine in Python
  (~10 centroids → microseconds). `sqlite-vec` is the scale path if ever needed.
- **Preview = BOTH** the discovered RSS feeds (with their latest 2-3 headlines)
  **and** a few Brave web results for the exact query.
- **Latency = true background job** (survives navigation), reusing the durable
  `provision_runs` + poll + SSE pattern (0023).
- **Placement is source-level relevance** via the index: a source only lands in
  topics it genuinely fits (best topic; also any other topic that scores highly →
  multi-topic via the existing many-to-many `topic_sources`; none clear the floor
  → create a new topic). After good placement, the topic's normal per-item
  relevance review applies unchanged. Routing considers **all** topics (so it can
  suggest an existing topic the user isn't subscribed to — e.g. "Educational
  Research" — and subscribe them).

## Architecture

### A. Topic embedding index (foundation, reusable)
- **`bbv2/embeddings.py`** — `embed_texts(texts) -> list[list[float]]` via OpenAI
  `/v1/embeddings` (`text-embedding-3-small`, 1536-d) through `request_with_backoff`;
  raises `LLMError` on failure. Injectable for offline tests. Metered to the
  system bucket as purpose `embedding` (shows in 0027 cost metrics; add a label).
- **`topic_embeddings` table** — `topic_id`, `date`, `model`, `dim`,
  `vector` (BLOB: packed float32), `kind` ('brief'|'meta'), `created_at`,
  UNIQUE(topic_id, date). Cosine helpers + float32 (un)pack in a small util.
- **Generation (decoupled from brief-build path).** Briefs land in the `briefs`
  table whether built by `nightly` (subscribed topics) or on-demand
  (`get_or_build_brief`, accessed topics); a topic with **no subscribers and never
  accessed** (e.g. "Educational Research") has *no* brief at all. So embedding keys
  off the table + a guaranteed floor, not off the build moment:
  1. **Meta embedding floor** — every topic gets a `kind='meta'` embedding of its
     name+description at creation (backfilled for existing topics), so *any* topic
     is routable immediately regardless of briefs. (No brief-build cost for topics
     nobody reads.)
  2. **Nightly sweep `embed_pending_briefs(window=30d)`** — embed any brief in the
     window lacking a `topic_embeddings` row. Keying off the `briefs` table, it
     catches briefs built **either** way (nightly *or* on-demand) without caring
     which. Cheap (only new briefs). Runs at the end of `bbv2 nightly`.
  3. **`bbv2 embed-topics` CLI** — one-time backfill: meta embeddings for all
     topics + brief embeddings for existing briefs.
  We do **not** force nightly briefs for unsubscribed topics (wasteful) or embed on
  the Headlines hot path (latency) — the sweep + meta floor cover both.
- **Routing helper** — `store.topic_centroid(topic_id, days=30)` = mean of recent
  brief vectors if any, else the `meta` embedding; `rank_topics(query_vec) ->
  [(topic, score)]` (cosine vs every topic centroid, ranked). Pure-Python
  dot/cosine (no numpy dep).

### B. Topic-agnostic discovery (refactor)
`discover_sources()` is topic-first. Extract **`discover_for_query(query, *,
generate, …) -> {candidates, web_results}`** (no topic): craft 1-2 angle queries
(Grok) → `brave_search` → `discover_site_feeds` → validate → grab each feed's 2-3
latest entry titles (already parsed during the probe) → return candidates
(name/url/sample_headlines) **and** the raw Brave results. Rewire
`discover_sources()` to call it with the topic's name/description.

### C. Durable search run
**`discovery_runs`** table (mirrors `provision_runs`, + a `result_json` payload):
`id (SRCH…)`, `user_id`, `conversation_id`, `message_id`, `query`, `stage`
(searching→probing→ready), `status`, `result_json`, `error`, timestamps.
**`discovery_runner.py`** (bounded pool) runs `discover_for_query`, writes the
preview, flips status. Extend the 0025 orphan-reset to clear stuck runs on restart.

### D. Agent tool `find_sources(query)`
Creates a `discovery_run`, submits it, yields a `search_run` SSE event (run id) +
`tool_start/tool_end`; returns a tool_result so the agent says "I'm searching for
sources on … — I'll show you what I find." Background + polled → survives
navigation. Budget-gated + a dedicated per-user rate limit.

### E. Frontend results card (read-back without a re-prompt)
A `useDiscovery` hook (mirrors `useProvisioning`) polls `/api/discoveries` and, in
the assistant message, shows a **progress pill** → on done a **results card**:
discovered sources (name + latest headlines) + a few Brave results + an **"Add
these sources"** button (+ Dismiss). The card renders from the run's
`result_json`, so the **agent never has to re-read results to converse** — it
kicked the search; the card shows specifics; the agent later narrates placement.

### F. Placement (evidence) + commit
`commit_sources(run_id)` — the card's **Add** button or "yes, add them":
1. **Rank** — embed the query, `rank_topics(query_vec)` → per-topic cosine scores.
2. **Activate** — best topic if score ≥ `PLACEMENT_MIN`; also attach to any other
   topic ≥ `PLACEMENT_MULTI`; if none ≥ floor → **create a new topic** (name/desc
   from the query). *(Thresholds need empirical calibration — text-embedding-3
   cosines for related text often sit ~0.3-0.55; start ~0.32 floor / ~0.45 multi
   and tune. Log the scores so we can see real distributions.)*
3. **Commit** — attach the candidate sources to the chosen topic(s) (approve),
   collect + per-topic relevance review, subscribe the user, build a brief if in
   the onboarding window — reuse provision/collect/review.
4. **Narrate** — return the scores + decision so the agent says: "The evidence
   puts this closest to **Educational Research** (0.61) over AI (0.29) — added
   there and subscribed you."

## Phases

- **P1 — embedding index:** `embeddings.py` + `topic_embeddings` table + the
  **meta-embedding floor** (topic create + backfill) + nightly
  `embed_pending_briefs` sweep + `embed-topics` backfill CLI + centroid/cosine
  routing helper + `embedding` cost label. Offline tests with a fake embedder.
- **P2 — discovery engine:** `discover_for_query` + sample headlines + Brave
  passthrough; rewire `discover_sources`. Offline tests (fake searcher/feed-finder).
- **P3 — durable run + tool:** `discovery_runs` + `discovery_runner` +
  `find_sources` tool + `search_run` SSE + `GET /api/discoveries` + orphan reset.
- **P4 — results card:** `useDiscovery` hook + progress→results card
  (sources + headlines + Brave results + Add/Dismiss), mobile-friendly.
- **P5 — placement + commit:** `rank_topics` evidence + `commit_sources`
  (multi-topic attach + collect + review + subscribe) + `commit-discovery`
  endpoint for the Add button + agent narration.
- **P6 — conversational confirm + polish + docs:** the "yes, add them" path,
  guards, architecture/README/roadmap/CLAUDE updates.

## Reuse upside
The embedding index isn't just for this feature — it directly enables **semantic
Stories search** (embed items, cosine over the index) and is the concrete first
step toward the roadmap's **persistent clusters** (cluster item embeddings, label
them, route/filter by cluster). Building it here pays forward.

## Guards & cost
Metered to the user's daily budget (query crafting + discovery + an embed call);
embeddings to the system bucket. Dedicated rate limit on `find_sources`; capped
queries/sites; all fetches via `safefetch`. New-topic branch reuses topic
moderation; the query is sanitized. New env: `OPENAI_API_KEY`,
`OPENAI_EMBED_MODEL` (default `text-embedding-3-small`), `EMBED_CENTROID_DAYS`
(default 30), `OPENAI_EMBED_PRICE` (cost metrics), placement thresholds.

