from bbv2.util import strip_html, titlecase


def test_titlecase():
    assert titlecase("crypto") == "Crypto"
    assert titlecase("world cup news") == "World Cup News"
    assert titlecase("BTC markets") == "BTC Markets"  # keeps acronym case


def test_strip_html():
    assert strip_html("<p>Hello <a href='x'>link</a></p>") == "Hello link"
    assert strip_html("a &amp; b") == "a & b"
    assert strip_html(None) == ""


def test_quickscan_drops_offtopic():
    from bbv2.review import quickscan_topic
    from bbv2.store import Store

    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    for iid, title in [("ITM1", "Bitcoin hits new high"), ("ITM2", "World Cup final recap")]:
        store.upsert_item(
            {
                "item_id": iid,
                "dedupe_key": f"url:{iid}",
                "canonical_url": f"https://e/{iid}",
                "source_id": str(sid),
                "source_name": "X",
                "title": title,
                "url": f"https://e/{iid}",
                "published_at": "2025-01-08T00:00:00+00:00",
                "fetched_at": "2025-01-08T00:00:00+00:00",
                "summary": "",
                "score": 1.0,
                "raw": {},
            }
        )
        store.map_item_topic(iid, tid)

    def fake_gen(prompt, **k):
        return '{"results":[{"id":"ITM1","relevant":true},{"id":"ITM2","relevant":false}]}'

    assert quickscan_topic(store, "crypto", generate=fake_gen) == {
        "reviewed": 2,
        "kept": 1,
        "dropped": 1,
    }
    # the off-topic item is now hidden from the topic feed; none left pending
    assert [r["title"] for r in store.items_for_topic("crypto", limit=10)] == [
        "Bitcoin hits new high"
    ]
    assert store.pending_relevance("crypto") == []
