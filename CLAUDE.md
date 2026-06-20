# CLAUDE.md — bbv2

Guidance for working in this repo. Design + phases live in `_plans/`; reference
docs in `_documentation/`.

## What this is

**bbv2** — a small, multi-user, topic-driven news platform. Topics → agent-
discovered sources → cron ingestion → per-topic feeds + a consumer API (read by
the `trader` project). Personal scale (me + family). Currently at **0002 —
ingestion core** (backend, single profile; no API/discovery/multi-user/UI yet).

## HARD RULES

- **Never modify the original briefbot** at `~/Developer/agent/projects/ai-assistant`.
  It's a live nightly system. We only **copy code out of it** (one-directional).
- **bbv2 owns its own database** (`BBV2_DB_PATH`, default `data/bbv2.db`). Never
  open, read, or connect to the original briefbot's DB.

## Stack

Python 3 · SQLite (WAL) · feedparser · beautifulsoup4 · requests ·
python-dateutil · python-dotenv · **FastAPI + uvicorn** (consumer API).
(Anthropic / Brave / Vite arrive in later phases.)

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

# Source discovery (0004) — Brave web search → candidate feeds → human approval
python -m bbv2 discover --topic crypto [--per-query 8] [--max 20]
python -m bbv2 source candidates --topic crypto
python -m bbv2 source approve <id>   |   python -m bbv2 source reject <id>

# Consumer API (0003)
python -m bbv2 token create --label trader --topics crypto,markets,geopolitics
python -m bbv2 token list
python -m bbv2 serve --host 127.0.0.1 --port 8080
#   consumer API (service token): GET /health /topics /items
#   dashboard API (Firebase ID token, 0007): /api/me /api/topics /api/headlines …
#   needs FIREBASE_CONFIG = path to the Admin *service-account* JSON

pytest        # offline tests (no network)
```

`scripts/collect.sh` is the hourly runner (cron/launchd on the server).

### Dashboard (frontend)

`dashboard/` is a separate Vite + React + TS app (custom CSS tokens, Firebase
auth) — **not** containerized.

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5173  (talks to `bbv2 serve` on :8080)
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
  api.py         FastAPI consumer API (service-token read: /health /topics /items)
  auth.py        Firebase ID-token verification (dashboard)
  dashboard_api.py  /api/* routes (Firebase auth) — me/topics/sources/headlines/settings
  notify.py      Notifier protocol + LogNotifier + MailgunNotifier
  digest.py      per-user recent-items digest (non-LLM)
  cli.py         `python -m bbv2 …`
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
- Keep files focused and reasonably small.

## Status / plans

Shipped: `0002` ingestion core · `0003` consumer API · `0004` Brave discovery ·
`0005` multi-user + settings + email · `0006/0007` dashboard (design + Firebase
API) · **`0008` v1-dashboard port** (Headlines/Chat/Stories/Favorites + `/admin/
topics`, prefixed ULIDs, brief engine, chat agent) · **`0009` user topic flow +
owner-only roles + guardrails**.

## WHERE WE ARE — pick up here (2026-06-19)

**Plan `0008` (phases 1–6) is done** — the original briefbot's normal-flow
dashboard is ported into bbv2. Run `make dev` (backend :8080 + frontend :5173):

- **Routes:** `/headlines` (tabbed: *Today* = generated brief — title + summary +
  Trending + Sources; per-topic tabs = stories newest-first), `/chat` (Haiku
  tool-use agent, SSE), `/stories` (search/source/sort + vote + ☆ save),
  `/favorites` (folders + links), `/topics` (user flow — see below).
  Source curation lives at **`/admin/topics`** (Discover/Approve/Collect/Generate
  brief) — **admin-only** (0009).
- **`/topics` user flow (0009):** any user creates a topic → it passes **tiered
  moderation** (slug/name validation → keyword denylist → Haiku classifier;
  infosec allowed, harmful denied) → **provision** streams a chip pipeline
  (Discover → Approve → Collect → Ready, SSE, witty phrases) → **Subscribe**.
  Create + provision are **rate-limited** (per user). Source discovery drops
  denylisted domains.
- **Roles (0009):** **owner-only admin** via `ADMIN_EMAILS` (the ONLY way to grant
  admin — no API/UI/CLI). `require_admin` 403-gates curation routes; the frontend
  hides `/admin` + guards the route for non-admins.
- **IDs:** prefixed ULIDs (`ITM…`/`SRC…`/`TOP…`/`CLU…`/`FAV…`/`FLD…`/`CON…`/
  `MSG…`/`BRF…`) via `bbv2/ids.py`. Dedupe still on `dedupe_key`.
- **Brief:** `bbv2/brief.py` + `cluster.py` + `llm.py` (Haiku). Generate via the
  admin button or CLI `bbv2 brief [--topic]`. Stored in `briefs` table.
- **Modules:** `ids`, `cluster`, `llm`, `brief`, `agent` (0008); `moderation`,
  `ratelimit`, `denylist`, `provision` (0009); store mixins
  (`store_dashboard`/`store_favorites`/`store_chat`). **66 pytest pass; build clean.**
- **Live LLM (Haiku) is user-invoked only** (brief, chat, topic moderation).
  Needs `ANTHROPIC_API_KEY`. Moderation **fails closed** (deny on LLM error).

**DB was wiped** (fresh `data/bbv2.db`) when ULIDs landed. To re-seed: set
`ADMIN_EMAILS=<you>` in `.env`, log in (you provision as admin) → create a topic
on **`/topics`** (auto discover→approve→collect) *or* curate via `/admin/topics` →
Generate brief → see `/headlines`.

**Creds:** backend Firebase service-account wired (`FIREBASE_CONFIG`, project
`briefbot-v2`). Frontend `dashboard/.env` still **needs `VITE_FIREBASE_API_KEY` +
`VITE_FIREBASE_APP_ID`** for live login.

### NEXT (own plans — the rest of the re-scope)

- **Settings:** per-user accent **color picker** (light accent is hardcoded blue
  now); plus the existing digest settings.
- **Logo** to replace the `◆` brand-mark; **article images** on cards (extract
  `media:content`/`enclosure` + `og:image`).
- **Persistent clusters** (unlocks the Stories cluster/tag filters deferred in
  0008 Phase 3) + per-article deep summaries; brief **cron** cadence.
- **Two pre-pivot bugs still open** (predate 0008, low priority now that flow is
  changing): admin "Approve all" uses `Promise.all` of POSTs → "failed to fetch"
  (serialize or add a bulk endpoint); collect ingests stale `published_at` items
  → add a recency filter in `bbv2/collect.py`.
- Trader data platform (`../trader/_plans/0017`) stays parked until bbv2 steady.
