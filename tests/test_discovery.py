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
    assert out == [{"url": "https://x.example/a", "title": "A", "description": ""}]


def test_craft_queries_uses_llm_with_fallback():
    from bbv2.discovery import craft_queries, build_queries
    gen = lambda prompt, **k: '["Glock new models news", "gun law changes", "NRA news"]'
    qs = craft_queries("Firearms", "", gen)
    assert qs == ["Glock new models news", "gun law changes", "NRA news"]
    # LLM error → heuristic fallback (never crashes discovery)
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    assert craft_queries("Firearms", "", boom) == build_queries("Firearms", "")
    # no generate → heuristic
    assert craft_queries("Firearms", "", None) == build_queries("Firearms", "")


def test_junk_feed_urls_filtered():
    from bbv2.discover import is_junk_feed_url
    assert is_junk_feed_url("https://en.wikipedia.org/w/api.php?action=featuredfeed&feed=potd")
    assert is_junk_feed_url("https://example.com/comments/feed/")
    assert not is_junk_feed_url("https://thefirearmblog.com/feed/")


def test_discover_retries_then_finds(monkeypatch):
    from bbv2.discovery import discover_sources
    from bbv2.store import Store

    store = Store(":memory:")
    store.add_topic("firearms", "Firearms")
    attempts_seen = []

    # First attempt's queries find nothing; a later attempt finds a feed.
    def fake_generate(prompt, **k):
        attempts_seen.append(prompt)
        # vary by attempt count so the retry produces different queries
        return f'["q{len(attempts_seen)}"]'

    def fake_search(query, n):
        return [{"url": "https://guns.example/post", "title": "Guns"}] if query == "q3" else []

    def fake_feed_finder(site):
        return ["https://guns.example/feed/"]

    stats = discover_sources(
        store, "firearms",
        generate=fake_generate, searcher=fake_search, feed_finder=fake_feed_finder,
        min_candidates=1,
    )
    assert stats["candidates"] == 1
    assert stats["attempts"] == 3  # retried until q3 hit
    assert stats["added"] == ["https://guns.example/feed/"]


def test_provision_errors_when_no_sources(monkeypatch):
    import bbv2.provision as provision
    from bbv2.store import Store

    store = Store(":memory:")
    store.add_topic("firearms", "Firearms")
    events = list(
        provision.provision_topic(
            store, "firearms",
            discover=lambda: {"candidates": 0},  # discovery found nothing
            collect=lambda: {"new": 0},
        )
    )
    assert events[-1]["type"] == "error"
    assert "couldn't find good sources" in events[-1]["message"]


# ---- topic-agnostic discovery for a free-text query (0030) ----

def test_discover_for_query_returns_candidates_web_and_headlines():
    from bbv2.discovery import discover_for_query

    def fake_search(query, n):
        return [
            {"url": "https://edutech.example/post", "title": "EdTech Today",
             "description": "K-12 learning research"},
            {"url": "https://journal.example/a", "title": "Journal of Learning",
             "description": "papers"},
        ]

    def fake_feed_finder(site):
        return [f"{site}feed/"]

    def fake_headlines(feed_url):
        return [
            {"title": "Multimodal learning in classrooms", "url": f"{feed_url}a"},
            {"title": "K-12 EdTech trends", "url": f"{feed_url}b"},
            {"title": "extra", "url": f"{feed_url}c"},
            {"title": "more", "url": f"{feed_url}d"},
        ]

    res = discover_for_query(
        "multimodal learning in K-12", "",
        searcher=fake_search, feed_finder=fake_feed_finder,
        headline_finder=fake_headlines, generate=lambda p, **k: '["q1"]',
        sample_articles=3,
    )
    assert res["query"] == "multimodal learning in K-12"
    urls = {c["url"] for c in res["candidates"]}
    assert "https://edutech.example/feed/" in urls
    assert "https://journal.example/feed/" in urls
    # sample articles captured (title+url) + capped at 3
    cand = next(c for c in res["candidates"] if c["url"] == "https://edutech.example/feed/")
    assert [a["title"] for a in cand["sample_articles"]] == [
        "Multimodal learning in classrooms", "K-12 EdTech trends", "extra"
    ]
    assert cand["sample_articles"][0]["url"] == "https://edutech.example/feed/a"
    # web results carry the Brave snippet
    assert res["web_results"][0]["snippet"] == "K-12 learning research"
    assert len(res["web_results"]) == 2


def test_discover_for_query_skips_existing_feeds():
    from bbv2.discovery import discover_for_query
    from bbv2.store import Store

    store = Store(":memory:")
    store.add_source("rss", "https://dup.example/feed/", "Dup")
    res = discover_for_query(
        "x", store=store,
        searcher=lambda q, n: [{"url": "https://dup.example/p", "title": "Dup"}],
        feed_finder=lambda site: [f"{site}feed/"],
        generate=lambda p, **k: '["q1"]',
    )
    assert res["candidates"] == []  # already a source → not proposed


def test_discover_for_query_names_by_site_and_strips_html():
    """Sources are named by SITE (clean domain), not an article title; web snippets
    have their Brave <strong> highlight HTML stripped (0030 UX fix)."""
    from bbv2.discovery import discover_for_query

    res = discover_for_query(
        "x",
        searcher=lambda q, n: [{
            "url": "https://www.eschoolnews.com/some-article",
            "title": "Some Long Article Headline",
            "description": "K-12 <strong>multimodal</strong> learning &amp; AI",
        }],
        feed_finder=lambda site: [f"{site}feed/"],
        generate=lambda p, **k: '["q1"]',
    )
    assert res["candidates"][0]["name"] == "eschoolnews.com"  # site, not the headline
    snip = res["web_results"][0]["snippet"]
    assert snip == "K-12 multimodal learning & AI" and "<strong>" not in snip
