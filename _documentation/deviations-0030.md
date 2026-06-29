# 0030 — deviations, decisions & known issues

Notes from building the topic embedding index + on-demand source discovery
(plan: `_plans/0030`). Recorded per the "keep docs current" rule.

## Decisions / deviations from the plan

- **`discover_sources` IS now a thin wrapper over `discover_for_query`** (the plan
  flagged this as risk). The shared core returns candidates as data; `discover_sources`
  persists them as `candidate` sources. All existing discovery tests still pass.
- **No on-topic-create meta embedding hook.** Instead of embedding a topic's meta
  vector at creation (network on the create path), `rank_topics` lazily calls
  `ensure_meta_embeddings` (a no-op once present) and the nightly sweep keeps it
  warm. Keeps topic creation network-free; first `find_sources` warms any gaps.
- **Embedding cost in metrics.** `estimate_cost` gained an embedding branch (model
  name contains "embed" → `OPENAI_EMBED_PRICE`/1M) so embeddings don't get
  mispriced at the Haiku rate. Metered to the system bucket, purpose `embedding`.
- **Commit collect+review is backgrounded, not inline.** `commit_discovery` does
  the fast part synchronously (rank → attach sources → subscribe → mark committed)
  and kicks `collect + quickscan` on a small pool, so the button/agent returns
  immediately. Stories appear shortly after.
- **Routing considers ALL topics with a vector**, including ones the user isn't
  subscribed to (so it can route to / create-subscribe an existing topic like
  "Educational Research" — the motivating transcript).

## Known issues / follow-ups

- **Placement thresholds are guesses.** `BBV2_PLACEMENT_MIN=0.32` /
  `BBV2_PLACEMENT_MULTI=0.45` are starting points — `text-embedding-3` cosines for
  related text often sit ~0.3–0.55. The commit logs the full score vector; tune
  these against real topics. Too-high a floor → everything becomes a new topic;
  too-low → sources land in loosely-related topics.
- **Cold start.** Routing quality scales with how many briefs a topic has embedded.
  Run `bbv2 embed-topics` after deploy to seed; brand-new/thin topics route on
  their meta (name+description) vector only until briefs accumulate.
- **Preview headlines depend on a live feed fetch.** A candidate feed that's slow
  or blocked yields a candidate with no sample headlines (still addable). The
  0029 auto-drop handles a feed that turns out dead after it's added.
- **`commit_sources` (conversational) targets the latest uncommitted run in the
  conversation.** If a user runs two searches and says "add them", it commits the
  most recent. The card's per-run **Add** button is unambiguous; prefer it.
- **add_source is INSERT-OR-IGNORE**, so a candidate URL that already exists as a
  *disabled* source is re-activated on commit (we `set_source_status` active) but
  keeps its old name. Rare (discovery dedupes against existing feeds).
- **No new-topic moderation LLM by default on the button path** beyond the keyword
  gate + classifier via the metered `moderation` generate passed from the route;
  the new-topic name is derived from the query (title-cased) then moderated.

## Tests

`test_embeddings.py` (math/store/generation/routing), `test_discovery.py`
(+`discover_for_query`), `test_discovery_runs.py` (durable run + `find_sources`
tool), `test_discovery_commit.py` (placement thresholds, route-to-existing,
new-topic, conversational path). All offline via a bag-of-words fake embedder +
fake searcher/feed-finder. **203 → 222 pytest pass; pyflakes + build clean.**

## File-size cap (deviation)

Adding the discovery handlers pushed `agent.py` (660) and `cli.py` (601) over the
600-line cap. Both were split: the run-spawning tool handlers moved to
`agent_runs.py` (`_create_topic_events`/`_find_sources_events`/`_commit_sources`/
`_slugify`), and `build_parser` moved to `cli_parser.py` (the deferred 0025 item).
All files are back under cap.
</content>
