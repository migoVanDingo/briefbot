# 0017 — Headlines date rail + de-duplicated brief

**Status:** ✅ Done — **Date:** 2026-06-21

Rework the Headlines page so a user can browse past days and the per-topic view
isn't three copies of the same story list.

## Changes

1. **Date rail (left column).** The last **10 calendar days** for the active
   topic. Each day with a brief shows `MMM D, YYYY — <title truncated to 15 chars>`
   and is selectable; days without a brief render disabled. Selecting a day shows
   that day's brief + **only that day's stories**. (User decisions: all 10 calendar
   days shown even when empty; past-date view filters stories to that day.)
2. **Drop the "Today" tab.** Tabs are just the user's topics (briefs are per-topic);
   the page defaults to the first topic + today.
3. **De-dup the brief card.** Removed the **Trending** cards and the **Sources**
   title-list; kept only the main story list (`StoryRow` already renders title +
   blurb + time + vote/save). The brief card is now title + summary only.

## Implementation

- **Backend:** `store.briefs_since(topic_id, since_date)` + `GET /api/topics/{slug}/briefs`
  (read-only; builds the last-10-day skeleton in UTC to match brief `date` keys,
  attaches each day's brief or null — never triggers an LLM build). Today's brief is
  still built on demand via the existing rundown endpoint when today is selected.
  Past-day stories reuse `/stories` with a `from`/`to` day window (already supported).
- **Frontend:** `api.topicBriefs(slug)` + `BriefDay`; `Headlines.tsx` rewritten
  (date rail + topic tabs + slim `BriefCard`); `styles/headlines.css` (rail layout,
  responsive stack) added to the barrel.
- **Tests:** `test_topic_briefs_rail` (10-day shape, brief vs null). 136 pytest +
  dashboard `tsc`/build green.

## Responsive nav (same session)

The topbar overflowed on phones. Below the tablet breakpoint (**≤768px**) the nav
+ right-side controls are hidden and replaced by a **hamburger menu** with a theme
toggle beside it. The menu has three sections: (1) main nav (Headlines/Stories/
Topics/Chat/Favorites, + Admin for admins), (2) a dynamic section — the Headlines
topic tabs (Crypto/Finance/Sports) when on `/headlines`, driven by a shared
`state/headlinesNav` store so picking one switches the active topic, (3) Settings +
Sign out. Added `overflow-wrap` so long titles/URLs wrap (no horizontal page
scroll); the date rail keeps its own horizontal scroll.

## Note

Requires a `bbv2 serve` restart to pick up the new endpoint (frontend hot-reloads).
