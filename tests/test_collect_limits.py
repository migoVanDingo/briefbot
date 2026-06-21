"""Per-topic source cap + per-source story cap (new-topic defaults)."""

import requests

import bbv2.collect as collect_mod
import bbv2.config as config
import bbv2.discovery as discovery
from bbv2.store import Store


def _item(i: int) -> dict:
    return {
        "item_id": f"ITM{i}",
        "dedupe_key": f"url:{i}",
        "canonical_url": f"https://e/{i}",
        "source_id": "1",
        "source_name": "X",
        "title": f"Story {i}",
        "url": f"https://e/{i}",
        "published_at": "2026-06-20T00:00:00+00:00",
        "fetched_at": "2026-06-20T00:00:00+00:00",
        "summary": "s",
        "score": 1.0,
        "raw": {},
    }


def test_collect_source_caps_stories(monkeypatch):
    monkeypatch.setattr(config, "max_stories_per_source", lambda: 7)
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    row = store.active_sources("crypto")[0]

    monkeypatch.setattr(
        collect_mod, "fetch_rss_feed",
        lambda *a, **k: ([_item(i) for i in range(20)], "ok"),
    )

    stats = collect_mod._empty_stats()
    collect_mod.collect_source(store, row, requests.Session(), 20, stats)
    assert stats["items"] == 7  # capped, even though the feed had 20


def test_collect_item_failure_does_not_sink_topic(monkeypatch):
    monkeypatch.setattr(config, "max_stories_per_source", lambda: 5)
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    row = store.active_sources("crypto")[0]
    monkeypatch.setattr(
        collect_mod, "fetch_rss_feed",
        lambda *a, **k: ([_item(i) for i in range(5)], "ok"),
    )
    # One bad upsert must be counted as an error, not raised.
    calls = {"n": 0}
    real = store.upsert_item

    def flaky(item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("transient")
        return real(item)

    monkeypatch.setattr(store, "upsert_item", flaky)
    stats = collect_mod._empty_stats()
    collect_mod.collect_source(store, row, requests.Session(), 20, stats)  # no raise
    assert stats["items"] == 4 and stats["errors"] == 1


def test_collect_drops_stale_then_keeps_newest_under_cap(monkeypatch):
    from datetime import datetime, timedelta, timezone

    # Tight cap so the newest-first sort decides WHICH items survive.
    monkeypatch.setattr(config, "max_stories_per_source", lambda: 2)
    monkeypatch.setattr(config, "collect_max_age_days", lambda: 14)
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    row = store.active_sources("crypto")[0]

    now = datetime.now(timezone.utc)

    def dated(i, days_ago):
        it = _item(i)
        it["published_at"] = (now - timedelta(days=days_ago)).isoformat()
        return it

    # Feed order is deliberately NOT newest-first; Story 2 is stale (40d old).
    feed = [dated(1, 3), dated(2, 40), dated(3, 1), dated(4, 10)]
    monkeypatch.setattr(collect_mod, "fetch_rss_feed", lambda *a, **k: (feed, "ok"))

    stats = collect_mod._empty_stats()
    collect_mod.collect_source(store, row, requests.Session(), 20, stats)
    assert stats["items"] == 2  # stale dropped, then capped to 2

    # The two newest fresh items (1d, 3d) survive — NOT the 10-day-old one,
    # proving the cap applies after a newest-first sort (not feed order).
    titles = {r["title"] for r in store.items_for_topic("crypto", limit=10)}
    assert titles == {"Story 3", "Story 1"}


def test_discovery_caps_sources(monkeypatch):
    monkeypatch.setattr(config, "max_sources_per_topic", lambda: 5)
    store = Store(":memory:")
    store.add_topic("crypto", "Crypto", "markets")
    # Searcher returns many homepages; each yields a feed → would be 10 without a cap.
    sites = [f"https://site{i}.example" for i in range(10)]
    out = discovery.discover_sources(
        store,
        "crypto",
        searcher=lambda q, n: [{"url": s, "title": s} for s in sites],
        feed_finder=lambda site: [f"{site}/feed"],
    )
    assert out["candidates"] <= 5
    assert len(store.list_candidates("crypto")) <= 5
