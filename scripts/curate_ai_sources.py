#!/usr/bin/env python3
"""One-off: curate the `ai` topic's sources (idempotent).

Adds a vetted set of AI company/research feeds + arXiv research-paper feeds, prunes
known-junk feeds, then collects + runs the relevance review so off-topic items are
filtered. Targets whatever DB `BBV2_DB_PATH` points at, so it works on the server
too. Safe to re-run.

    .venv/bin/python scripts/curate_ai_sources.py
"""

from __future__ import annotations

from bbv2 import config
from bbv2.store import Store

GOOD_FEEDS = [
    ("OpenAI News", "https://openai.com/news/rss.xml"),
    ("Google DeepMind Blog", "https://deepmind.google/discover/blog/feed/"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ("Google Research Blog", "https://research.google/blog/rss/"),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/"),
    ("AWS Machine Learning Blog", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("Stability AI News", "https://stability.ai/news-updates?format=rss"),
    ("Google Developers Blog", "https://developers.googleblog.com/feed/"),
    # arXiv research papers — the export host returns a backlog (rss.arxiv.org is
    # empty on weekends).
    ("arXiv: Artificial Intelligence (cs.AI)", "https://export.arxiv.org/rss/cs.AI"),
    ("arXiv: Machine Learning (cs.LG)", "https://export.arxiv.org/rss/cs.LG"),
    ("arXiv: Computation & Language (cs.CL)", "https://export.arxiv.org/rss/cs.CL"),
    ("arXiv: Computer Vision (cs.CV)", "https://export.arxiv.org/rss/cs.CV"),
    ("arXiv: Statistics – ML (stat.ML)", "https://export.arxiv.org/rss/stat.ML"),
]

# Junk feeds to prune if present (substring match on the source URL).
JUNK_MARKERS = (
    "theguardian.com/us/rss",
    "onlinedegrees.sandiego.edu",
    "feeder.co",
    "medium.com/feed/@",
    "wired.com/feed",
    "ai.meta.com/blog/feeds",  # 404 (dead)
    "databricks.com/blog/category",  # serves HTML, not a feed
)


def main() -> None:
    store = Store(str(config.db_path()))
    topic = store.get_topic("ai")
    if not topic:
        raise SystemExit("no 'ai' topic — create/subscribe to it first")
    tid = int(topic["id"])

    existing = store.source_urls()
    added = 0
    for name, url in GOOD_FEEDS:
        if url not in existing:
            added += 1
        sid = store.add_source("rss", url, name, status="active", discovered_by="curate")
        store.link_topic_source(tid, sid)
    print(f"added {added} new source(s)")

    pruned = 0
    for r in store.list_sources("ai"):
        if any(m in r["url"] for m in JUNK_MARKERS):
            store.delete_source(r["id"])
            pruned += 1
            print("  pruned:", r["name"][:45])
    print(f"pruned {pruned} junk source(s); ai now has {len(store.list_sources('ai'))} sources")

    print("collecting…")
    from bbv2.collect import collect as run_collect

    stats = run_collect(store, "ai")
    print("  ", {k: stats[k] for k in ("feeds", "new", "errors") if k in stats})

    print("reviewing (LLM relevance)…")
    from bbv2.models import relevance_generate
    from bbv2.review import quickscan_topic

    res = quickscan_topic(store, "ai", generate=relevance_generate())
    print("  ", res)
    print(f"done — {len(store.items_for_topic('ai', limit=500))} relevant AI items visible")


if __name__ == "__main__":
    main()
