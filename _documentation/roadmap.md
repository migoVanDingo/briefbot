# bbv2 — Roadmap & backlog

Phased build is tracked in [`../_plans/`](../_plans/). This file holds backlog
items and known rough edges to address later.

## Known issues / refinements

- **Language filtering (English).** Discovery and collection surface some
  **non-English** sources/items. Address later via:
  - bias Brave search to English (`search_lang=en`, `country`/`ui_lang` params);
  - a **per-topic and/or per-user language preference**;
  - **language detection** on items → tag, and filter/hide non-preferred
    languages (don't necessarily drop the source, just the items).
- **Candidate quality** (0004): the probe path can still propose weak feeds
  (aggregators, comments feeds). Consider an LLM ranker/labeler and a feed
  "health" check (does it have recent, real entries?) before showing candidates.
- **LLM query crafting** (0004 note): use Claude to turn a topic into better
  search queries than the current heuristics.
- **Feed-URL dedupe:** treat trailing-slash variants (`/feed` vs `/feed/`) as one.

## Upcoming phases (see _plans)

- 0005 — multi-user + settings + per-user email.
- Dashboard (Headlines feed, topic/source management) — styling per
  [`ui-style.md`](./ui-style.md).
- Daily briefs / LLM synthesis.
- Engagement (like / favorites / discuss-with-agent).
- HN/arXiv fetchers (normalizers already exist).
