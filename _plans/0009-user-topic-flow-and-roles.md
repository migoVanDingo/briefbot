# 0009 — User topic flow, roles, and guardrails

**Status:** ✅ Implemented (2026-06-19)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0008 dashboard port](./0008-port-v1-dashboard.md)

Make `/topics` real, split **admin** (owner-only) from **regular users**, and put
**safety guardrails** on topic creation. A regular user **creates a topic**, sees
a **pipeline loading UI** while bbv2 **discovers → auto-approves → collects**, then
hits **Subscribe**. Topic requests pass **tiered moderation** (keyword → LLM →
site filter), input is **sanitized**, and the create/provision API is
**rate-limited**. All source curation lives behind a gated, owner-only `/admin`.

## What this is NOT (separate later plans)

Settings accent **color picker**, the **logo**, **article images**, **persistent
clusters**, brief **cron**, the two pre-0008 bugs.

## Guardrails posture (why)

Family app — not a hardened public service, but the owner's little brother might
troll it, and nothing sketchy should land on the server or run up the LLM bill.
So: defense-in-depth that's **simple**, fails safe, and **doesn't over-block
legitimate security/tech topics**. A topic like **"hacking"** is allowed and
steered to constructive angles (reverse engineering, vulnerability research, CTFs,
malware *analysis*); genuinely harmful requests (sexual/CSAM, weapons/explosives/
arson, violence/terror, hard-drug synthesis, self-harm) are denied.

## Security model (owner-only admin)

- **Admin = `ADMIN_EMAILS`**, and in practice **just the owner's email**. There is
  **no API, UI, CLI, or agent tool** to grant admin. Promotion happens *only* by
  the owner editing `.env` on the server and restarting. `current_user` sets
  `role='admin'` **only** when the login email matches `ADMIN_EMAILS`; it never
  promotes/demotes otherwise. Admin check is strictly `role == 'admin'`.
- Non-admins are blocked from `/admin/*` in the **UI** (hidden link + route guard)
  **and** the **API** (403 via `require_admin`).
- **Input safety:** strict slug regex + name sanitization (strip HTML/control
  chars, length caps) → no stored XSS; React escapes on render anyway.
