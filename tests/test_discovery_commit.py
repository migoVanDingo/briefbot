"""Placement (embedding evidence) + commit of discovered sources (0030)."""

import bbv2.discovery_commit as commit_mod
from bbv2.discovery_commit import commit_discovery, decide_targets
from bbv2.store import Store
from tests.test_embeddings import fake_embedder  # reuse the bag-of-words embedder


def _seed_run(store, query, candidates):
    uid = store.add_user("Me", "me@example.com")
    rid = store.create_discovery_run(uid, query)
    store.finish_discovery_run(rid, "done", result={
        "candidates": candidates, "web_results": [], "stats": {},
    })
    return uid, rid


def test_decide_targets_thresholds(monkeypatch):
    monkeypatch.setenv("BBV2_PLACEMENT_MIN", "0.3")
    monkeypatch.setenv("BBV2_PLACEMENT_MULTI", "0.6")
    # best clears the floor; a second topic clears the multi bar → both targeted
    mode, targets = decide_targets([
        {"slug": "edu", "name": "Edu", "score": 0.7},
        {"slug": "ai", "name": "AI", "score": 0.65},
        {"slug": "guns", "name": "Guns", "score": 0.1},
    ])
    assert mode == "existing"
    assert [t["slug"] for t in targets] == ["edu", "ai"]
    # nothing clears the floor → new topic
    assert decide_targets([{"slug": "x", "name": "X", "score": 0.1}]) == ("new", [])
    assert decide_targets([]) == ("new", [])


def test_commit_routes_to_existing_topic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BBV2_PLACEMENT_MIN", "0.2")
    monkeypatch.setattr(commit_mod, "_pool", lambda: _SyncPool())  # run collect inline
    import bbv2.topic_index as ti

    store = Store(":memory:", check_same_thread=False)
    tid_edu = store.add_topic("edu", "Educational Research", "learning and student education")
    store.add_topic("firearms", "Firearms", "gun and firearm news")
    ti.ensure_meta_embeddings(store, embedder=fake_embedder)

    uid, rid = _seed_run(store, "multimodal learning for students education", [
        {"name": "EdSurge", "url": "https://eds/feed", "sample_headlines": ["x"]},
    ])
    decision = commit_discovery(
        store, rid, uid, embedder=fake_embedder, submit_collect=False,
    )
    assert decision["mode"] == "existing"
    assert decision["topics"][0]["slug"] == "edu"
    assert decision["sources_added"] == 1
    # source attached to edu + user subscribed
    assert "https://eds/feed" in {s["url"] for s in store.active_sources("edu")}
    assert tid_edu in [t["id"] for t in store.user_subscriptions(uid)]
    # run marked committed
    assert store.get_discovery_run(rid)["committed_at"] is not None


