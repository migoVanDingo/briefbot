# 0007 — Dashboard API (Firebase auth)

**Status:** ✅ Implemented (2026-06-19) — live Firebase pending the service-account key
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0006 design](./0006-dashboard-design.md)

> **Done.** 28 tests pass (dashboard routes via TestClient + a fake verifier:
> 401 paths, `/api/me` auto-provision, topics+subscribe flag, settings roundtrip,
> headlines scoped to subscriptions). `serve` mounts `/api/*` + CORS.
>
> **Cred note:** the file currently at `FIREBASE_CONFIG` is the Firebase **web
> config** (apiKey/authDomain/…), not an Admin **service-account** key —
> firebase-admin correctly rejected it. Point `FIREBASE_CONFIG` at the
> service-account JSON (Console → Project Settings → Service accounts → Generate
> new private key) to enable live verification. The web config is what the
> frontend needs (`dashboard/.env` `VITE_FIREBASE_*`).

Implements **Phase 1** of the dashboard: the backend `/api/*` routes with
**Firebase** auth, so the frontend (next phase) has something to talk to.

## Guardrails

og briefbot untouched; bbv2 own DB. Separate from the 0003 service-token consumer
API (both served by the same FastAPI app on different paths).

## Auth

`bbv2/auth.py`: `firebase-admin` verifies the ID token per request
(`verify_id_token(token, clock_skew_seconds=10)`); the route dependency
**auto-provisions** the user (upsert into `users` by email; name from the token).
The verifier is **injectable** so routes are testable offline with a fake.
Backend cred: `FIREBASE_CONFIG` (service-account JSON path).

## Routes (`/api/*`, Firebase bearer)

`GET /api/me`, `GET/POST /api/topics`, `POST/DELETE /api/topics/{slug}/subscribe`,
`POST /api/topics/{slug}/discover`, `GET /api/topics/{slug}/sources?status=`,
`POST /api/sources/{id}/approve|reject`, `GET /api/headlines`,
`GET /api/topics/{slug}/items`, `GET/PUT /api/settings`. Most map to existing
store methods (0002–0005).

## Serving

`bbv2 serve` builds the consumer app, attaches the dashboard routes, and adds
**CORS** for the Vite dev origin (`localhost:5173`).

## Tasks

- [x] **1** `firebase-admin` in requirements; `config.firebase_config_path()`.
- [x] **2** `bbv2/auth.py` — init + `verify_token` (real) used by serve.
- [x] **3** `bbv2/dashboard_api.py` — `add_dashboard_routes(app, store, verifier)`
      with an injectable `current_user` dependency.
- [x] **4** `serve`: mount dashboard routes + CORS.
- [x] **5** Tests (TestClient + fake verifier): 401 paths, `/api/me` upsert,
      topics+subscribe flag, settings roundtrip, headlines.
- [x] **6** Docs: CLAUDE.md.

## Done when

`serve` exposes `/api/*`; a valid Firebase token resolves/creates a user and the
routes work; invalid/missing token → 401; tests pass; og untouched.

## Notes

Frontend (`dashboard/`, Vite+TS, Firebase web SDK, custom tokens) is the **next**
phase and needs `VITE_FIREBASE_*` web config.
