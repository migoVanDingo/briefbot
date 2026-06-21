"""Build a topic's daily brief.

Pipeline: pull the topic's recent items → cluster them into trending storylines →
ask Haiku for a day title + a short narrative ("what's going on today") over the
top stories → persist {title, summary, trending, sources} to the `briefs` table.

The LLM call is injected (`generate`) so this is unit-testable offline with a
fake. bbv2 uses Haiku for the real call (cost).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import config, ids
from .cluster import cluster_items
from .llm import extract_json, generate_text
from .store import Store

Generate = Callable[..., str]

TOP_STORIES = 8          # stories fed to the summary + listed as sources
TOP_TRENDING = 5         # storylines shown in the Trending section
RECENT_WINDOW_HOURS = 48  # how far back "today's" brief looks


def _row_to_item(r: Any) -> dict[str, Any]:
    return {
        "item_id": r["item_id"],
        "title": r["title"],
        "url": r["url"],
        "source_id": r["source_id"],
        "source_name": r["source_name"],
        "published_at": r["published_at"],
        "fetched_at": r["fetched_at"],
        "summary": r["summary"],
        "score": r["score"],
    }


def _prompt(topic_name: str, stories: list[dict[str, Any]]) -> str:
    lines = []
    for i, s in enumerate(stories, 1):
        summ = (s.get("summary") or "").strip().replace("\n", " ")
        if len(summ) > 280:
            summ = summ[:280] + "…"
        lines.append(f"{i}. [{s.get('source_name')}] {s.get('title')}\n   {summ}")
    body = "\n".join(lines)
    return (
        f'You are writing today\'s news brief for the topic "{topic_name}".\n'
        "Using ONLY the stories below, return STRICT JSON (no markdown, no prose "
        "outside the JSON) of the form:\n"
        '{"title": "...", "summary": "..."}\n'
        '- "title": a short, specific headline for the day (<= 12 words).\n'
        '- "summary": 2-3 short plain-text paragraphs (NO bullet points, NO '
        "markdown) on what's going on today, grouped into a few storylines. End "
        "with one sentence starting exactly 'What to watch next:'.\n"
        "Separate paragraphs with a blank line. Do not invent facts beyond the "
        "stories provided.\n\n"
        f"Stories:\n{body}"
    )


def build_brief(
    store: Store,
    topic_slug: str,
    *,
    date: str | None = None,
    generate: Generate | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Build + persist a topic's brief. Returns the brief dict, or None if the
    topic has no recent items."""
    topic = store.get_topic(topic_slug)
    if not topic:
        raise ValueError(f"unknown topic '{topic_slug}'")
    now = now or datetime.now(timezone.utc)
    date = date or now.date().isoformat()
    generate = generate or generate_text

    since = (now - timedelta(hours=RECENT_WINDOW_HOURS)).replace(microsecond=0).isoformat()
    rows = store.items_for_topic(topic_slug, since_iso=since, limit=80)
    if not rows:
        return None
    items = [_row_to_item(r) for r in rows]

    trending = cluster_items(items, now=now)[:TOP_TRENDING]
    top_stories = sorted(
        items, key=lambda x: float(x.get("score") or 0.0), reverse=True
    )[:TOP_STORIES]

    raw = generate(_prompt(topic["name"], top_stories), max_tokens=900, temperature=0.2)
    data = extract_json(raw)
    title = (data.get("title") or f"{topic['name']} — {date}").strip()
    summary = (data.get("summary") or "").strip()

    brief = {
        "id": ids.new_id(ids.BRIEF),
        "topic_id": int(topic["id"]),
        "date": date,
        "title": title,
        "summary": summary,
        "trending": [
            {
                "label": t["label"],
                "trend_score": t["trend_score"],
                "item_count": t["item_count"],
                "representative_title": t["representative_title"],
                "representative_url": t["representative_url"],
            }
            for t in trending
        ],
        "sources": [
            {
                "title": s["title"],
                "url": s["url"],
                "source_name": s["source_name"],
                "item_id": s["item_id"],
            }
            for s in top_stories
        ],
        "model": config.anthropic_model(),
    }
    store.upsert_brief(brief)
    return brief


def get_or_build_brief(
    store: Store,
    topic_slug: str,
    *,
    generate: Generate | None = None,
    now: datetime | None = None,
) -> Any | None:
    """Return today's brief for a topic, building it **once** if missing.

    This is the on-demand "topic rundown": the first visitor that day triggers the
    synthesis; every later visitor (any user) reads the cached `(topic_id, date)`
    row. Returns the brief dict (built) or the existing brief row, or None if the
    topic has no recent items to summarize."""
    topic = store.get_topic(topic_slug)
    if not topic:
        raise ValueError(f"unknown topic '{topic_slug}'")
    now = now or datetime.now(timezone.utc)
    date = now.date().isoformat()
    existing = store.get_brief(int(topic["id"]), date)
    if existing is not None:
        return existing
    built = build_brief(store, topic_slug, date=date, generate=generate, now=now)
    if built is None:
        return None
    # Return the persisted row so callers always get a uniform shape.
    return store.get_brief(int(topic["id"]), date)


def build_all_briefs(
    store: Store,
    *,
    date: str | None = None,
    generate: Generate | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Build briefs for every topic that has recent items."""
    built = 0
    skipped = 0
    for t in store.list_topics():
        result = build_brief(store, t["slug"], date=date, generate=generate, now=now)
        if result is None:
            skipped += 1
        else:
            built += 1
    return {"built": built, "skipped": skipped}
