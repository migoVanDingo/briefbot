# 0002 — Ingestion Core

**Status:** Proposed (awaiting review)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** [0001 design](./0001-bbv2-design.md)

## Goal

Stand up bbv2's own ingestion pipeline: its **own** SQLite DB, a
topics/sources/items schema, a copied-and-adapted `collect` pipeline, an hourly
collect, and a CLI to hand-seed a topic + sources and run a collect. Single
profile — no multi-user, API, discovery, LLM, dashboard, or briefs yet.

## Hard guardrails

- **Never modify the original briefbot** (`~/Developer/agent/projects/ai-assistant`).
- **Never open/connect to og briefbot's database.** bbv2 has its **own** fresh DB
  (`BBV2_DB_PATH`, default `data/bbv2.db`). We copy *code* out of og briefbot and
  adapt it; we do not share its data, schema instance, or runtime.
- Copying is one-directional: og briefbot → bbv2.

## Scope

- **In:** Python project scaffold; own SQLite schema (topics, sources,
  topic_sources, items, item_topics, feed/discovery cache); copied
  `util/fetch/normalize/discover` + adapted `store`; a simple `score`; the
  `collect` flow with `item_topics` mapping; a CLI; an hourly collect runner;
  tests.
- **Out (later phases):** consumer API (0003-era), agent source discovery
  (Brave), multi-user/settings/email, dashboard/Headlines, LLM briefs, engagement.

## Project layout (new, in this repo)

```
briefbot/                  (repo root = bbv2)
  bbv2/                    Python package
    __init__.py
    __main__.py            `python -m bbv2 …`
    cli.py                 commands: init, topic, source, collect, items
    config.py              env/config (BBV2_* ), paths
    store.py               own schema + upserts + queries  (adapted from og)
    fetch.py               feed/site fetch w/ conditional GET   (copied)
    normalize.py           item normalization                   (copied)
    discover.py            RSS/Atom autodiscovery from a site    (copied)
    score.py               simple recency × source-weight score  (slim)
    util.py                time/json/dir helpers                 (copied)
  scripts/collect.sh       hourly runner (cron/launchd on the server)
  tests/                   pytest
  requirements.txt
  .env.example             BBV2_DB_PATH, etc.
  data/                    bbv2.db, caches  (gitignored)
```

Mirror og briefbot's stack so copied modules drop in: `feedparser`,
`beautifulsoup4`, `requests`, `pydantic`, `PyYAML`, `RapidFuzz`, `python-dotenv`.
(No FastAPI/Anthropic/Brave yet — those arrive in later phases.)

## Schema (bbv2's own SQLite, WAL)

Adapted from og briefbot's `items`/cache tables, plus the new topic model:

```sql
topics(id, slug UNIQUE, name, description, created_at)
sources(id, type, url, name, tags_json, weight, status, discovered_by, created_at)
        -- type: rss|site|hn|arxiv ; status: candidate|active|rejected
topic_sources(topic_id, source_id, PRIMARY KEY(topic_id, source_id))
items(item_id PK, dedupe_key UNIQUE, canonical_url, source_id, source_name,
      title, url, published_at, fetched_at, summary, score, raw_json)
item_topics(item_id, topic_id, PRIMARY KEY(item_id, topic_id))
feed_cache(feed_url PK, etag, last_modified, last_checked_at)        -- from og
discovered_feeds(site_url PK, feeds_json, discovered_at)             -- from og
```

(`users`, `subscriptions`, `user_settings`, `favorites`, `likes`, `api_tokens`
land in later phases — see 0001.)

## Collect flow

```
load active sources (optionally filtered by topic)
  → fetch each (conditional GET via feed_cache: ETag/Last-Modified)
  → normalize items
  → dedupe (dedupe_key)
  → score (recency × source weight)
  → upsert into items
  → map each item to its source's topic(s) via item_topics
```

## CLI

```bash
python -m bbv2 init                                   # create data/bbv2.db
python -m bbv2 topic add crypto --name "Crypto" --description "…"
python -m bbv2 source add --topic crypto --type rss --url <feed> --name "…"
python -m bbv2 source add --topic crypto --type site --url <site>   # autodiscovers feed
python -m bbv2 collect [--topic crypto]               # run the pipeline
python -m bbv2 items --topic crypto --since 24h --limit 20   # peek
```

## Scheduling

`scripts/collect.sh` loads `.env`, activates the venv, runs `python -m bbv2
collect`, logs to `data/logs/`. Hourly via cron/launchd **on the home server**
(an example plist/crontab line in the script's header). Keep it dumb — just the
collect; nightly LLM brief comes in a later phase.

## Tasks

- [ ] **1** Scaffold the Python project (venv, `requirements.txt` subset,
      `.env.example`, package skeleton, gitignored `data/`).
- [ ] **2** Copy `util.py` as-is; copy `fetch.py`, `normalize.py`, `discover.py`.
- [ ] **3** Adapt `store.py` to the bbv2 schema above (own DB path, init +
      migrations, item upsert/dedupe, `item_topics` mapping, topic/source CRUD).
- [ ] **4** Slim `score.py` (recency × source weight; refine later).
- [ ] **5** `collect` pipeline wiring the above.
- [ ] **6** `cli.py` / `__main__.py`: init, topic add, source add (+ site→feed
      discovery), collect, items.
- [ ] **7** `scripts/collect.sh` + a documented hourly cron/launchd example.
- [ ] **8** Tests (pytest): normalize, dedupe, score (pure) + a `collect` smoke
      test against a local fixture feed (no network).
- [ ] **9** `CLAUDE.md` for bbv2: stack, the og-briefbot guardrails, run commands,
      and modularity rules (mirror the trader project's discipline).

## Done when

`init` → `topic add crypto` → `source add … --topic crypto` → `collect` produces
items in `data/bbv2.db` mapped to `crypto` via `item_topics`; `items --topic
crypto` lists them; tests pass; **og briefbot is untouched and its DB is never
opened**.

## Notes

- Carry the trader project's discipline: small focused modules, pure logic
  testable without I/O, no dead code.
- A local fixture feed (a saved RSS XML file) keeps tests network-free and fast.
