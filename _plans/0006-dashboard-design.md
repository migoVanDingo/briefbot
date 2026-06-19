# 0006 — Dashboard — Design

**Status:** Design (awaiting review)
**Date:** 2026-06-19
**Phase:** Design · **Depends on:** 0002–0005 ✅

## Goal

A human-facing web dashboard for bbv2: a dynamic **Headlines** feed, **topic**
management + subscriptions, **source discovery & approval**, item **browsing**,
and **settings** — multi-user (each person sees their own subscriptions). Must be
**responsive**, with **snackbars on every action** and a **distinct look** (not
og briefbot's MUI/rounded-pill style — see `_documentation/ui-style.md`).

## Guardrails

og briefbot untouched; bbv2 reads/writes only its own DB. The dashboard API is a
new surface on bbv2's existing FastAPI app, separate from the service-token
**consumer API** (0003).

## Stack decision

- **Frontend:** React 18 + **Vite + TypeScript** in a **`dashboard/`** folder
  (not containerized — like trader). **Styling: custom CSS design tokens** (single
  source `theme.ts` + injected CSS vars), **Zustand**, **react-router**, **Firebase
  web SDK** for auth.
  - *On MUI:* MUI is fine (you use it elsewhere) — og's pill-shaped look was custom
    styling, not MUI itself. We're going **custom tokens** anyway for full control
    over the low-radius/accent look and to match the trader app's patterns. Easy to
    swap to a themed MUI later if preferred.
- **Backend:** extend bbv2's FastAPI with dashboard routes under `/api/*`
  (**Firebase auth**, below), alongside the consumer API. CORS allowed for the
  Vite dev origin.
- **Snackbars:** a small toasts store + component (reimplement trader's `Toasts`
  in bbv2's style).

This mirrors the trader app's architecture, so patterns (tokens, Zustand,
Toasts, hooks) carry over.

## Auth — Firebase (Google + email/password)

Mirrors the mass-platform pattern (`mass-frontend` + `mass-user-management`),
simplified for bbv2:

- **Frontend:** Firebase web SDK. `signInWithPopup(GoogleAuthProvider)` and
  `signInWithEmailAndPassword`; after login `user.getIdToken()` is sent as
  `Authorization: Bearer <firebase_id_token>` on every `/api/*` request.
- **Backend:** `firebase-admin` verifies the ID token **per request**
  (`auth.verify_id_token(token, clock_skew_seconds=10)` — the clock-skew detail is
  from mass) and **auto-provisions** the user on first sight (upsert into `users`
  by email; `name` from the token, `role='human'`). No separate session
  table/JWT — Firebase manages token lifecycle.
- **Why simpler than mass:** mass issues its own platform JWT to share auth across
  many services; bbv2 is one service, so per-request verification is enough. The
  exchange→session pattern is an easy future upgrade.

Separate from the 0003 service-token consumer API. Harden (allowlist of permitted
emails) before any non-local exposure.

### Config / creds needed (you'll provide)

- **Frontend** (`dashboard/.env`): `VITE_FIREBASE_API_KEY`, `…_AUTH_DOMAIN`,
  `…_PROJECT_ID`, `…_STORAGE_BUCKET`, `…_MESSAGING_SENDER_ID`, `…_APP_ID`.
- **Backend** (bbv2 `.env`): `FIREBASE_CONFIG` = path to the Firebase **service
  account** JSON (for `firebase-admin`). Enable Google + Email/Password providers
  in the Firebase console.

## Backend dashboard API (`/api/*`, Firebase bearer)

Every `/api/*` route is protected by a dependency that verifies the Firebase ID
token and resolves (auto-provisioning) the user.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/me` | verify token, upsert user; return user + settings + subscriptions |
| GET | `/api/topics` | all topics (+ `subscribed` flag) |
| POST | `/api/topics` | create a topic |
| POST/DELETE | `/api/topics/{slug}/subscribe` | (un)subscribe |
| POST | `/api/topics/{slug}/discover` | run Brave discovery (returns stats) |
| GET | `/api/topics/{slug}/sources?status=` | active/candidate sources |
| POST | `/api/sources/{id}/approve` · `/reject` | curate candidates |
| GET | `/api/headlines?limit=` | recent items across my subscriptions |
| GET | `/api/topics/{slug}/items?since=&limit=` | browse a topic |
| GET/PUT | `/api/settings` | email_enabled / digest_limit |

Most map directly to existing store methods (0002–0005); a few new ones (sessions,
topics-with-subscribed-flag).

## Frontend (pages + components)

- **Shell:** header (brand, user, theme toggle), responsive nav, `<Toasts/>`.
- **Login** — pick/enter email.
- **Headlines** — live-ish feed across subscriptions (refresh on load; poll later).
- **Topics** — browse/subscribe/unsubscribe; create topic.
- **Topic detail** — items + sources (active + **candidates** with approve/reject)
  + a **Discover** button (Brave) → snackbar with results.
- **Settings** — email on/off, digest limit.
- **Engagement (like / favorites / discuss-with-agent)** — **deferred** to a later
  phase (0007); the og dashboard's chat/agent + FavoriteButton are the reference.

All actions fire snackbars (subscribed, approved, rejected, discovered N,
settings saved, errors). Light/dark with distinct palettes; responsive layout.

## Reuse from og briefbot (concepts, not code/MUI)

og's `dashboard/` (React + MUI + FastAPI `api.py`/`dao.py`, agent chat in
`backend/agent/`) is a reference for **features and API shape** — the
brief/stories/favorites/chat pages and the DAO pattern. We reimplement in our
stack/tokens; the agent-chat ("discuss with agent") informs the later engagement
phase.

## Build order (phased → own plans)

1. **Dashboard API** — `firebase-admin` token verification + user auto-provision,
   the `/api/*` routes above, and CORS for the Vite dev origin.
2. **Frontend shell** — `dashboard/` Vite+TS scaffold, tokens/theme (light/dark),
   Zustand, router, Toasts, **Firebase login** (Google + email/pw) + `/api/me`.
3. **Topics & subscriptions** — list/create/(un)subscribe.
4. **Discovery & approval** — topic sources, candidates, approve/reject, Discover.
5. **Headlines & browsing** — feed + per-topic items.
6. **Settings**.
7. (later) **Engagement** — like / favorites / discuss-with-agent.

Each is independently shippable; trader-style discipline (small modules, tokens,
tests for pure logic, snackbars on actions).

## Decisions (resolved)

1. **Auth → Firebase** (Google + email/password), verified per request by
   `firebase-admin`, user auto-provisioned. Creds provided by you.
2. **Frontend → `dashboard/`** folder in this repo (Vite + TS, not containerized).
3. **Styling → custom CSS tokens** (no MUI; MUI was fine but custom gives control
   + trader consistency).
4. **Prod serving (deferred):** Vite dev locally is enough now; static-serve via
   uvicorn (og's `static_server.py` pattern) only when we deploy.
