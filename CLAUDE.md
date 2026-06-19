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
API) · dashboard **frontend** (`dashboard/`, Vite+React+TS, custom tokens,
Firebase login, Headlines/Topics/TopicDetail/Settings, witty loading phrases).

## WHERE WE ARE — pick up here (2026-06-19)

The dashboard works end-to-end: log in (Firebase) → Topics → open a topic →
**Discover sources** (Brave) → **Approve** → **Collect now** → items show in
Headlines. `make dev` runs backend(:8080)+frontend(:5173) together.

**Live creds status:** backend Firebase service-account is wired (`FIREBASE_CONFIG`,
project `briefbot-v2`, init verified). Frontend `dashboard/.env` still **needs
`VITE_FIREBASE_API_KEY` + `VITE_FIREBASE_APP_ID`** (web config was deleted; user
to provide or restore `config/firebase.json`). Login works once those are set.

### OPEN BUGS to fix next

1. **"Approve all" → "failed to fetch".** Single approve works; the bulk path
   (`Promise.all` of approve POSTs in `dashboard/src/pages/TopicDetail.tsx`)
   fails. Likely **concurrent writes on the one shared SQLite connection**
   (`bbv2 serve` uses `Store(check_same_thread=False)`; the threadpool runs the
   POSTs in parallel → lock/"recursive cursor"/dropped connection → browser sees
   "failed to fetch"). **Fix:** add a backend **bulk approve** endpoint
   (`POST /api/topics/{slug}/sources/approve-all` or accept ids) that does the
   updates on the server in one request; or serialize client-side (await in a
   loop, not Promise.all); ideally also guard the store with a write lock.
2. **Old items in Headlines (e.g. "2207d ago").** Collect ingests items with very
   old/garbage `published_at` (some feeds carry stale entries). Expectation:
   pulled stories should be ~that day. **Fix:** in `bbv2/collect.py`, **filter
   items to recent** (e.g. drop items whose `published_at` is older than N days,
   default ~2–3) before upsert; also sanity-check date parsing in
   `normalize.py`/`util.parse_to_utc_iso` (a misparse could yield epoch-ish
   dates). Keep it configurable.

### Then continue

- Wire the frontend env once API key/appId arrive; live-test login + the loop.
- Remaining roadmap (`_documentation/roadmap.md`): non-English filtering, LLM
  briefs (use **Haiku**), engagement (like/favorites/discuss), HN/arXiv fetchers.
- Trader data platform (`../trader/_plans/0017`) stays parked until bbv2 steady;
  first piece there is the kline collector.

Build order ref: `0001` design → consumer API → discovery → multi-user → dashboard
→ briefs → engagement.
