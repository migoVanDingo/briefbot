# Deviations & notes — plans 0025–0028 (2026-06-27)

Implementation notes and where the build differed from the plans in
`_plans/0025`–`0028`. Recorded per the CLAUDE.md "keep docs current" rule.

## Review pass (pre-0025)

Four parallel review agents (security, modularity, correctness/concurrency,
frontend) produced the verified findings in `_plans/0025`. The four
highest-impact items were re-confirmed by hand before fixing. Net result: **193
pytest pass, dashboard build clean** (was 174 before this batch; +19 new tests).

## 0025 — review fixes

- **cookie_secure default NOT flipped.** The plan floated defaulting
  `cookie_secure()` to `True`. Kept the default `False` (local http dev needs it)
  and instead added a **startup WARNING** in `serve` when binding a non-localhost
  host with cookies insecure. Lower regression risk; prod already sets it true.
- **`email_verified` gate is conservative.** Exchange is rejected only when the
  claim is *explicitly* `False` (and owner-bootstrap requires it not be false).
  A *missing* claim is allowed — the real Firebase token always includes it, and
  this keeps the test fakes (which omit it) working. Closes the actual
  owner-impersonation path without breaking providers that omit the claim.
- **Concurrency dedup via locks/atomic claims, not a job queue.** `get_or_build_brief`
  uses a per-(topic,date) `threading.Lock`; topic-image + avatar use an atomic
  conditional-UPDATE claim (`claim_topic_image` / `claim_avatar`). Single-process
  app, so in-process is sufficient.
- **File split scope.** Only `dashboard_api.py` (the one **over** the 600 cap) was
  split — into `dashboard_briefs.py` + `dashboard_serial.py` (now 476 lines).
  `agent.py` (~573) and `cli.py` (~580) are **under** cap; their suggested splits
  (tool registry, `with_store`) are deferred to `roadmap.md`, not done.
- **Mobile onboarding tour.** Rather than anchor the existing steps to the hidden
  desktop nav, added a **mobile-specific step set** (body-centered intro + a step
  on the visible hamburger, which now carries `data-tour="menu"`).
- **Deferred (in roadmap, not done):** `provision_runner.start_run` dedup (H2),
  `api.ts` → `api.types.ts` (M5), `llm_errors()` wrapper (M4), and several
  frontend lows (useAsync hook, tap-target sizes, Google busy-guard, Settings
  number input, null-url StoryRow, dead-CSS prune). All low-value; do when next
  touched.

## 0026 — logging

- Replaced the old ad-hoc `cli._setup_logging` with `bbv2/logging_setup.py`
  (`configure_logging`, idempotent, env + `-v` driven, rotating file + stderr).
- uvicorn is started with `log_level=config.log_level().lower()` so its access/error
  logs align with ours. A global `@app.exception_handler(Exception)` logs unhandled
  500s with a traceback (4xx keep their own handlers and stay quiet).

## 0027 — metrics expansion

- **Image cost is per-image, not per-token.** Images record a `token_usage` row
  with 0 tokens (`purpose="image"`); `usage_summary` counts those rows and prices
  them at `config.image_price()` (`GROK_IMAGE_PRICE`, default $0.02), folding the
  cost into `overall`, the `image` by-purpose row, and the per-topic buckets.
- `"(background)"` → **"Not topic-specific"** + a `kind` flag (`topic`|`background`)
  so the UI marks it. One existing test (`test_usage_summary_attributes_by_topic`)
  was updated for the new label.
- Per-user drill-down is a **drawer** (right sheet on desktop, full-width bottom
  sheet < 560px) fed by `GET /api/admin/metrics/users/{id}`.

## 0028 — profiles + avatars

- **Avatar metering goes to the system bucket** (user_id 0), consistent with all
  image gen, so it shows in admin cost metrics but does **not** count against the
  user's personal token total on their profile (personal stats are token-only).
- **Blog is a client-only stub** (a "coming soon" card on `/profile`) — no API
  surface, per the plan's preference to avoid dead endpoints. The real blog engine
  is a future spaces plan (roadmap).
- `GET /api/avatar/{id}` is mounted on `app` (public, like topic images) and
  returns either the stored JPEG (`ready`) or the identicon SVG, so an `<img>`
  always resolves without auth juggling.

## Post-build `/code-review` pass (2026-06-28)

An 8-angle code review of the uncommitted batch surfaced 10 findings, all fixed:
- **Avatar rate-limit lockout** — a 409 ("already generating") was consuming a
  limiter slot; added a cheap `pending` pre-check before `limiter.check`.
- **Avatar/image stuck `pending`** after a mid-gen restart — added
  `store.reset_orphaned_image_jobs()` (called in `serve`, alongside
  `fail_orphaned_runs`) and let Profile show "Reset" on `error` too.
- **`user_detail` votes ignored the range** — scoped 👍/👎 + recent votes to the
  window (story_feedback.updated_at).
- **Headlines same-topic day race** — added a `cancelled` guard to the
  `briefStories` effect (the topic_slug guard only covered cross-topic switches).
- **MAX_LIMIT** restored 100 → **200** (the split had silently halved it).
- **by_model** now includes the per-image cost row so it reconciles with `overall`.
- **N+1** in the by_topic image fold replaced with one batched `WHERE id IN (…)`.
- **api.ts** (612 lines) split → `api.types.ts` (types) + `api.ts` (318-line client),
  back under the 600 cap — the deferred `0025` M5 item, now done.
- Removed the **dead `email_verified` conjunct** in the owner bootstrap.
- **Topbar avatar** now refreshes after a generation (shared `avatarVersion` in the
  auth store, bumped by Profile). Also added an unmount guard to Profile's polling.

+4 regression tests (avatar-lockout, orphan-reset, vote-range, by_model reconcile).
**197 pytest pass, pyflakes clean, tsc + build clean.**

## Not done / explicitly out of scope

- Did **not** push or deploy (per the request — review in the morning).
- Did **not** run the full `/code-review` skill on this batch; relied on the
  pre-implementation multi-agent review + new regression tests + green suite/build.
</content>
