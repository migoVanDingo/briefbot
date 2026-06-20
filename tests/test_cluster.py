from datetime import datetime, timezone

from bbv2.cluster import cluster_items

NOW = datetime(2025, 1, 8, 12, tzinfo=timezone.utc)


def _item(iid, title, when, source="s1"):
    return {
        "item_id": iid,
        "title": title,
        "url": f"https://e/{iid}",
        "source_id": source,
        "source_name": source,
        "published_at": when,
        "fetched_at": when,
        "score": 1.0,
    }


def test_near_duplicate_titles_cluster_separate_topic_splits():
    items = [
        _item("a", "Bitcoin rallies on ETF approval news today", "2025-01-08T08:00:00+00:00", "s1"),
        _item("b", "Bitcoin rallies on ETF approval news", "2025-01-08T09:00:00+00:00", "s2"),
        _item("c", "Best pasta recipe for dinner tonight", "2025-01-08T10:00:00+00:00", "s3"),
    ]
    clusters = cluster_items(items, now=NOW)
    # two bitcoin items merge; the pasta item stands alone
    assert sorted(c["item_count"] for c in clusters) == [1, 2]
    # the 2-item, 2-source storyline has the higher trend score → ranked first
    assert clusters[0]["item_count"] == 2
    assert clusters[0]["sources_count"] == 2
    # label is built from the shared title tokens (tie order is arbitrary)
    assert any(
        tok in clusters[0]["label"]
        for tok in ("bitcoin", "etf", "approval", "rallies", "news")
    )
    assert clusters[0]["trend_score"] >= clusters[1]["trend_score"]


def test_representative_is_highest_score():
    items = [
        _item("a", "Ethereum upgrade ships", "2025-01-08T08:00:00+00:00"),
        _item("b", "Ethereum upgrade ships smoothly", "2025-01-08T09:00:00+00:00"),
    ]
    items[1]["score"] = 9.0
    clusters = cluster_items(items, now=NOW)
    assert clusters[0]["representative_url"] == "https://e/b"


def test_empty():
    assert cluster_items([], now=NOW) == []
