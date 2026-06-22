# 0018 — Persist UI state in the DB (kill the localStorage replay bug)

**Status:** ✅ Implemented (2026-06-22) — all 5 phases shipped; 2 new backend
tests + dashboard `tsc`/build green. Shipped **alongside 0019** in one pass.
**Phase:** Build · **Depends on:** current dashboard auth (`/api/me`).
**Sibling:** [0019 auth + RBAC + spaces](./0019-auth-rbac-and-spaces.md) — independent;
ship either order (see Sequencing).

## Implementation notes / deviations

- **Built together with 0019**, so `api.ts` already uses the cookie session — the
  prefs/flags helpers ride on it (the "Sequencing" note's both-orders case).
- **Backend prefs/flags routes live in `bbv2/dashboard_prefs.py`** (`add_prefs_routes`),
  not inline in `dashboard_api.py` — extracted to keep that file under the 600-line
  cap after the 0019 additions. Same routes/behavior as specced.
- Schema/helpers exactly as planned: `user_settings.theme`/`accent` columns +
  `user_flags` table (idempotent `_migrate`); `set_user_settings(theme=,accent=)`,
  `get/set/clear_user_flag`. `/api/me` gains `preferences` + `flags`.
- Kept `bbv2.lastChat` device-local as decided; `bbv2_tour_done`/`bbv2.tour.*`
  localStorage reads removed (server flags now authoritative — the replay fix).
- Added the optional Settings **"Replay tutorials"** button (Phase 4.5).

Move the user-meaningful client state out of `localStorage` and into the DB so it
**follows the user across devices/browsers and survives a storage clear or an
incognito window.** Today the theme and the tutorial-seen flags live only in
`localStorage`, so the Joyride tours **replay** every time storage is cleared or a
new browser is used, and the chosen theme resets to the OS default. Both should be
per-user server state.

## Current state (audited)

Four `localStorage` keys, no sessionStorage/cookies/IndexedDB:

| Key | File | Holds | Disposition |
|---|---|---|---|
| `bbv2.theme` | `dashboard/src/theme.ts:69,73,82` | `"light"\|"dark"` | **→ DB** (mirror kept for anti-FOUC) |
| `bbv2_tour_done` | `dashboard/src/components/OnboardingTour.tsx:9,51,68` | global onboarding seen flag | **→ DB** (consolidate w/ `onboarded_at`) |
| `bbv2.tour.{page}` | `dashboard/src/components/PageTour.tsx:11,17,29` | per-page tour seen (`headlines/stories/topics/favorites`) | **→ DB** |
| `bbv2.lastChat` | `dashboard/src/pages/Chat.tsx:39,64` | last-opened conversation id | **KEEP local** (see Decisions) |

Server already has the seams: `user_settings` is a 1:1 per-user row
(`store.py:124`) with an `onboarded_at` column (`store_users.py:119` +
`_migrate` `store.py:275`), and `/api/me` (`dashboard_api.py:122`) already returns
a `settings` block the dashboard reads on boot. We extend both.

## What this is NOT

- **Not** moving `bbv2.lastChat` — it's a per-device convenience pointer, already
  validated server-side against the user's own conversations (`Chat.tsx:99`).
  Syncing "last chat" across devices is a mild anti-feature; left in `localStorage`.
- **Not** the accent **color picker** itself (still roadmap) — but we add the
  `accent` column now so that plan becomes a pure frontend task.
- **Not** caching headlines/stories/favorites locally (already server-fetched).

## Decisions

1. **Two stores, by shape.** *Editable preferences* (theme, accent — things the
   Settings page sets and Settings will grow) go in **typed columns on
   `user_settings`**. *Write-once "seen" flags* (tours, dismissed banners — an
   open-ended, growing set of booleans keyed by string) go in a generic
   **`user_flags`** key table. Typed columns stay strongly-typed and easy to read;
   flags stay flexible without an `ALTER` per new tour. Mirrors mass-platform's
   split of typed `user_preference` columns vs. a JSON prefs bag.
2. **`localStorage` becomes a non-authoritative cache, only for theme.** Theme is
   applied *before* auth resolves (avoid a flash of the wrong theme), so we keep a
   `localStorage` mirror for the instant pre-auth paint, then reconcile to the DB
   value once `/api/me` loads. DB is the source of truth; the mirror is a perf hint.
   Tours don't paint pre-auth (they only run when logged in) → **no** `localStorage`
   fallback for tours; the DB flag is authoritative. This is what fixes the replay.
3. **Consolidate global onboarding onto the server flag.** `bbv2_tour_done` is
   today *intentionally decoupled* from `onboarded_at`. We collapse them: the
   onboarding tour fires off the server `onboarding_done` flag and marks it via API.
4. **Schema via the existing idempotent `_migrate`** (`store.py:265`) — `ALTER
   TABLE … ADD COLUMN` + `CREATE TABLE IF NOT EXISTS`. No Alembic (SQLite, personal
   scale; matches the repo).

## Phase 1 — Backend: schema + store helpers

1.1 **`user_settings` columns** (via `_migrate`): `theme TEXT` (nullable → "follow
    OS" when null), `accent TEXT` (nullable; forward-looking for the picker).
1.2 **`user_flags` table** (in `SCHEMA_SQL`):
    ```sql
    CREATE TABLE IF NOT EXISTS user_flags (
        user_id INTEGER NOT NULL,
        flag    TEXT    NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, flag)
    );
    ```
    Presence = set/seen. Flags: `onboarding_done`, `tour:headlines`, `tour:stories`,
    `tour:topics`, `tour:favorites` (namespaced so future banners slot in).
1.3 **Store helpers** (`store_users.py`): extend `set_user_settings(...)` with
    `theme`/`accent`; `get_user_flags(user_id) -> set[str]`; `set_user_flag(user_id,
    flag)` (idempotent `INSERT OR IGNORE`); `clear_user_flag(user_id, flag)` (for a
    "replay all tutorials" reset). Keep `mark_onboarded` writing the flag too, or
    redefine `is_onboarded` over the flag — pick one source (Decision 3).

## Phase 2 — Backend: API

2.1 **Extend `/api/me`** (`dashboard_api.py:122`) to return:
    ```jsonc
    "preferences": { "theme": "dark"|"light"|null, "accent": null },
    "flags": ["onboarding_done", "tour:headlines", ...]
    ```
    (Keep the existing `settings`/`onboarded` keys for now; `onboarded` derives from
    the `onboarding_done` flag.)
2.2 **`PATCH /api/preferences`** — body `{theme?, accent?}`, validated
    (theme ∈ {light,dark} or null; accent a short hex/`null`); writes via
    `set_user_settings`. Per-user, no special role. Covered by the default rate limit.
2.3 **`PUT /api/flags/{flag}`** (idempotent set) + **`DELETE /api/flags/{flag}`**
    (reset, powers "replay tutorials"). `flag` validated against an allowlist set so
    the table can't be spammed with arbitrary keys.

## Phase 3 — Frontend: theme

3.1 **`theme.ts`** — split init into `cachedTheme()` (reads the `localStorage`
    mirror, else OS) for the instant pre-auth paint, and keep `applyTheme` writing
    the mirror *and* `data-theme`. Add `reconcileTheme(serverTheme)`: if the server
    has an explicit theme, apply it (updates mirror); if null, leave the cached/OS
    choice.
3.2 **`themeStore.ts`** — `toggle()` writes through: `applyTheme(next)` + `set(...)`
    **and** `api.patchPreferences({theme: next})` (optimistic; on failure toast +
    revert). Add `hydrate(serverTheme)` called once after `/api/me` resolves.
3.3 Call `hydrate` from wherever `/api/me` lands in the auth store (`state/auth.ts`).
    Logged-out users keep the cache/OS behavior unchanged.

## Phase 4 — Frontend: tours off the server flags

4.1 **`PageTour.tsx`** — drop the `localStorage.getItem(key)` gate; auto-run when
    `ready && !flags.has(\`tour:${page}\`)`. On finish/skip, `setRun(false)` +
    `api.setFlag(\`tour:${page}\`)` and update the in-memory flag set so it doesn't
    re-arm this session. The ⓘ relaunch button still force-runs locally.
4.2 **`OnboardingTour.tsx`** — gate on the server `onboarding_done` flag (via the
    auth store), mark complete through `api.setFlag("onboarding_done")`. Remove
    `bbv2_tour_done`.
4.3 **Flags into the auth store** — load `flags` from `/api/me` into `state/auth.ts`
    (or a small `usePrefs` store); expose `hasFlag`/`setFlag` (setFlag also calls the
    API). Tours read these, not `localStorage`.
4.4 **`api.ts`** — `patchPreferences`, `setFlag`, `clearFlag` helpers (reuse the
    existing authed-fetch wrapper).
4.5 **Settings page** — optional small win: a **"Replay tutorials"** button that
    `DELETE`s the `tour:*` + `onboarding_done` flags (now possible because state is
    server-side). Theme toggle already lives in the shell.

## Phase 5 — Verify + docs

- **Tests** (`tests/test_dashboard_api.py`): `/api/me` returns preferences+flags;
  `PATCH /api/preferences` persists + validates (bad theme → 422); `PUT/DELETE
  /api/flags` idempotent + allowlist-gated; flag survives a fresh `/api/me`
  (the replay-bug regression test). `tsc && vite build` clean.
- `/code-review` per CLAUDE.md; address findings.
- Update `_documentation/architecture.md` (preferences/flags model) + `README.md`;
  prune `roadmap.md` (the localStorage debt item).

## Sequencing vs. 0019

Independent. 0018 rides on the **current** Firebase-Bearer `/api/me`. If 0019
(cookie/JWT auth) ships first, 0018's only change is that `api.ts` helpers use the
cookie session instead of the Bearer header — the schema, endpoints, and tour logic
are unchanged. Recommended order: **0018 first** (small, self-contained, fixes a
visible bug), then 0019. Both return their state through the same `/api/me`.

## Done when

A user picks dark mode and finishes the tours on one browser, opens the app in a
fresh incognito window on another machine, and gets **dark mode with no tours
replaying** — because theme and tour-seen flags now live in the DB keyed to their
account, with `localStorage` only smoothing the first paint.
