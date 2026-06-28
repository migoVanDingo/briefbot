# CLAUDE.md — bbv2

Guidance for working in this repo. Design + phases live in `_plans/`; reference
docs in `_documentation/`.

## What this is

**bbv2** ("briefbot") — a small, multi-user, topic-driven **news platform**.
You name a topic → an agent discovers RSS/site sources → cron ingests + an LLM
filters them → per-topic **Headlines** (AI-written daily brief + the stories
behind it), a **chat** agent you can ask to search/summarize/create topics, a
**Stories** browser, and **Favorites**. Firebase auth, owner-only admin, per-user
LLM token budgets. Personal scale (me + mom + brother). Also exposes a read-only
**consumer API** for the sibling `trader` project.

**It is deployed and live in production** — a headless Ubuntu VM on a home Proxmox
box, served over Tailscale HTTPS at `https://briefbot.tailb058fe.ts.net`, with
**push-to-`main` CI/CD**. Full ops detail in `_documentation/devops.md`.

## HARD RULES

- **Never modify the original briefbot** at `~/Developer/agent/projects/ai-assistant`.
  It's a live nightly system. We only **copy code out of it** (one-directional).
- **bbv2 owns its own database** (`BBV2_DB_PATH`, default `data/bbv2.db`). Never
  open, read, or connect to the original briefbot's DB.

## Stack

**Backend:** Python 3 · SQLite (WAL) · FastAPI + uvicorn · feedparser ·
beautifulsoup4 · requests · firebase-admin (auth). LLM over plain HTTP (no SDK):
**Claude Haiku** for prose/moderation, **xAI Grok** for relevance (Haiku
fallback). Brave Search for source discovery; Mailgun for the nightly email.
**Frontend:** `dashboard/` — Vite + React + TS, custom CSS tokens, Firebase web SDK.
**Prod:** Ubuntu VM on Proxmox · systemd · nginx · Tailscale · self-hosted GitHub
Actions runner (see `_documentation/devops.md`).

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python -m bbv2 init
python -m bbv2 topic add crypto --name "Crypto" --description "Crypto + markets"
python -m bbv2 source add --topic crypto --type rss --url <feed-url> --name "Source"
python -m bbv2 source add --topic crypto --type site --url <site-url> --name "Site"
python -m bbv2 collect [--topic crypto]
python -m bbv2 items --topic crypto --since 24h --limit 20

# Multi-user + email (0005)
python -m bbv2 user add --name "Mom" --email mom@example.com
python -m bbv2 subscribe --user mom@example.com --topic crypto
python -m bbv2 settings show --user mom@example.com
python -m bbv2 settings set --user mom@example.com --email-enabled true --digest-limit 15
python -m bbv2 digest --dry-run     # LogNotifier; real Mailgun when MAILGUN_* set

# Scheduling (0014) — two decoupled cron jobs:
python -m bbv2 tick                 # hourly: due-based discovery + collection + quickscan
python -m bbv2 nightly [--dry-run]  # 11pm: build subscribed-topic briefs + email "brief ready"
#   cadence is admin-set per topic (discover/collect) + per source (collect override)

# Source discovery (0004) — Brave web search → candidate feeds → human approval
python -m bbv2 discover --topic crypto [--per-query 8] [--max 20]
python -m bbv2 source candidates --topic crypto
python -m bbv2 source approve <id>   |   python -m bbv2 source reject <id>

# Consumer API (0003)
python -m bbv2 token create --label trader --topics crypto,markets,geopolitics
python -m bbv2 token list
python -m bbv2 token revoke <label|token>   # kill a leaked token (0016)
python -m bbv2 serve --host 127.0.0.1 --port 8080   # --host defaults to BBV2_SERVE_HOST
#   consumer API (service token): GET /health · /consumer/topics · /consumer/items
#   dashboard API (Firebase ID token, 0007): /api/me /api/topics /api/headlines …
#   needs FIREBASE_CONFIG = path to the Admin *service-account* JSON

pytest        # offline tests (no network)
```

Cron/launchd on the server runs **`bbv2 tick` hourly** (pulls) and **`bbv2 nightly`
at 11pm** (briefs + email). LLM: Haiku for prose, **xAI Grok** for relevance
(`GROK_API_KEY`, falls back to Haiku). Per-user budget `TOKEN_LIMIT` (default
100k/day); background/shared LLM spend goes to a system bucket, not a user.

### Dashboard (frontend)

`dashboard/` is a separate Vite + React + TS app (custom CSS tokens, Firebase
auth) — **not** containerized.

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5180  (talks to `bbv2 serve` on :8080)
```

Needs `dashboard/.env` (gitignored) with the Firebase **web** config
(`VITE_FIREBASE_*`) + `VITE_API_BASE`. The backend (`bbv2 serve`) must be running
for login/data.

## Project layout

