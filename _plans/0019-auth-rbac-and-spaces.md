# 0019 — Backend auth, RBAC + capabilities, and a user-spaces foundation

**Status:** ✅ Implemented (2026-06-22) — all 6 phases shipped; **149 backend
pytest pass** (incl. new `tests/test_auth_rbac.py`), dashboard `tsc`/build green,
CLI verified.
**Phase:** Build · **Depends on:** 0009 (owner-only admin), 0016 (hardening).
**Reference:** `mass-platform/mass-user-management` + `mass-platform-common`
(read-only guide — patterns adapted to SQLite / single-backend / personal scale).
**Sibling:** [0018 persist UI state](./0018-persist-ui-state-in-db.md).

## Implementation notes / deviations

- **`add_dashboard_routes` keeps its `(app, store, verifier)` signature and now
  internally mounts `add_auth_routes`** (exchange/session/logout + admin user-mgmt).
  This kept the cli/test call sites unchanged; tests just POST `/api/auth/exchange`
  once (TestClient persists the cookies) — folded into each `_client()` helper.
- **`current_user` accepts the access JWT from the cookie OR an
  `Authorization: Bearer <access-jwt>`** (programmatic clients). The **Firebase**
  token is accepted only at `/exchange`. Revocation is immediate: every request
  checks `session_active(sid)` + `status='active'` (one indexed query each), so
  "force-revoke sessions" / "disable" take effect at once (stronger than mass's
  refresh-time-only revocation).
- **Capability tightening done** (not just the mechanical `require_admin` alias):
  curation routes use `topics:curate` / `sources:approve` / `brief:generate` /
  `cadence:set`; `owner` holds `*`, `admin` holds all of them.
- **Legacy role `human` ≡ `user`** in `rbac.global_capabilities` — avoided a data
  migration of existing rows; new dashboard users still upsert as `human`.
- **Module split for the 600-line cap:** `dashboard_prefs.py` (0018 routes) and
  `dashboard_chat.py` (conversations/chat routes) were extracted from
  `dashboard_api.py`; `auth_api.py`, `authjwt.py`, `rbac.py`, `store_sessions.py`,
  `store_spaces.py` are new. `store.py` (586) / `dashboard_api.py` (540) under cap.
- **JWT secret:** `BBV2_JWT_SECRET` env; when unset, a process-stable fallback is
  used and `bbv2 serve` prints a warning (sessions then drop on restart). Pinned
  `PyJWT==2.13.0` in `requirements.txt` (already present transitively).
- **Spaces:** foundation only, as planned — tables + membership + auto personal
  space + `GET /api/spaces` + capability scoping primitive; no route is space-scoped
  yet (topics/headlines stay global; that migration is a later plan).
- **Not done (out of original scope, noted):** no spaces/admin-users **UI** beyond
  what RBAC needs (CLI + admin API cover management); consumer `api.py` tokens
  untouched.

Replace today's **stateless, email-string** auth with a real backend identity
layer, modelled on `mass-user-management` but right-sized for briefbot:

1. **Sessions** — exchange the Firebase ID token for briefbot's **own** access JWT
   (short-lived, audience-scoped) + an opaque **refresh token** in a
   `user_sessions` table (rotation + server-side revocation).
2. **RBAC** — replace hardcoded `role == 'admin'` checks with **roles → named
   capabilities**, resolved **globally and per-space**.
3. **Spaces** — a `spaces` + `space_membership` foundation so the future
   blogs/learning/personalization "user spaces" have a home and per-space roles from
   day one.
4. **Lifecycle + audit** — user `status` (active/disabled), `last_login_at`, and an
   `auth_events` log (the "logging" gap).

## Why change (today's gaps)

- **No backend session/token management.** `current_user` verifies the Firebase ID
  token statelessly on every request (`dashboard_api.py:51`, `auth.py:32`). There's
  no server record of a session, **no way to revoke a user or force logout**, no
  login audit.
