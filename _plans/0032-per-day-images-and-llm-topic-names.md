# 0032 — Per-day brief images + LLM-named discovered topics

Two fixes from real use.

## A. Topic images are the same every day → make them per-brief

**Diagnosis:** images are stored **per topic** (`topics.image_path/image_status`)
and `topic_image.maybe_kick` only fires when the topic's status is unset — so an
image is generated **once, ever**, and every day's brief shows it. (Hypothesis (a):
generated once; not a display bug.)

**Fix:** move the image to the **brief** (`(topic, date)`), so each new day's brief
gets its own image, seeded from that day's summary.
- Schema: `briefs.image_path`, `briefs.image_status` (default `none`).
- Store: `claim_brief_image(topic_id, date)` (atomic none→pending),
  `set_brief_image(topic_id, date, path, status)`.
- `topic_image.py`: `maybe_kick(store, topic_row, brief_row)` claims the **brief's**
  image, generates seeded from `brief["summary"]`, writes
  `data/topic_images/<slug>-<date>.jpg`, sets the brief's status. Meters one image.
- Serve: `GET /api/topics/{slug}/briefs/{date}/image` (FileResponse from the brief's
  `image_path`) — replaces the per-topic `/api/topics/{slug}/image`.
- `serialize_brief`: `image_status`/`image_url` from the **brief row** (date URL).
- Callers (`/briefs`, `/topics/{slug}/briefs`, `/rundown`) pass the brief row.
- Generation is **lazy on view** (only briefs people look at), bounded to the
  latest brief per topic — so each day accrues its own image as it becomes current.
- Frontend `BriefCard` polls the **day-specific** brief (via `topic_briefs` matched
  on `brief.date`) for the pending→ready swap; date URLs differ per day so there's
  no cross-day cache collision. `topics.image_*` columns become vestigial (left).

## B. New discovered topics get awful names → LLM-craft them

**Diagnosis:** when a search routes to a *new* topic, the name is just the
title-cased raw query — e.g. "LLM security vulnerabilities attacks" →
**"Llm Security Vulnerabilities Attacks"** (awkward + far too narrow to ever have
much news).

**Fix:** craft a concise, appropriately-broad topic from the query with one Haiku
call.
- `_craft_topic_name(query, generate) -> (name, description)`: prompt for a short
  TITLE-CASE topic name (1-4 words, a subject area not a search phrase) + a one-line
  description; parse JSON; fall back to the heuristic on any error. e.g.
  "LLM security vulnerabilities attacks" → **"LLM Security"** /
  "Security vulnerabilities and attacks against large language models."
- `commit_discovery` new-topic branch uses it; `name_generate` (metered Haiku) is
  passed from the endpoint + the agent's `commit_sources`.
- Routing into an EXISTING topic (AI / an "LLM Security" the user already has) is
  unchanged and **requires `OPENAI_API_KEY`** (embeddings); without it, every
  commit makes a new topic — now at least sensibly named. Calibrating
  `BBV2_PLACEMENT_MIN` controls how readily a query joins an existing topic vs
  spawns a new one.

## Tests
- brief image: `claim_brief_image` is atomic/idempotent; `maybe_kick` claims the
  brief (not the topic); serialize points at the date URL.
- topic naming: `_craft_topic_name` returns the LLM name + falls back on error;
  `commit_discovery` new-topic uses the crafted name.

## Notes
Per-day images cost one Grok image per topic per day (lazy, gated by
`TOPIC_IMAGES_ENABLED`). `topics.image_*` left in place (unused) to avoid a
destructive migration.
</content>
