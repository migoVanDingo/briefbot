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
#   GET /health · GET /topics · GET /items?topic=&since=&limit=  (Bearer token)

pytest        # offline tests (no network)
```

`scripts/collect.sh` is the hourly runner (cron/launchd on the server).

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
  api.py         FastAPI consumer API (token-auth read: /health /topics /items)
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

- `_plans/0001-bbv2-design.md` — design (decision-complete).
- `_plans/0002-ingestion-core.md` — this phase.
- Next phases: consumer API → agent discovery (Brave) → multi-user + settings +
  email → dashboard (see `_documentation/ui-style.md`) → briefs → engagement.
