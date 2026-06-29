"""Agent is conversant about discovered sources: read_source, summarize_article(url),
and the discovery context injection (0031)."""

import bbv2.discovery as disc
from bbv2.agent import _context_block, execute_tool
from bbv2.store import Store


def _seed_search(store, uid, cid, *, query="firearms blogs", committed=False):
    rid = store.create_discovery_run(uid, query, conversation_id=cid)
    store.finish_discovery_run(rid, "done", result={
        "candidates": [
            {"name": "smokinggun.org", "url": "https://smokinggun.org/feed",
             "sample_articles": [{"title": "ATF Director appeals to gun groups", "url": "https://smokinggun.org/a"},
                                 {"title": "Father's Day: Get Dad a Gun", "url": "https://smokinggun.org/b"}]},
            {"name": "thereload.com", "url": "https://thereload.com/feed",
             "sample_articles": [{"title": "SCOTUS gun ruling analysis", "url": "https://thereload.com/x"}]},
        ],
        "web_results": [], "stats": {},
    })
    if committed:
        store.mark_discovery_committed(rid)
    return rid


# ---- read_source ----

def test_read_source_resolves_domain_from_latest_search(monkeypatch):
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)
    _seed_search(store, uid, cid)

    captured = {}

    def fake_fetch(store_, feed_url, limit=15):
        captured["url"] = feed_url
        return [{"title": "Recent ATF story", "url": "https://smokinggun.org/r1"}]

    monkeypatch.setattr(disc, "fetch_feed_articles", fake_fetch)
    result, summary = execute_tool(
        store, uid, "read_source", {"source": "smokinggun.org"}, lambda *a, **k: "",
        conversation_id=cid,
    )
    assert captured["url"] == "https://smokinggun.org/feed"  # domain → that feed
    assert result["articles"][0]["title"] == "Recent ATF story"
    assert "1 articles" in summary


def test_read_source_accepts_literal_url(monkeypatch):
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    monkeypatch.setattr(disc, "fetch_feed_articles", lambda s, u, limit=15: [{"title": "t", "url": "u"}])
    result, _ = execute_tool(
        store, uid, "read_source", {"source": "https://x.example/feed"}, lambda *a, **k: "",
    )
    assert result["feed_url"] == "https://x.example/feed"


def test_read_source_unknown_source():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    result, summary = execute_tool(
        store, uid, "read_source", {"source": "nowhere.invalid"}, lambda *a, **k: "",
    )
    assert "couldn't find a source" in result["error"] and summary == "no source"


# ---- summarize_article(url=…) ----

def test_summarize_article_by_url(monkeypatch):
    import bbv2.agent as agent_mod

    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    monkeypatch.setattr(agent_mod, "_fetch_text", lambda url: "Full article body about the ATF.")
    result, summary = execute_tool(
        store, uid, "summarize_article",
        {"url": "https://smokinggun.org/a", "title": "ATF Director"},
        lambda prompt, **k: "A concise grounded summary.",
    )
    assert result["summary"] == "A concise grounded summary."
    assert result["url"] == "https://smokinggun.org/a" and result["title"] == "ATF Director"
    assert summary == "summarized"


def test_summarize_article_url_no_content(monkeypatch):
    import bbv2.agent as agent_mod

    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    monkeypatch.setattr(agent_mod, "_fetch_text", lambda url: "")
    result, _ = execute_tool(
        store, uid, "summarize_article", {"url": "https://x/y"}, lambda *a, **k: "x",
    )
    assert result["error"] == "no readable content"


# ---- context injection ----

def test_context_block_includes_recent_search():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)
    _seed_search(store, uid, cid, query="firearms blogs")
    ctx = _context_block(store, uid, cid)
    assert "firearms blogs" in ctx
    assert "smokinggun.org" in ctx and "thereload.com" in ctx
    assert "ATF Director appeals to gun groups" in ctx
    assert "read_source" in ctx  # nudges the agent to the right tools


def test_context_block_drops_committed_search():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)
    _seed_search(store, uid, cid, committed=True)
    assert "smokinggun.org" not in _context_block(store, uid, cid)


def test_context_block_without_conversation():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    # no conversation id → no discovery context, no crash
    assert "Recent web search" not in _context_block(store, uid, None)
