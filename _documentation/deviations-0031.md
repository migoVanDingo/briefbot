# 0031 — deviations & notes (agent conversant about found sources)

Plan: `_plans/0031`. Built on top of 0030.

## What shipped

- **Discovery preview now carries article URLs.** Candidate `sample_headlines:
  string[]` → `sample_articles: [{title, url}]` (up to 6). `feed_headline_finder`
  returns `{title, url}`; the card still shows the first 2 titles. This is what
  lets the agent summarize a specific found article (it has the URL).
- **Agent context injection.** `_context_block` now takes `conversation_id` and
  appends the conversation's most-recent **done, uncommitted, ≤30-min** search:
  its query + up to 6 sources with 2 article titles each, plus a nudge to use
  `read_source` / `summarize_article(url=…)`. So the agent stops saying "I can't
  browse that" — it knows what it found. Drops out once the search is committed
  (the stories are then subscribed → `search_stories` covers them).
- **Two tool upgrades:**
  - `read_source(source, limit?)` — lists a source's recent articles (title+url).
    `source` resolves as a literal URL, else a match against the conversation's
    latest search candidates (by domain/name/url), else a subscribed source.
  - `summarize_article(url=…, title?)` — summarizes an arbitrary URL (a found
    article not yet subscribed); `query` still summarizes a subscribed story.
  - `execute_tool` gained a `conversation_id` param so `read_source` can resolve
    against the conversation's search.

## Deviations / decisions

- **Chose context-injection over a `get_found_sources` tool.** Injecting a compact
  summary of the active search makes the agent reliably *aware* (so it won't deny
  the capability), while `read_source` provides depth on demand. Avoids the model
  failing to connect a source name to a tool.
- **`sample_articles` replaces `sample_headlines` outright** (uncommitted feature,
  no back-compat needed). The commit-path test fixtures still carry the old key as
  an ignored field — commit only reads `name`/`url`, so they're harmless.
- **`read_source` fetches live, no persistence.** Articles for un-added sources are
  fetched on demand (safe-fetched via `feed_headline_finder`), not stored. A
  down/blocked feed returns a graceful "no readable articles" error.
- **Subscribed-source resolution iterates the user's topics' sources.** Fine at
  personal scale; if topic/source counts grow, add an indexed lookup.

## Known follow-ups

- `read_source` titles come from the RSS feed, so depth is limited to what the feed
  exposes (often 10-20 recent items). No pagination/archive crawl.
- The 30-min/uncommitted window for context injection is heuristic; if a user
  returns to an old thread to ask about a stale search, they may need to re-run it.

## Tests

`test_agent_sources.py` (read_source resolve/url/unknown, summarize-by-url,
context injection present/committed/no-conversation) + updated
`test_discovery.py` for `sample_articles`. **231 pytest pass; pyflakes + build clean.**
</content>