- **Roles are a single string.** `users.role` is `'human'|'admin'`
  (`store.py:110`); admin is whoever's email is in `ADMIN_EMAILS`
  (`config.py:112`); the 9 gated routes each do `require_admin` →
  `role == 'admin'` (`dashboard_api.py:86`). No granularity, no per-resource scope.
- **No multi-tenant seam.** Topics/headlines/favorites are global; there's nothing
  to hang "user spaces" off of.

## What we keep / what's out of scope

- **Firebase stays the IdP.** We still `verify_id_token` — but only **once**, at
  `/api/auth/exchange`, then issue our own session. (Mirrors mass:
  `exchange_token_handler.py:77`.)
- **Consumer API tokens unchanged.** `api.py` service tokens (`store_consumer.py`)
  are a separate auth path for the `trader` integration — untouched here.
- **Not bit-masked permissions.** We use named capabilities, not mass's permission
  bits — simpler for 3 users, still composable. (Decision below.)
- **Spaces: foundation only.** Tables + membership + auto personal space +
  capability-scoping primitives. Existing features stay **global** this round; the
  space-scoping migration of topics/headlines is a later plan. No spaces UI beyond
  what RBAC needs.

## Decisions (confirmed 2026-06-22)

1. **Exchange → own JWT + refresh** (mass-exact mechanism). HttpOnly cookies, not a
   Bearer header (the dashboard is same-site behind Tailscale; `SameSite=Strict`
   covers CSRF). Access JWT ~15 min, refresh ~30 days with a rotation chain.
2. **RBAC = roles + named capabilities**, scoped **global + per-space**. A global
   role grants global caps; a space-membership role grants caps **within that
   space**. `require_capability(cap, space_id=None)`.
3. **Spaces foundation now** — `spaces` + `space_membership`; every user gets an
   auto-provisioned **personal** space on first exchange.
4. **Owner bootstrap stays `ADMIN_EMAILS`.** That allowlist now maps to the
   **`owner`** role (the only role with `user:manage`). `admin` becomes a grantable
   role (owner-assigned, CLI/API) — there's still no self-serve promotion.
5. **Schema via the idempotent `_migrate`** (`store.py:265`) + `SCHEMA_SQL`. No
   Alembic. IDs use the existing prefixed-ULID helper (`bbv2/ids.py`): `ses_`, `spc_`.

## Phase 1 — Session/token layer (exchange model)

1.1 **Config** (`config.py`): `BBV2_JWT_SECRET` (HS256 signing key; **required** —
    fail closed if unset in prod), `BBV2_ACCESS_TTL_S` (900), `BBV2_REFRESH_TTL_S`
    (2592000), audience constants (`bbv2.user.access`), `BBV2_COOKIE_*`
    (name/domain/secure/samesite). Document all in `.env.example` + `devops.md`.
1.2 **`bbv2/authjwt.py`** — `build_access_token(user_id, session_id)` and
    `decode_access_token(token)` (HS256; require `exp/iat/iss/aud`; `iss=bbv2`;
    `aud=bbv2.user.access`; mirror mass `jwt_utils.py:109` audience enforcement).
    Pure + unit-testable (no network).
1.3 **`user_sessions` table** (`SCHEMA_SQL`), modelled on mass `user_session`:
    ```sql
    CREATE TABLE IF NOT EXISTS user_sessions (
        id TEXT PRIMARY KEY,                  -- ses_<ulid>
        user_id INTEGER NOT NULL,
        refresh_token TEXT NOT NULL UNIQUE,   -- secrets.token_urlsafe(32), opaque
        expires_at TEXT NOT NULL,
        last_active_at TEXT NOT NULL,
        is_revoked INTEGER NOT NULL DEFAULT 0,
        replaced_by TEXT,                     -- rotation chain
        ip TEXT, user_agent TEXT,
        created_at TEXT NOT NULL
    );
    ```
    Store helpers in a new `store_sessions.py` (keep `store.py` under cap):
    `create_session`, `get_session_by_refresh` (active only), `rotate_session`
    (revoke old, link `replaced_by`, mint new), `revoke_session`,
    `revoke_user_sessions(user_id)`, opportunistic prune of expired rows.
