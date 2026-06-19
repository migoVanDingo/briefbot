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

- **Frontend:** React 18 + **Vite + TypeScript**, plain CSS with **design tokens**
  (single source like trader's `theme.ts` + injected CSS vars), **Zustand**,
  **react-router**. **No MUI** — og's MUI is exactly the rounded/pill look we're
  moving away from; our own tokens give full control (low radius, distinct
  light/dark accents, snackbars).
- **Backend:** extend bbv2's FastAPI with dashboard routes under `/api/*`
  (session auth), alongside the consumer API. CORS allowed for the Vite dev
  origin.
- **Snackbars:** a small toasts store + component (reimplement trader's `Toasts`
  in bbv2's style).

This mirrors the trader app's architecture, so patterns (tokens, Zustand,
Toasts, hooks) carry over.

## Auth (personal scale)

Intentionally minimal for **local, personal** use (me + mom + brother):
`POST /api/login {email}` → if the user exists, create a **session token**
(`sessions(token, user_id, created_at)`), return it; the client stores it and
sends `Authorization: Bearer <session>`. No passwords. **Harden before any
public exposure** (passcode/allowlist/proper auth). Separate from 0003 service
tokens.

## Backend dashboard API (`/api/*`, session auth)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/login` | email → session token |
| GET | `/api/me` | user + settings + subscriptions |
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

1. **Dashboard API** — sessions + the `/api/*` routes above + CORS.
2. **Frontend shell** — Vite+TS scaffold, tokens/theme (light/dark), Zustand,
   router, Toasts, login + `/api/me`.
3. **Topics & subscriptions** — list/create/(un)subscribe.
4. **Discovery & approval** — topic sources, candidates, approve/reject, Discover.
5. **Headlines & browsing** — feed + per-topic items.
6. **Settings**.
7. (later) **Engagement** — like / favorites / discuss-with-agent.

Each is independently shippable; trader-style discipline (small modules, tokens,
tests for pure logic, snackbars on actions).

## Open questions

1. **Auth depth:** is the email-only local login acceptable for now (harden
   later), or do you want a shared passcode even locally?
2. **Frontend location:** a `dashboard/` (or `web/`) folder in this repo
   (Vite, not containerized — like trader), with the Python API in docker later?
3. **Prod serving:** Vite dev locally is enough for now; static-serve via
   uvicorn (og's `static_server.py` pattern) only when we deploy.
