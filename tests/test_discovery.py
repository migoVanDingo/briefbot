from bbv2.brave import brave_search
from bbv2.discovery import build_queries, discover_sources
from bbv2.store import Store


def test_build_queries_includes_name():
    qs = build_queries("Crypto", "digital assets")
    assert any("Crypto" in q for q in qs)
    assert any("digital assets" in q for q in qs)


def _fake_searcher(results_by_substr):
    def searcher(query, count):
        for substr, results in results_by_substr.items():
            if substr in query:
                return results[:count]
        return []

    return searcher


def test_discover_adds_candidates_linked_but_not_active():
    store = Store(":memory:")
    store.add_topic("crypto", "Crypto", "")

    # Two queries surface the same domain twice (dedupe) + a second domain.
    searcher = _fake_searcher(
        {
            "Crypto news": [
                {"url": "https://alpha.example/post1", "title": "Alpha"},
                {"url": "https://alpha.example/post2", "title": "Alpha 2"},
            ],
            "Crypto rss feed": [{"url": "https://beta.example/x", "title": "Beta"}],
        }
    )
    feeds = {
        "https://alpha.example/": ["https://alpha.example/feed.xml"],
        "https://beta.example/": ["https://beta.example/rss"],
    }

    stats = discover_sources(
        store,
        "crypto",
        searcher=searcher,
        feed_finder=lambda site: feeds.get(site, []),
        per_query=10,
    )

    assert stats["candidates"] == 2  # alpha deduped to one feed + beta
    cands = store.list_candidates("crypto")
    urls = {c["url"] for c in cands}
    assert urls == {"https://alpha.example/feed.xml", "https://beta.example/rss"}
    assert all(c["status"] == "candidate" and c["discovered_by"] == "brave" for c in cands)
    # Candidates are NOT collected until approved.
    assert store.active_sources("crypto") == []
    store.close()


def test_approve_makes_candidate_active():
    store = Store(":memory:")
    store.add_topic("crypto", "Crypto", "")
    discover_sources(
        store,
        "crypto",
        searcher=_fake_searcher({"Crypto news": [{"url": "https://a.example/p", "title": "A"}]}),
        feed_finder=lambda site: ["https://a.example/feed"],
    )
    cid = store.list_candidates("crypto")[0]["id"]
    store.set_source_status(cid, "active")
    assert [s["id"] for s in store.active_sources("crypto")] == [cid]
    store.close()


def test_discover_skips_existing_feeds():
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto", "")
    sid = store.add_source("rss", "https://a.example/feed", "A", status="active")
    store.link_topic_source(tid, sid)
    stats = discover_sources(
        store,
        "crypto",
        searcher=_fake_searcher({"Crypto news": [{"url": "https://a.example/p", "title": "A"}]}),
        feed_finder=lambda site: ["https://a.example/feed"],
    )
    assert stats["candidates"] == 0  # already a source
    store.close()


class _StubResp:
    status_code = 200

    def json(self):
        return {
            "web": {
                "results": [
                    {"url": "https://x.example/a", "title": "A"},
                    {"title": "no url"},  # dropped
                ]
            }
        }


class _StubSession:
    def get(self, *a, **k):
        return _StubResp()


def test_brave_search_parses_results():
    out = brave_search("q", api_key="k", session=_StubSession())
    assert out == [{"url": "https://x.example/a", "title": "A"}]
