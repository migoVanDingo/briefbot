# 0032 — deviations & notes (per-day images + LLM topic names)

Plan: `_plans/0032`.

## A. Per-day brief images

- Image moved from **topic** (`topics.image_path/image_status`) to **brief**
  (`briefs.image_path/image_status`), so each day's brief gets its own image,
  seeded from that day's summary. Files are `data/topic_images/<slug>-<date>.jpg`.
- `topic_image.maybe_kick(store, topic_row, brief_row)` now claims the **brief**
  (atomic `claim_brief_image`) and generates per `(topic, date)`; served at
  `GET /api/topics/{slug}/briefs/{date}/image` (replaces `/api/topics/{slug}/image`).
- Generation stays **lazy on view**, bounded to the latest brief per topic
  (`/briefs`, `topic_briefs[0]`, `/rundown`) — so each day accrues its own image as
  it becomes current; historical days aren't retroactively generated.
- Frontend `BriefCard` polls the **day-specific** brief (via `topic_briefs` matched
  on `brief.date`) for pending→ready, instead of always polling today's rundown.
- `reset_orphaned_image_jobs` now also clears stuck `briefs.image_status='pending'`.

### Deviations
- **Removed the dead per-topic `claim_topic_image`/`set_topic_image`** (no callers
  after the move). `topics.image_path/image_status` columns are **left in place**
  (vestigial) to avoid a destructive migration — they're simply unused now.
- **Existing topics keep their old single image only for days already generated;**
  there's no backfill of past briefs (cost). New days get fresh images going
  forward — which is the requested behavior.
- Per-day images cost ~1 Grok image per topic per day (lazy, gated by
  `TOPIC_IMAGES_ENABLED`).

## B. LLM-crafted new-topic names

- New-topic naming changed from title-casing the raw query
  (`_topic_name_from_query` → "Llm Security Vulnerabilities Attacks") to
  `_craft_topic_name(query, generate)`: one Haiku call → a short, broad-enough
  Title-Case name + one-line description (e.g. **"LLM Security"**). Falls back to
  the heuristic on any LLM error or when no generator is supplied.
- `commit_discovery` gained a `name_generate` param; the commit endpoint and the
  agent's `commit_sources` pass a metered Haiku generator (purpose `provision`).

### Notes / known limits
- **Routing into an EXISTING topic still requires `OPENAI_API_KEY`** (embeddings).
  Without it, `rank_topics` returns `[]` → every commit makes a *new* topic (now
  well-named). With it, whether "LLM security" joins your "AI"/"LLM" topic vs
  spawns a new one is governed by `BBV2_PLACEMENT_MIN` (default 0.32) — lower it to
  bias toward joining existing topics. The transcript's bad outcome was the *name*
  (fixed) plus likely no key set (→ always-new).
- The user can still rename/merge topics after the fact via admin.

## Tests
Rewrote `test_topic_image.py` for per-day brief images (dated file, per-day
maybe_kick, idempotent per day, distinct days each get one); updated
`test_profile.py` orphan-reset to the brief image; added
`test_craft_topic_name_*` + `test_commit_new_topic_uses_crafted_name`.
**233 pytest pass; pyflakes + tsc + build clean; all files under the 600-line cap.**
</content>