1.4 **`POST /api/auth/exchange`** (`auth_api.py`, new router): `Authorization:
    Bearer <Firebase ID token>` → `verify_token` (keep `clock_skew_seconds=10`,
    `auth.py:38`) → upsert user → **block if `status='disabled'`** → create session
    + refresh → set HttpOnly `access`+`refresh` cookies → return `/api/me` payload.
    Auto-provision the user's **personal space** here (Phase 3).
1.5 **`GET /api/auth/session`** (refresh/probe): read refresh cookie → if access
    cookie still valid, return user; else **rotate** the session, re-mint access,
    reset cookies. `POST /api/auth/logout`: revoke session + clear cookies.
1.6 **Rework `current_user`** (`dashboard_api.py:51`): read the **access cookie**,
    `decode_access_token` (audience-checked), load the user, **enforce
    `status='active'`**. On expiry → 401; the frontend calls `/api/auth/session`
    then retries. The Bearer-Firebase path is removed from `/api/*` (it lives only
    at `/exchange`).

## Phase 2 — RBAC: roles + named capabilities

2.1 **`bbv2/rbac.py`** — capability constants + role→caps map, e.g.
    ```python
    CAPS = {  # global role → capabilities
      "owner":  {"*"},                                   # superset incl. user:manage
      "admin":  {"topics:curate","sources:approve","brief:generate",
                 "cadence:set","token:manage","admin:read"},
      "user":   {"topics:create","topics:subscribe","chat:use"},
      "service":{"api:read"},
    }
    ```
    Plus **space-role → caps** for per-space membership
    (`space:owner`/`editor`/`viewer` → `space:*`/`space:write`/`space:read`).
    `resolve_capabilities(user, space_id=None, membership_role=None) -> set[str]`
    unions global + space caps; `has_capability(...)`.
2.2 **`require_capability(cap, space_id=None)`** dependency factory replaces
    `require_admin`. Keep a thin `require_admin = require_capability("admin:read")`
    alias so the 9 gated routes (`dashboard_api.py:254…452`) migrate mechanically;
    then tighten the obvious ones to specific caps (`sources:approve`,
    `brief:generate`, `cadence:set`, `token:manage`).
2.3 **`ADMIN_EMAILS` → `owner`.** `current_user`/exchange sets `role='owner'` on an
    `ADMIN_EMAILS` match (never demotes), matching today's promote-only behavior
    (`dashboard_api.py:64`, plan 0009). `admin` is owner-grantable (Phase 4).
2.4 **`/api/me`** returns `capabilities: [...]` (global) so the frontend gates UI on
    caps, not on `role === 'admin'`.

## Phase 3 — Spaces foundation

3.1 **Schema** (`SCHEMA_SQL`):
    ```sql
    CREATE TABLE IF NOT EXISTS spaces (
        id TEXT PRIMARY KEY,                  -- spc_<ulid>
        owner_user_id INTEGER NOT NULL,
        type TEXT NOT NULL DEFAULT 'personal',-- personal | blog | learning
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS space_membership (
        space_id TEXT NOT NULL,
        user_id  INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',  -- owner | editor | viewer
        created_at TEXT NOT NULL,
        PRIMARY KEY (space_id, user_id)
    );
    ```
    `store_spaces.py`: `create_space`, `add_member`, `get_membership(space,user)`,
    `user_spaces(user)`, `space_members(space)`.
3.2 **Auto personal space** at exchange (Phase 1.4): if the user has none, create a
    `type='personal'` space owned by them + an `owner` membership.
