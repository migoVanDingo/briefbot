from pathlib import Path

import feedparser

from bbv2.normalize import normalize_feed_entry
from bbv2.score import compute_score
from bbv2.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def _items(source):
    parsed = feedparser.parse(FIXTURE.read_text())
    return [normalize_feed_entry(source, dict(e)) for e in parsed.entries]


def test_topic_source_item_flow():
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto", "")
    sid = store.add_source("rss", "https://example.com/feed", "Sample", tags=["crypto"])
    store.link_topic_source(tid, sid)

    assert [r["id"] for r in store.active_sources("crypto")] == [sid]
    assert store.source_topic_ids(sid) == [tid]

    src = {"id": str(sid), "name": "Sample", "tags": ["crypto"]}
    items = _items(src)
    for it in items:
        it["score"] = compute_score(it)
        assert store.upsert_item(it) is True
        store.map_item_topic(it["item_id"], tid)

    # Re-inserting a duplicate is ignored.
    assert store.upsert_item(items[0]) is False

    rows = store.items_for_topic("crypto", limit=10)
    assert len(rows) == 2
    assert "Bitcoin rallies on ETF news" in {r["title"] for r in rows}
    store.close()


def test_add_topic_and_source_are_idempotent():
    store = Store(":memory:")
    t1 = store.add_topic("crypto", "Crypto")
    t2 = store.add_topic("crypto", "Crypto again")
    assert t1 == t2  # same row, not a duplicate
    s1 = store.add_source("rss", "https://x.com/feed", "X")
    s2 = store.add_source("rss", "https://x.com/feed", "X")
    assert s1 == s2
    store.close()


def test_feed_cache_headers_roundtrip():
    store = Store(":memory:")
    assert store.get_feed_cache_headers("u") == {}
    store.set_feed_cache_headers("u", "etag123", "Mon, 01 Jan 2025 00:00:00 GMT")
    headers = store.get_feed_cache_headers("u")
    assert headers["If-None-Match"] == "etag123"
    assert headers["If-Modified-Since"].startswith("Mon")
    store.close()