```
bbv2/
  config.py      env/paths (BBV2_*)
  util.py        copied from og briefbot (verbatim)
  normalize.py   copied from og briefbot
  discover.py    site → feed URLs (adapted from og: stricter feed detection)
  fetch.py       RSS fetch w/ conditional GET (trimmed from og; HN/arXiv deferred)
  brave.py       Brave Web Search client (source discovery)
  discovery.py   topic → search → resolve feeds → candidate sources
  score.py       slim recency × source-weight (bbv2-specific)
  store.py       bbv2 SQLite schema + queries (own DB): topics/sources/items,
                 tokens/candidates, users/subscriptions/settings
  collect.py     pipeline wiring
  api.py         FastAPI consumer API (service-token read: /health · /consumer/*)
  auth.py        Firebase ID-token verification (dashboard)
  dashboard_api.py  /api/* routes (Firebase auth) — me/topics/sources/settings
  dashboard_briefs.py  headlines/stories/briefs routes (split from dashboard_api, 0025)
  dashboard_serial.py  shared response serializers (story_dict/serialize_brief)
  dashboard_profile.py  /api/profile + /api/avatar routes (0028)
  dashboard_metrics.py  /admin/metrics/* (cost + per-user drill-down, 0021/0027)
  logging_setup.py  configure_logging() — central log config (0026)
  metrics_labels.py  friendly purpose labels for the cost breakdown (0027)
  identicon.py   deterministic GitHub-style avatar SVG (0028)
  topic_image.py / avatar_image.py  Grok Imagine bg image gen (topics / avatars)
  notify.py      Notifier protocol + LogNotifier + MailgunNotifier
  digest.py      per-user recent-items digest (non-LLM)
  cli.py         `python -m bbv2 …`  (-v/--verbose for DEBUG logs)
scripts/collect.sh
tests/           pytest (network-free; uses tests/fixtures/sample_feed.xml)
```

## Conventions & modularity (mirror the trader project)

- Small, single-responsibility modules; pure logic (normalize/score) testable
  without network or DB.
- Layers: `fetch`/`discover` (network) → `store` (persistence) → `collect`
  (pipeline) → `cli`. Keep them separate.
- **Copied modules stay faithful** to the original so future copies stay easy;
  bbv2-specific behavior goes in new modules (score/store/collect/cli/config).
