# 0024 — Per-topic header images (Grok Imagine)

**Status:** ✅ Implemented (2026-06-27) — 172 backend pytest pass, dashboard
tsc/build clean.
**Phase:** Build · **Depends on:** brief engine (0008), Grok client (0011).

A **per-topic** header image, shown on the Headlines brief, generated **once** in
the background via **Grok Imagine** (system call; reuses `GROK_API_KEY`). Decided
with the user: per-topic (stable identity, not per-day), Headlines header only,
background generation with a loading state.

## Design (as built)

- **API:** `POST https://api.x.ai/v1/images/generations`, model
  `grok-imagine-image-quality` (env `GROK_IMAGE_MODEL`), `response_format=b64_json`
  (the URL form is temporary), `aspect_ratio=16:9`, `resolution=1k`. New
  `llm.grok_image() -> bytes`.
- **Schema:** `topics.image_path` + `image_status` (`none|pending|ready|error`).
- **Generation** (`topic_image.py`, bounded pool): `maybe_kick(store, topic, summary)`
  is idempotent — the first time a topic has a brief but no image, it marks the
  topic `pending` and spawns a background job that feeds a house-style prompt
  (topic name + brief-summary gist, "no text/logos") to Grok, downloads the bytes,
  stores `data/topic_images/<slug>.jpg`, sets `ready`. Any failure (incl.
  moderation) → `error`, no image. Kicked from the `/briefs`, `/topics/{slug}/briefs`,
  and `/rundown` endpoints.
- **Serving:** public `GET /api/topics/{slug}/image` (FileResponse) — mounted on
  the app, not the authed router, so an `<img>` loads cross-origin in dev without
  the session cookie (the image is a non-sensitive AI illustration).
- **Frontend:** `BriefCard` shows the image as a banner; a **shimmer** placeholder
  while `pending`, polling the (cached) rundown until `ready`, then swapping it in.

## Notes / deviations

- **Per-topic, generated once** (not per-brief/day) per the user's choice — cheaper,
  stable. Re-generation is not yet exposed (an admin "regenerate" button is a
  follow-up; an `error` topic stays imageless until then).
- Query/brief LLMs unchanged: **Haiku** still writes the summary; **Grok** makes the
  image — consistent with "Grok for system calls, Haiku for user-facing prose."
- Cost is a **system-bucket** concern (~$0.05–0.10/image, once per topic). Not
  token-metered (image gen isn't token-based).
- Tests stub the image fn / set `TOPIC_IMAGES_ENABLED=false` (conftest) so no test
  hits the network.

## Done when

A subscribed topic's Headlines brief shows a generated header image — a shimmer
while it's being made, then the image — created once per topic from its summary,
with sensitive topics gracefully falling back to no image.