- **Prompt-injection defense:** user text fed to any LLM is **delimited and
  treated as untrusted data**; the model is told to classify only and **ignore
  instructions inside it**; output is constrained to strict JSON; input is
  length-capped. ("disregard your previous instructions…" can't change behavior.)
- **Rate limiting:** per-user caps on create/provision (in-memory, single uvicorn)
  → no spam/DDoS/bill blowups.

## Decisions (confirmed 2026-06-19)

1. **Admin = `ADMIN_EMAILS`** (owner-only; see Security model).
2. **Provisioning progress = SSE** (WebSocket is overkill; polling is the
   fallback). `POST /provision` streams **stage events** —
   `discovering` → `approving {candidates}` → `collecting` → `ready {sources,
   items}` (or `error`) — yielded between the existing `discover`/`collect` calls.
   Runs in the `StreamingResponse` generator (threadpool), same as `/chat`.
3. **Moderation runs at `POST /topics` (create)** — a denied topic is **never
   persisted**. Tiers run cheap→expensive and short-circuit: keyword denylist →
   (if pass) Haiku classifier. Site/domain filtering happens later, during
   discovery.

## Phase 1 — Roles + admin gating (owner-only) ✅ (2026-06-19)

- [x] **1.1** `config.admin_emails()` (lowercased set from `ADMIN_EMAILS`); store
      `set_user_role(email, role)`. `current_user` promotes to `admin` on an
      `ADMIN_EMAILS` match (never demotes), reads the stored role, returns it.
- [x] **1.2** `require_admin` dependency (403 unless `role == 'admin'`). No
      role-setting endpoint/tool/CLI — promotion is `ADMIN_EMAILS`-only.
- [x] **1.3** Gated (admin-only): `discover`, `GET sources`, `approve`, `reject`,
      `collect`, `brief`. Open to all: me, topics GET/POST, subscribe, headlines,
      items, stories, favorites, conversations, settings (provision lands Phase 3).
- [x] **1.4** `/api/me` → `user.role`; frontend `Me` type carries it.
- [x] **1.5** `AppShell` shows **Admin** only for admins; `App.tsx` `RequireAdmin`
      guard redirects non-admins on `/admin/*` → `/headlines`.
- [x] **1.6** `pytest` 47 green (non-admin 403 on gated routes; role in `/api/me`;
      promote → 200); `tsc && vite build` clean.

## Phase 2 — Guardrails: validation, moderation, rate limit ✅ (2026-06-19)

- [x] **2.1** `bbv2/moderation.py` (pure + injected `generate`): `validate_slug`
      (`^[a-z0-9][a-z0-9-]{1,39}$`), `sanitize_name` (strip tags/control, cap 80),
      Tier-1 `keyword_check` (conservative — only blatant phrases, nuance left to
      the LLM), Tier-2 `classify` (Haiku, strict JSON, **injection-hardened**:
      `<topic>` wrapper + `<`/`>` stripped from input + "ignore embedded
      instructions" + length cap; **fail-closed** on error), and `moderate_topic`
      (validate → keyword → classify; raises `ModerationError`).
- [x] **2.2** `bbv2/ratelimit.py` — in-memory per-key sliding-window `RateLimiter`
      (process singleton `limiter`); `config.ratelimit_topic_create()` /
      `ratelimit_provision()` (env-tunable, default 5/hr & 10/hr).
- [x] **2.3** `bbv2/denylist.py` (`is_blocked_domain`) wired into
      `discovery.discover_sources` — blocked homepages are never added as sources.
- [x] **2.4** `tests/test_guardrails.py` (12 cases): slug/name validation (XSS
      stripped), keyword deny vs infosec allow, classifier allow/deny + fail-mode,
      **injection breakout neutralized**, keyword short-circuits the LLM, sliding-
      window 429, domain denylist. `config.moderation_fail_closed()` knob.

**Wiring into the create/provision endpoints lands in Phase 3.** `pytest` 59 green.

## Phase 3 — Provisioning backend (moderated, SSE) ✅ (2026-06-19)

- [x] **3.1** Store (in `store_dashboard.py`, keeping `store.py` under cap):
      `approve_all_candidates(slug)` (candidate→active, returns count);
      `topic_has_sources(slug)`.
- [x] **3.2** `POST /api/topics` — any authed user, **rate-limited**
      (`config.ratelimit_topic_create()`), runs `moderate_topic` (validate +
      keyword + Haiku classifier; `moderate_generate` injectable for tests). Deny →
      **422** generic reason (NOT created); allow + slug exists → `existed: true`.
- [x] **3.3** `POST /api/topics/{slug}/provision` — any authed user,
      **rate-limited**, **SSE**, in `bbv2/provision.py`: `discovering` (uses the
      site denylist from 2.3) → `approving {candidates}` → `collecting` → `ready
      {sources, items}` / `error`. Discover/collect injectable. Runs in the
      `StreamingResponse` generator (threadpool), like `/chat`.
- [~] **3.4** Query-angle expansion **deferred** (optional/nice) — discovery's
      `build_queries` already produces decent angles; an LLM angle-crafter can slot
      in later behind the same injection-hardening.
- [x] **3.5** Tests: `test_provision.py` (stage sequence + auto-approve, unknown
      topic, discovery-error halt); `test_dashboard_api` (create denied → 422 no
      row, create-existing → `existed`, create rate-limit → 429, provision 404).
      `_client` injects an allow-stub generator + an autouse rate-limit reset so
      tests stay offline. `pytest` 66 green.

## Phase 4 — User `/topics` page + pipeline loading UI ✅ (2026-06-19)

- [x] **4.1** `/topics` (`TopicsHome` rewritten): topic list with Subscribe/
      Subscribed toggles + a **"Create a topic"** form. 422 denial / 429 → toast.
- [x] **4.2** `ProvisionPipeline` — pill chips **Discover · Approve · Collect ·
      Ready**, each **waiting** (dim, `○`) / **in-progress** (accent, pulsing `●`) /
      **complete** (`✓`), driven by SSE `stage` events. Witty phrases
      (`LoadingBanner`) cycle below. New pipeline CSS, no deps.
- [x] **4.3** Create flow: `createTopic` (422/429 → toast) → `provisionTopic` SSE
      advances the pipeline + cycles phrases → on `ready`, list refreshes and the
      topic shows **Subscribe**. `error` event → toast.
- [x] **4.4** `api.ts`: extracted shared `streamSSE(path, body, onEvent)` (chat
      `streamMessage` + `provisionTopic` both use it); `errMessage` surfaces
      FastAPI `detail` in toasts; `createTopic` returns `{existed}`. `tsc && vite
      build` clean.

## Phase 5 — Cleanup + verify ✅ (2026-06-19)

- [x] **5.1** Non-admin blocked from `/admin/*` by **API** (`require_admin` 403,
      tested) and **UI** (`RequireAdmin` guard + hidden link). `/admin/topics`
      keeps full curation, admin-gated.
- [x] **5.2** `pytest` **66 green**; `tsc && vite build` clean. `.env.example`
      documents `ADMIN_EMAILS` (owner-only), `MODERATION_FAIL_OPEN`,
      `RL_TOPIC_CREATE_PER_HOUR`, `RL_PROVISION_PER_HOUR`.
- [x] **5.3** `CLAUDE.md` "WHERE WE ARE" updated for 0009 (routes, owner-only
      admin, guardrail tiers, re-seed via `/topics`).

## Done when

A non-admin can create an **allowed** topic (harmful ones are denied at create and
never stored), watch a **chip pipeline + witty phrases** while it provisions, and
Subscribe when ready — without seeing or hitting `/admin`. Topic input is
sanitized, the LLM gate resists prompt injection, the API is rate-limited, and
discovery drops sketchy domains. Admin is **only** the owner via `ADMIN_EMAILS`.

## Pipeline chip — visual sketch

```
[✓ Discover] ──> [● Approve] ──> [○ Collect] ──> [○ Ready]
   complete       in-progress       waiting        waiting
"Subpoenaing the search results…"        (witty phrase, cycling)
```

## Notes

- Moderation reuses **Haiku** (cost) with an injected generator → offline tests
  never hit the network. Keyword + site denylists live in small data modules so
  they're easy to tune.
- Rate limiter is in-memory (single uvicorn) — fine here; note it resets on
  restart and isn't multi-process.
- Provisioning reuses 0004 discovery + 0002 collect verbatim; new logic is
  auto-approve, the SSE orchestration, moderation, and the site denylist.