def test_commit_creates_new_topic_when_no_match(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BBV2_PLACEMENT_MIN", "0.95")  # nothing will clear this
    monkeypatch.setattr(commit_mod, "_pool", lambda: _SyncPool())
    import bbv2.topic_index as ti

    store = Store(":memory:", check_same_thread=False)
    store.add_topic("firearms", "Firearms", "gun and firearm news")
    ti.ensure_meta_embeddings(store, embedder=fake_embedder)

    uid, rid = _seed_run(store, "quantum computing breakthroughs", [
        {"name": "Quanta", "url": "https://q/feed", "sample_headlines": []},
    ])
    # nothing clears the 0.95 floor → new topic created from the query
    decision = commit_discovery(
        store, rid, uid, embedder=fake_embedder,
        moderate_generate=lambda *a, **k: '{"allowed": true, "category": "ok", "reason": "ok"}',
        submit_collect=False,
    )
    assert decision["created_new"] is True
    slug = decision["topics"][0]["slug"]
    assert store.get_topic(slug) is not None
    assert "https://q/feed" in {s["url"] for s in store.active_sources(slug)}


def test_commit_rejects_foreign_run():
    store = Store(":memory:")
    uid, rid = _seed_run(store, "q", [{"name": "n", "url": "https://x/feed"}])
    other = store.add_user("Other", "other@example.com")
    assert commit_discovery(store, rid, other, submit_collect=False)["error"] == "unknown search"


class _SyncPool:
    def submit(self, fn, *a, **k):
        return fn(*a, **k)


def test_conversational_commit_path(monkeypatch):
    """A user 'yes, add them' → agent commit_sources commits the latest run."""
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BBV2_PLACEMENT_MIN", "0.2")
    monkeypatch.setattr(commit_mod, "_pool", lambda: _SyncPool())
    import bbv2.topic_index as ti
    from bbv2.agent import run_chat_turn

    store = Store(":memory:", check_same_thread=False)
    store.add_topic("edu", "Educational Research", "learning and student education")
    ti.ensure_meta_embeddings(store, embedder=fake_embedder)
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)
    rid = store.create_discovery_run(uid, "multimodal learning students education",
                                     conversation_id=cid)
    store.finish_discovery_run(rid, "done", result={
        "candidates": [{"name": "EdSurge", "url": "https://eds/feed", "sample_headlines": []}],
        "web_results": [], "stats": {},
    })
    # commit uses the default metered embedder (real OpenAI) — inject the fake.
    import bbv2.discovery_commit as dc
    monkeypatch.setattr(dc, "metered_embedder", lambda store: fake_embedder)

    def fake_model(messages, tools=None, system=None):
        if not any(m.get("role") == "user" and isinstance(m.get("content"), list) for m in messages):
            return {"content": [{"type": "tool_use", "id": "t1", "name": "commit_sources",
                                 "input": {}}], "stop_reason": "tool_use"}
        return {"content": [{"type": "text", "text": "Added to Educational Research."}],
                "stop_reason": "end_turn"}

    events = list(run_chat_turn(store, uid, cid, "yes, add them", call_model=fake_model,
                                title_fn=lambda u: "T"))
    assert events[-1]["type"] == "done"
    # the run is now committed + the source is on the edu topic
    assert store.get_discovery_run(rid)["committed_at"] is not None
    assert "https://eds/feed" in {s["url"] for s in store.active_sources("edu")}


def test_craft_topic_name_llm_and_fallback():
    from bbv2.discovery_commit import _craft_topic_name

    # LLM crafts a clean, broad name + description
    gen = lambda p, **k: '{"name": "LLM Security", "description": "Security of LLMs"}'
    name, desc = _craft_topic_name("llm security vulnerabilities attacks", gen)
    assert name == "LLM Security" and desc == "Security of LLMs"
    # no generator → heuristic fallback (title-cased query)
    n2, d2 = _craft_topic_name("quantum computing", None)
    assert n2 == "Quantum Computing"
    # LLM error → fallback, never raises
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    n3, _ = _craft_topic_name("space weather", boom)
    assert n3 == "Space Weather"


def test_commit_new_topic_uses_crafted_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BBV2_PLACEMENT_MIN", "0.95")  # force new topic
    monkeypatch.setattr(commit_mod, "_pool", lambda: _SyncPool())
    import bbv2.topic_index as ti

    store = Store(":memory:", check_same_thread=False)
    store.add_topic("firearms", "Firearms", "gun news")
    ti.ensure_meta_embeddings(store, embedder=fake_embedder)
    uid, rid = _seed_run(store, "llm security vulnerabilities attacks", [
        {"name": "thehackernews.com", "url": "https://thn/feed"},
    ])
    decision = commit_discovery(
        store, rid, uid, embedder=fake_embedder, submit_collect=False,
        name_generate=lambda p, **k: '{"name": "LLM Security", "description": "Security of LLMs"}',
        moderate_generate=lambda *a, **k: '{"allowed": true, "category": "ok", "reason": "ok"}',
    )
    assert decision["created_new"] and decision["topics"][0]["name"] == "LLM Security"
    assert store.get_topic("llm-security") is not None
