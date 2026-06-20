import json
from datetime import datetime, timezone

from bbv2.brief import build_brief
from bbv2.store import Store

NOW = datetime(2025, 1, 8, 12, tzinfo=timezone.utc)


def _fake_generate(prompt, **kw):
    # The brief builder only depends on title + summary from the JSON.
    return '{"title": "Crypto heats up", "summary": "Para one.\\n\\nWhat to watch next: more ETFs."}'


def _seed(store: Store) -> int:
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    for iid, title, when in [
        ("ITMa", "Bitcoin rallies on ETF approval news today", "2025-01-08T08:00:00+00:00"),
        ("ITMb", "Bitcoin rallies on ETF approval news", "2025-01-08T09:00:00+00:00"),
    ]:
        store.upsert_item(
            {
                "item_id": iid,
                "dedupe_key": f"url:{iid}",
                "canonical_url": f"https://e/{iid}",
                "source_id": str(sid),
                "source_name": "X",
                "title": title,
                "url": f"https://e/{iid}",
                "published_at": when,
                "fetched_at": when,
                "summary": "Some summary.",
                "score": 2.0,
                "raw": {},
            }
        )
        store.map_item_topic(iid, tid)
    return tid


def test_build_brief_persists_and_returns():
    store = Store(":memory:")
    tid = _seed(store)
    b = build_brief(store, "crypto", generate=_fake_generate, now=NOW)
    assert b is not None
    assert b["title"] == "Crypto heats up"
    assert "What to watch next" in b["summary"]
    assert len(b["sources"]) == 2
    assert b["trending"]  # at least one storyline
    assert b["id"].startswith("BRF")

    row = store.get_brief(tid, "2025-01-08")
    assert row is not None and row["title"] == "Crypto heats up"
    assert len(json.loads(row["sources_json"])) == 2
    assert store.latest_brief(tid)["date"] == "2025-01-08"


def test_build_brief_no_recent_items_returns_none():
    store = Store(":memory:")
    store.add_topic("empty", "Empty")
    assert build_brief(store, "empty", generate=_fake_generate, now=NOW) is None