- Tests must run offline (use the fixture feed; never hit the network in tests).
- Keep files focused and reasonably small (≤600 lines; split into modules/mixins).
- **Keep docs current as part of every feature task** (not a later TODO): update
  `_documentation/architecture.md` and `README.md` to match new behavior, and
  **prune** `_documentation/roadmap.md` (move shipped items out, keep what's left).
- **Run `/code-review` after implementing a feature or any large change** (before
  considering it done) — it catches correctness/concurrency bugs that tests miss.
  Address its findings, then re-verify.

## Status / plans

Shipped: `0002` ingestion core · `0003` consumer API · `0004` Brave discovery ·
`0005` multi-user + settings + email · `0006/0007` dashboard (design + Firebase
API) · **`0008` v1-dashboard port** (Headlines/Chat/Stories/Favorites + `/admin/
topics`, prefixed ULIDs, brief engine, chat agent) · **`0009` user topic flow +
owner-only roles + guardrails** · `0010`–`0015` relevance/chat/budget/cadence
polish · **`0016` tech-debt + hardening** (SSRF guard `safefetch`, env CORS/bind,
token revoke, collect recency filter, moderation metering, cron logging, CSS
split, SSE abort, dead-code removal) · `0017` headlines date rail · `0018`–`0024`
(UI-state-in-DB, auth/RBAC/spaces, scheduling, metrics, `/consumer`, durable
provisioning, topic images) · **`0025` review + fixes** · **`0026` logging** ·
**`0027` metrics expansion** · **`0028` profiles + avatars** (see `_plans/`).

## Deployment (production)

**Live at `https://briefbot.tailb058fe.ts.net`** (Tailscale-only). Runs on a home
Proxmox VM: systemd `bbv2` (uvicorn :8080) ← nginx (:8081, serves the built
dashboard + proxies `/api`) ← `tailscale serve` (HTTPS) ; cron runs `bbv2 tick`
(hourly) + `bbv2 nightly` (11pm). **CI/CD: push to `main` → a self-hosted GitHub
Actions runner on the VM rebuilds + restarts (~30s).** Full runbook (topology,
config/secrets, ops, troubleshooting, how it was provisioned):
**`_documentation/devops.md`**. Local dev is still `make dev` (backend :8080 +
dashboard :5180).

## WHERE WE ARE — current state

**Shipped & deployed** through `0024`; **`0025`–`0028` built locally (not yet
pushed)**: `0018` DB-persisted UI state · `0019` auth sessions + RBAC + spaces ·
`0020` per-topic scheduling + caps · `0021` admin metrics · `0022` consumer API
under `/consumer` · `0023` durable provisioning pipelines · `0024` topic header
images · **`0025` codebase review + fixes** (security/concurrency/modularity/
mobile) · **`0026` structured logging** · **`0027` metrics expansion** · **`0028`
user profiles + avatars**. Working end-to-end:

- **Routes:** `/headlines` (per-topic tabs; a left **date rail** of the last 10
  days *with briefs* → that day's AI brief + that day's stories), `/chat` (Haiku
  tool-use agent, SSE — search/summarize/**create or subscribe to topics**),
  `/stories` (search/source/date/sort + vote + ☆ save), `/favorites` (folders),
  `/topics` (user create→moderate→provision→subscribe), `/profile` (avatar +
  personal metrics + blog stub), `/admin/topics` (source curation), `/admin/
  metrics` (cost + per-user drill-down), `/settings`.
- **Per-page Joyride tutorials** (`PageTour` + `lib/tours`) with a ⓘ relaunch button;
  responsive **hamburger** nav below the tablet breakpoint.
- **Topic create flow:** tiered moderation (validation → keyword denylist → Haiku
  classifier) → SSE provision pipeline (discover→approve→collect→review→[brief]) →
  auto-subscribe. Rate-limited per user.
- **Auth (0019):** Firebase token **exchanged once** at `/api/auth/exchange` for a
  bbv2 **session** — own access JWT + refresh token (rotation/revoke) in HttpOnly
  cookies; `/api/auth/session` refresh, `/api/auth/logout`. **RBAC** is roles →
  named capabilities (`bbv2/rbac.py`); owner bootstrapped via `ADMIN_EMAILS`, then
  owner-grantable `admin`/`user`/`service` (CLI `user set-role/disable`, `session
  revoke`; admin API). User `status` + `auth_events` audit. **Spaces foundation**:
  a personal `space` per user (`/api/spaces`), per-space membership roles ready —
  existing features still global.
- **DB-persisted UI state (0018):** theme + tour-seen flags live in
  `user_settings`/`user_flags` (via `/api/preferences` + `/api/flags`), so they
  follow the account; localStorage is only an anti-FOUC theme mirror now.
- **IDs:** prefixed ULIDs via `bbv2/ids.py`; dedupe on `dedupe_key`.
- **Cost control:** per-user daily **token budget** (Haiku/Grok metered); LLM is
  user-invoked + background (tick/nightly to a system bucket). Moderation fails closed.
- **Logging (0026):** `bbv2/logging_setup.py::configure_logging()` (called by serve +
  CLI); env-driven `BBV2_LOG_LEVEL`/`BBV2_LOG_FORMAT`, `-v` for DEBUG; instruments
  LLM/HTTP/auth/agent/background; global 500 handler logs tracebacks. To stderr +
  a rotating file (journald/cron capture it).
- **Metrics (0021 + 0027):** est. LLM cost by model/**purpose** (friendly labels)/
  topic/day + **per-image** cost; click a user → drill-down (usage, access, subs, 👍/👎).
- **Profiles (0028):** `/profile` — identicon avatar (or Grok-generated from a prompt,
  `GET /api/avatar/{id}` serves either) + personal tokens/cost (day/week/month/year/all)
  + subscriptions + **blog stub**. `users.avatar_*` columns; `bbv2/avatar_image.py`.
- **Hardening (0016 + 0025):** SSRF guard (`safefetch`), env CORS/bind, token revoke;
  `0025` added the `email_verified` exchange gate, thread-safe rate limiter, chat
  tool-call guard, brief/image dedup, and the `dashboard_api` split. **193 pytest
  pass; dashboard build clean.**

## Backlog / next (each its own plan — see `_documentation/roadmap.md`)

- Settings accent **color picker** (`accent` column + `/api/preferences` exist —
  frontend-only now); per-**article** images on cards still TODO.
- **User spaces** — the **profile** slice shipped (`0028`); still: scope topics/
  headlines per space + spaces UI + invites + the real **blog engine** behind the
  profile stub (`0019` `spaces`/`space_membership` + caps are the foundation).
- **Deferred `0025` refactors** (low-value, do when next touched) — see
  `roadmap.md`: agent tool registry, `provision_runner.start_run`, `api.ts` types
  split, `cli with_store`, and a handful of frontend lows.
- **Persistent clusters** → Stories cluster/tag filters + better brief selection.
- **Collect time-of-day** — `0020` gave discovery daily/weekly scheduling; collection
  is still interval-only (covers the freshness use case). Extend if needed.
- **Trader↔bbv2 integration:** the consumer API is now under `/consumer` (`0022`); add
  the nginx `location /consumer/` block on the VM (see `devops.md`) + hand `trader` a
  scoped token to consume `crypto` (kept fresh by `0020`).
