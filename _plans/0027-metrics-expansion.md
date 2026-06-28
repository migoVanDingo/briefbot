# 0027 — Admin metrics expansion

Extend the existing `0021` metrics (which the user likes) rather than replace it.
Three asks: (1) make the token breakdown say **where tokens go and for what**
with friendly labels + estimated cost per purpose (image gen, summaries, brief,
agent chat, discovery, moderation, relevance); (2) fix the opaque "(background)"
topic label; (3) a **per-user drill-down** — click a name → that user's token
usage for the selected period, access frequency, subscriptions, and 👍/👎.

## Current state

- `store.usage_summary(since, until)` already returns `overall`, `by_model`,
  `by_purpose`, `by_topic`, `by_day` with estimated cost (`usage.estimate_cost`).
- Purposes in the wild: `chat`, `chat-turn` (interaction counter, 0 tokens),
  `rundown`, `discovery`, `provision`, `moderation`, `review`, `relevance`,
  `nightly`, `brief`. **No image metering yet.**
- `by_topic` lumps all NULL-`topic_id` spend into `"(background)"`.
- `/admin/metrics/llm?range=` and `/admin/metrics/users` exist; `Metrics.tsx`
  renders cards + tables with `overflow-x:auto`.

## Phases

- **P1 — Friendly purpose labels + descriptions (backend + shared).**
  A `PURPOSE_META` map (label + one-line description + category) in a small
  `bbv2/metrics_labels.py`. e.g. `chat → "Agent chat"`, `rundown → "On-demand
  topic brief"`, `discovery → "Source discovery"`, `brief/nightly → "Daily
  briefs"`, `moderation → "Topic moderation"`, `review/relevance → "Relevance
  review"`, `provision → "Topic provisioning"`, `image → "Header images"`.
  `usage_summary`'s `by_purpose` rows gain `label` + `description`. Unknown
  purposes fall back to a title-cased label.

- **P2 — Meter image generation.** On a successful Grok Imagine gen in
  `topic_image.py`, `store.record_usage(SYSTEM_USER_ID, "image", model, 0, 0,
  topic_id=tid)` (one row per image). Images don't use tokens, so cost is
  per-image: add `BBV2_IMAGE_PRICE` (default ~$0.02) to `config`, and in
  `usage_summary` compute image cost = `image_calls × image_price` and fold it
  into `overall.cost`, `by_purpose` (the `image` row), and `by_topic`. Add an
  `images` count to the summary so the UI can show "N images · $X".

- **P3 — De-opaque the topic bucket.** Rename `"(background)"` →
  `"Not topic-specific"` and add a `kind: "topic" | "background"` flag so the UI
  can render it distinctly (it's chat + moderation + system spend). Keep the
  by_purpose view as the primary "for what" answer.

- **P4 — Per-user drill-down (backend).** `store.user_detail(user_id, since,
  until)` →: token usage by purpose (reuse the fold, filtered to the user),
  total tokens + estimated cost, login/access frequency (`auth_events` count of
  `login` in window + `last_login_at` + distinct active days), subscriptions
  (topic names), and feedback (👍/👎 counts + recent voted items). New route
  `GET /admin/metrics/users/{id}?range=` (gated by `metrics:read`).

- **P5 — Frontend.** Extend `Metrics.tsx`:
  - by_purpose table shows the friendly label + description tooltip + cost.
  - a small "Header images" stat (count + cost).
  - user rows become clickable → a drawer/modal (mobile-friendly, full-width
    sheet < 560px) showing the per-user detail (period-scoped usage-by-purpose,
    access frequency, subscriptions chips, 👍/👎). Reuse existing table/card CSS.

## Tests

- `usage_summary` includes `label` on by_purpose rows and image cost when image
  rows exist.
- image metering records a row; cost folds in.
- `user_detail` returns correct period-scoped tokens, subs, votes for a seeded user.

Non-breaking; purely additive to the metrics surface.
</content>
