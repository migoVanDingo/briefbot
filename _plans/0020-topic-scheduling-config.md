# 0020 — Per-topic scheduling + caps (admin config tab)

**Status:** ✅ Implemented (2026-06-22) — backend + Admin → Scheduling UI; 157
backend pytest pass, dashboard tsc/build clean.
**Phase:** Build · **Depends on:** 0014 (cadence/tick engine), 0019 (RBAC capabilities).
**Sibling:** [0021 metrics](./0021-admin-metrics.md), [0022 consumer API](./0022-consumer-api-trader.md).

## Implementation notes / deviations

- **Discovery schedule is human-friendly: "run every {day|week|month|year}
  starting <date> at <time>"** (columns `discover_period`/`discover_start_date`/
  `discover_at_min`; weekday/day-of-month derived from the start date in
  `_discover_due`). Replaced the earlier raw-minutes/freq model after review —
  nobody reads 10080 as "weekly". Collection stayed an interval (per-topic
  `collect_interval_min`, shown in the UI as hrs:min) — already delivers "crypto
  every 15 min"; collect time-of-day is an easy follow-up.
- **Per-topic caps**: `topics.max_sources` / `max_stories_per_source` (NULL →
  env default); the per-source story cap resolves as the **most-permissive (MAX)**
  across a shared source's topics (`eff_max_stories`). Reset = NULL (per-topic +
  global).
- **`SCHEMA_SQL` extracted to `bbv2/schema.py`** so `store.py` stayed under the
  600-line cap; scheduling routes live in `bbv2/dashboard_schedule.py`.
- **Server step (not in repo):** the `tick` crontab must be changed to `*/15` on
  the VM — documented in `devops.md`; `SCHEDULER_WINDOW_MIN` must match it.
- Missed-tick caveat: a `daily`/`weekly` slot that the server is down for is
  skipped that day (no catch-up) — acceptable at personal scale, noted in config.

Give the admin real control over **when each topic pulls and how much** — e.g.
`tech`/`ai` discover **nightly**, `crypto` collects **every 15 min** to keep the
`trader` feed hot — from a dedicated **Admin → Scheduling** tab. Per-topic
**story/source caps** become editable (env values stay the default) with a
**reset-to-default** (per-topic or global). Admin-only.

## What already exists (extend, don't rebuild)

- Topics carry `discover_interval_min` / `collect_interval_min`; sources carry a
  `collect_interval_min` override (`store.py`). Settable via
  `PATCH /api/topics/{slug}/cadence` + `/api/sources/{id}/cadence`
  (`dashboard_api.py`, gated by the `cadence:set` capability).
- `bbv2 tick` (`scheduler.py`) is the **due-based heartbeat**: it runs only what's
  due (`_due(last_iso, interval_min, now)`), so most ticks are cheap no-ops.
- Global caps: `config.max_sources_per_topic()` (5), `config.max_stories_per_source()`
  (7) — read at discovery/collect time.

## What this is NOT

- **Not** real per-topic OS cron jobs. The OS cron stays a single heartbeat; each
  topic's schedule lives in the DB and `tick` honors it.
- **Not** full cron expressions — a small {interval | daily@HH:MM | weekly} model.
- **Not** the brief/email schedule (`nightly` stays 11pm) — this is discover+collect.

## Decisions (confirmed 2026-06-22)

1. **Heartbeat → every 15 min.** Bump the server crontab from hourly to `*/15`.
   Free (due-gated), and 15 min becomes the finest granularity. Document in devops.
2. **Schedule model per topic, for discover + collect independently:**
   - `interval` — every N minutes (reuses the existing `*_interval_min` columns).
   - `daily` — at a minute-of-day (UTC; server runs UTC).
   - `weekly` — weekday + minute-of-day.
3. **Per-topic caps** `max_sources` + `max_stories_per_source` (nullable). `NULL`
   ⇒ fall back to the env default. **Reset** = set back to `NULL`.

## Phase 1 — Schema + schedule engine

1.1 **Topic columns** (idempotent `_migrate`): `discover_freq` / `collect_freq`
    (`'interval'|'daily'|'weekly'`, default `'interval'`), `discover_at_min` /
    `collect_at_min` (INTEGER minutes-into-day, for daily/weekly), `discover_weekday`
    / `collect_weekday` (0–6), plus caps `max_sources`, `max_stories_per_source`
    (nullable). `*_interval_min` stay for interval mode.
1.2 **`scheduler._due` → schedule-aware** `_due_schedule(freq, interval_min,
    at_min, weekday, last_iso, now, tick_window_min)`:
    - `interval`: unchanged elapsed-time check.
    - `daily`: due if `now`'s minute-of-day is within the tick window of `at_min`
      **and** `last_iso` isn't already today (UTC date compare).
    - `weekly`: same + `now.weekday() == weekday`.
    `tick_window_min` = the heartbeat interval (15) so a daily slot fires once.
1.3 **Caps wired**: `discovery.discover_sources` and `collect.collect_source` read
    the topic's `max_sources` / `max_stories_per_source` ?? the env default
    (thread the topic row through, or a `store.topic_caps(slug)` helper).

## Phase 2 — Backend API (admin)

2.1 **`GET /api/admin/schedule`** (cap `cadence:set`) — every topic with its
    resolved schedule + caps + `last_discovered_at` / `last_collected_at` + the
    env defaults (so the UI can show "default (7)").
2.2 **`PATCH /api/topics/{slug}/schedule`** — set discover/collect freq + interval/
    time/weekday + caps. Validates ranges (minute 0–1439, weekday 0–6, positive
    caps). Supersedes the narrow `/cadence` endpoint (keep it as a thin alias).
2.3 **`POST /api/topics/{slug}/schedule/reset`** and **`POST /api/admin/schedule/reset`**
    (global) — null the per-topic caps (and optionally schedule) back to defaults.
2.4 Store helpers in `store_schedule.py`: `set_topic_schedule(...)`,
    `reset_topic_schedule(slug)`, `reset_all_schedules()`, `topic_caps(slug)`.

## Phase 3 — Admin UI (Scheduling tab)

3.1 New route `/admin/scheduling` (capability-gated, like `/admin/topics`) +
    a tab/link in the admin area. `api.ts` helpers for the Phase-2 endpoints.
3.2 A table: one row per topic — **Discover** and **Collect** each with a
    frequency control (Every N min · Daily @ time · Weekly @ day/time), plus
    **Sources cap** and **Stories/source cap** inputs (placeholder shows the
    default), a **Reset** per row, and a **Reset all** button. Shows
    `last_*_at` as "last ran".
3.3 Inline save per row (PATCH); toast on success/validation error.

## Phase 4 — Cron + verify + docs

4.1 **Crontab → `*/15`** for `tick` on the VM; update `_documentation/devops.md`
    (the runbook's cron section) + note 15 min is the finest granularity.
4.2 **Tests** (`tests/test_scheduler.py` + `test_dashboard_api.py`): `daily`/`weekly`
    due-logic (fires once in the slot, not again same day; respects weekday);
    per-topic caps override the env default; reset → null → default; schedule PATCH
    validation + non-admin 403. Offline (inject `now`).
4.3 Update `architecture.md` (schedule model), `roadmap.md`, `.env.example`
    (defaults unchanged, note they're now per-topic-overridable).

## Done when

An admin opens **Admin → Scheduling**, sets `tech` discovery to **daily @ 02:00**
and `crypto` collection to **every 15 min** with a **20-story** cap, and the next
ticks honor exactly that — while a one-click **Reset** drops a topic back to the
env defaults. The heartbeat runs every 15 min with no added LLM cost.
