# 0028 — User profiles + spaces foundation

Build the user-facing profile on top of the `0019` spaces foundation (every user
already has a personal `space` via `ensure_personal_space`). Profile = avatar +
personal metrics + a stubbed blogs section.

## Asks

- **Profile page** for the signed-in user.
- **Avatar:** no image upload. Default is a **GitHub-style identicon** generated
  deterministically from the user (no LLM). Optionally the user submits a **text
  prompt** → Grok Imagine generates a 1:1 avatar (background job, loading state).
- **Personal metrics:** topics subscribed; tokens used **and total cost** for
  day / week / month / year / all-time.
- **Blogs:** a **stub only** — placeholder section, no real blog engine.

## Reuse / patterns

- Mirror `topic_image.py` (bounded pool, `image_status` none→pending→ready→error,
  public `FileResponse` endpoint, `maybe_kick` idempotent claim) for avatars.
- Mirror `usage.estimate_cost` for per-window cost; metered to `"image"` (0027).
- IDs via `ids.py`; schema via `_migrate` ALTERs (no Alembic).

## Phases

- **P1 — Schema.** `_migrate` adds to `users`: `avatar_path TEXT`,
  `avatar_status TEXT DEFAULT 'none'`, `avatar_prompt TEXT`. (Identicon needs no
  storage — it's generated on the fly.)

- **P2 — Identicon.** `bbv2/identicon.py::identicon_svg(seed: str, size=240) ->
  str`: GitHub-style 5×5 mirrored grid, color derived from a hash of the seed
  (user email/id), on a light background. Pure + deterministic → unit-testable.

- **P3 — Avatar gen + serving.** `bbv2/avatar_image.py` mirrors `topic_image`:
  `start_avatar(store, user_id, prompt)` claims `avatar_status='pending'`
  (conditional UPDATE) and submits to a bounded pool; the worker calls
  `llm.grok_image(prompt, aspect_ratio="1:1", resolution="1k")`, writes
  `data/avatars/<user_id>.jpg`, sets `ready` (or `error`), and meters one
  `"image"` usage row. Routes:
  - `GET /api/avatar/{user_id}` — public-on-app (like topic image): the stored
    JPEG if `ready`, else the identicon SVG (so it always renders).
  - `POST /api/profile/avatar` `{prompt}` — rate-limited, budget-gated; kicks gen.
  - `DELETE /api/profile/avatar` — revert to identicon (clear path/status).

- **P4 — Profile + personal metrics (backend).**
  `store.user_profile_stats(user_id, now_iso)` → `{subscriptions: [...names],
  usage: {day, week, month, year, all: {tokens, cost}}}` (cost folded per model
  via `estimate_cost`). `GET /api/profile` returns the user (name, email, role,
  avatar_status, member_since) + stats. Self-only (uses `current_user`).

- **P5 — Frontend `/profile`.** New page + nav entry (and the avatar in the
  topbar/hamburger). Sections:
  - Avatar card: current avatar (identicon or generated) + a prompt input and
    "Generate avatar" button (loading/poll like BriefCard) + "Reset to default".
  - Personal metrics: small stat cards for subscriptions and tokens+cost across
    the five windows (reuse the metrics card CSS).
  - Subscriptions: chips/list of subscribed topics.
  - **Blogs (stub):** a card "Blogs — coming soon" with a disabled "New post".
  All mobile-friendly (stacked cards, full-width < 560px, ≥40px tap targets).

- **P6 — Blog stub (backend, minimal).** No engine. Either a no-op
  `GET /api/profile/blogs → {posts: []}` returning empty, or simply render the
  stub client-side with no endpoint. Prefer client-only stub to avoid dead API
  surface; leave a `roadmap.md` note for the real blogs/spaces plan.

## Tests

- `identicon_svg` is deterministic and valid SVG; differs by seed; is symmetric.
- avatar claim is idempotent (second `maybe`/`start` while pending is a no-op).
- `user_profile_stats` returns correct per-window tokens/cost + subs for a seeded
  user (use injected `now`).
- `GET /api/avatar/{id}` returns SVG for default, the JPEG once ready.

## Notes

This is the **profile** slice of user-spaces; topic/headline scoping per space
and space invites remain a later plan (keep them in `roadmap.md`). Existing
features stay global.
</content>
