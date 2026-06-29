# 0031 — Make the agent conversant about discovered sources

## Problem

After `find_sources` (0030) runs, the **results card** shows the found sources +
their latest headlines + web results — but the **agent can't talk about any of
it**. The tool returns only "searching…"; the actual results are written to
`discovery_runs.result_json` and rendered by the card, never fed back into the
model's context. So when the user asks "list some articles from smokinggun.org" or
"summarize that ATF article," the agent says *"I don't have a way to browse a
website."* And `summarize_article` only searches the user's **subscribed** stories,
which the found-source articles aren't yet.

The user wants to **explore the found sources with the agent before adding them**:
list a source's articles, discuss them, summarize one — then decide.

## Fix (three parts)

### A. Enrich the discovery preview with article LINKS
Today a candidate carries `sample_headlines: string[]` (titles only — you can't
summarize a title). Change the feed sampling to capture `{title, url}` pairs and a
few more of them:
- `feed_headline_finder` → returns `[{title, url}]` from the feed's recent entries
  (`fetch_rss_feed` items already have `title` + `url`).
- candidate shape: `sample_articles: [{title, url}]` (replaces `sample_headlines`),
  up to ~6. The card shows the first 2 titles (unchanged look); the agent gets all
  6 **with URLs** so it can summarize them.

### B. Feed the conversation's latest search into the agent context
Extend `_context_block` (pass `conversation_id`) to inject the most recent **done**
discovery run in this conversation (recent + not yet committed), compact:
```
Recent web search you ran: "smith & wesson glock …". Found sources (not yet
added): smokinggun.org [The New ATF Director…; The Firearms Industry on Father's
Day…], thereload.com [Analysis: SCOTUS…; Podcast…], … . You can read more from a
source with read_source, and summarize any article with summarize_article(url=…).
These aren't in the user's feed yet.
```
So the agent inherently knows what it found and can **list/discuss** it directly
instead of claiming it can't. Bounded: one run, ≤6 sources × 2 titles, only while
the search is fresh (≤ ~30 min and uncommitted).

### C. Two tool upgrades for depth
1. **`read_source(source)`** — fetch a specific source's **recent articles**
   (title + url, ~15) beyond the 2-paragraph preview. Resolves `source` as: an
   http(s) feed URL → fetch directly; else a domain/name → match the conversation's
   latest-search candidates, then the user's subscribed sources. Safe-fetched, no
   LLM. Lets the agent answer "list articles from smokinggun.org" with real depth,
   and hand the URLs to summarize.
2. **`summarize_article(url=…)`** — add an optional `url` param. If given, fetch +
   summarize **that URL** (an article from the search, not yet subscribed); else
   the current behavior (search subscribed stories by query). Reuses `_fetch_text`
   + the summarizer.

`execute_tool` gains a `conversation_id` parameter so `read_source` can resolve
against the conversation's latest search. A store helper
`latest_discovery_with_results(user_id, conversation_id)` returns that run's
parsed result.

## Phases

- **P1 — enriched samples:** `feed_headline_finder` → `[{title,url}]`;
  `discover_for_query` → `sample_articles`; update `DiscoveryCard` + `api.types` +
  tests. (`discover_sources`/provisioning passes no headline finder, unaffected.)
- **P2 — context awareness:** thread `conversation_id` into `_context_block`;
  inject the latest conversation search (compact, gated on recency/uncommitted) +
  `latest_discovery_with_results` store helper.
- **P3 — tools:** `read_source` tool + handler (+ `execute_tool` conversation_id);
  `summarize_article` `url` param; schemas + tool descriptions.
- **P4 — prompt + docs:** nudge the agent to use these when asked about a found
  source/article; update architecture/CLAUDE; record deviations.

## Tests
- discovery returns `sample_articles` with urls; card/types updated.
- `read_source` resolves a feed URL and a found-source domain → recent articles;
  unknown source → graceful error.
- `summarize_article(url=…)` summarizes an arbitrary URL (injected fetch + fake gen).
- context block includes the recent search's sources when present, omits it when
  committed/absent.

## Non-goals
Not building per-article persistence for un-added sources (we fetch on demand).
Not auto-adding sources just because the user explored them — add stays explicit.
</content>
