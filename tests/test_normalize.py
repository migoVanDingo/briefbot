from pathlib import Path

import feedparser

from bbv2.normalize import normalize_feed_entry

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def _entries():
    return feedparser.parse(FIXTURE.read_text()).entries


def test_normalize_feed_entry_basic():
    src = {"id": "1", "name": "Sample", "tags": ["crypto"]}
    item = normalize_feed_entry(src, dict(_entries()[0]))
    assert item["title"] == "Bitcoin rallies on ETF news"
    assert item["source_id"] == "1"
    assert item["canonical_url"].startswith("https://example.com/btc-etf")
    assert "utm_source" not in item["canonical_url"]  # tracking param stripped
    assert item["dedupe_key"].startswith("url:")
    assert item["published_at"].endswith("+00:00")


def test_dedupe_key_and_item_id_are_stable():
    src = {"id": "1", "name": "Sample"}
    a = normalize_feed_entry(src, dict(_entries()[0]))
    b = normalize_feed_entry(src, dict(_entries()[0]))
    assert a["dedupe_key"] == b["dedupe_key"]
    assert a["item_id"] == b["item_id"]