3.3 **Capability scoping wired** — `require_capability(cap, space_id=X)` looks up the
    caller's membership role in space `X` and unions those caps. **No existing route
    is space-scoped yet** (topics/headlines stay global); this proves the primitive
    end-to-end with a minimal `GET /api/spaces` (the caller's spaces) + the personal
    space, leaving the topics→space migration to a later plan. Note that seam in the
    plan + `architecture.md`.

## Phase 4 — User lifecycle, status, audit

4.1 **`users` columns** (via `_migrate`): `status TEXT DEFAULT 'active'`
    (active|disabled), `last_login_at TEXT`. Enforce `disabled` in exchange +
    `current_user` (Phase 1).
4.2 **`auth_events` table** — `(id, user_id, event, ip, user_agent, created_at)`,
    `event ∈ {login, refresh, logout, denied, revoked, disabled}`. Write from the
    auth router; this is the audit/logging the brief calls out. Surfaced via CLI +
    an owner-only `GET /api/admin/auth-events`.
4.3 **Owner user-management surface** (owner cap `user:manage` only):
    - CLI: `bbv2 user list` (with status/role/last-login), `bbv2 user set-role
      <email> <role>`, `bbv2 user disable/enable <email>`, `bbv2 session revoke
      --user <email>`.
    - API: `GET /api/admin/users`, `PATCH /api/admin/users/{id}` (role/status),
      `POST /api/admin/users/{id}/revoke-sessions`. No self-promotion to owner.

## Phase 5 — Frontend auth rework

5.1 **`api.ts`** — after Firebase sign-in, `POST /api/auth/exchange` once with the
    Firebase ID token; thereafter rely on the **cookie** session (`credentials:
    "include"`), drop the per-request `getIdToken()` Bearer. On 401 → call
    `/api/auth/session` (refresh) once, then retry; on refresh failure → sign out.
    `logout()` hits `/api/auth/logout` then Firebase `signOut`.
5.2 **`state/auth.ts`** — store `capabilities` from `/api/me`; expose `can(cap)`.
5.3 **Capability-gated UI** — replace `role === 'admin'` in `AppShell` (admin link)
    and the `RequireAdmin` route guard (`App.tsx`) with `can("admin:read")`. Same
    visible behavior today; ready for finer caps later.
5.4 **CORS/cookies** — `allowed_origins` already env-driven (0016); ensure
    `allow_credentials=True` + the Tailscale origin; cookies `Secure` +
    `SameSite=Strict` in prod, relaxed for local `http://localhost:5180`.

## Phase 6 — Verify + docs

- **Tests** (offline — inject a fake Firebase verifier; sign/verify our JWT with a
  test secret; in-memory store): exchange creates a session + personal space + login
  event; expired access → `/session` rotates (old refresh revoked, `replaced_by`
  set); revoked/disabled user → 401; `require_capability` allows owner/admin, 403s a
  plain user; each migrated gated route keeps its 403; consumer `api.py` path
  unaffected. `tsc && vite build` clean.
- **`/code-review`** per CLAUDE.md (auth/session code is exactly where it earns its
  keep — rotation races, cookie flags, audience checks); address findings.
- **Docs**: `_documentation/architecture.md` (auth/session/RBAC/spaces),
  `_documentation/devops.md` (`BBV2_JWT_SECRET` + cookie/secret-rotation ops),
  `README.md`, `.env.example`; prune `roadmap.md`. Update `CLAUDE.md` "WHERE WE ARE".

## Risks / notes

- **Cookie + CSRF.** `SameSite=Strict` + same-site Tailscale serving is the primary
  defense; revisit a CSRF token only if a cross-site surface appears.
- **JWT secret is a new prod secret** — generate, store like the other secrets
  (never committed), document rotation (rotating invalidates live access tokens;
  refresh tokens survive → users re-mint on next call). Single backend → one key.
- **Clock skew** — keep `clock_skew_seconds=10` on the Firebase verify (`auth.py`)
  for the home-VM drift, matching mass.
- **In-memory rate limiter** (single uvicorn) still applies to `/auth/*`; note it
  resets on restart (accepted at this scale, per 0016).

## Done when

The dashboard exchanges the Firebase login for a briefbot session cookie; the owner
can **list users, change roles, disable an account, and force-revoke its sessions**
from the CLI/admin API; every authed request is checked against **capabilities**
(owner via `ADMIN_EMAILS`, admin grantable, plain users blocked from curation);
logins/refreshes/logouts are **audited**; and every user has a **personal space**
with per-space membership roles ready for the blogs/learning/personalization work —
with the consumer API and existing global features still working unchanged.
