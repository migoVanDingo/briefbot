"""Durable on-demand discovery runs + the find_sources agent tool (0030)."""

import bbv2.discovery_runner as runner
from bbv2.agent import run_chat_turn
from bbv2.store import Store


def test_discovery_run_lifecycle():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    rid = store.create_discovery_run(uid, "multimodal learning", conversation_id="c1", message_id="m1")
    assert rid.startswith("DSC")
    row = store.get_discovery_run(rid)
    assert row["status"] == "running" and row["query"] == "multimodal learning"

    store.finish_discovery_run(rid, "done", result={
        "candidates": [{"name": "EdTech", "url": "https://e/feed", "sample_headlines": ["h1"]}],
        "web_results": [{"title": "T", "url": "https://e/a", "snippet": "s"}],
        "stats": {},
    })
    res = store.discovery_result(rid)
    assert res["candidates"][0]["url"] == "https://e/feed"
    runs = store.discovery_runs_for_conversation(uid, "c1")
    assert [r["id"] for r in runs] == [rid]


def test_run_discovery_writes_preview(monkeypatch):
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    rid = store.create_discovery_run(uid, "edtech research")

    import bbv2.discovery as disc

    def fake_discover_for_query(query, **kwargs):
        return {
            "query": query,
            "candidates": [{"name": "EdSurge", "url": "https://eds/feed", "sample_headlines": ["x"]}],
            "web_results": [{"title": "A", "url": "https://eds/a", "snippet": "s"}],
            "stats": {"candidates": 1},
        }

    monkeypatch.setattr(disc, "discover_for_query", fake_discover_for_query)
    runner.run_discovery(store, rid, "edtech research")
    row = store.get_discovery_run(rid)
    assert row["status"] == "done" and row["stage"] == "ready"
    assert store.discovery_result(rid)["candidates"][0]["name"] == "EdSurge"


def test_run_discovery_marks_error_on_failure(monkeypatch):
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    rid = store.create_discovery_run(uid, "q")
    import bbv2.discovery as disc

    def boom(*a, **k):
        raise RuntimeError("brave down")

    monkeypatch.setattr(disc, "discover_for_query", boom)
    runner.run_discovery(store, rid, "q")
    assert store.get_discovery_run(rid)["status"] == "error"


def test_fail_orphaned_discovery_runs():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    store.create_discovery_run(uid, "q")
    assert store.fail_orphaned_discovery_runs() == 1
    assert store.discovery_runs_for_user(uid)[0]["status"] == "error"


def test_find_sources_tool_kicks_background_run(monkeypatch):
    """The agent's find_sources tool creates a run, emits a search_run event, and
    keeps the chat stream alive."""
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)

    submitted = {}

    def fake_submit(store, run_id, query, **kwargs):
        submitted["run_id"] = run_id
        submitted["query"] = query

    monkeypatch.setattr(runner, "submit", fake_submit)

    calls = {"n": 0}

    def fake_model(messages, tools=None, system=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": [{"type": "tool_use", "id": "t1", "name": "find_sources",
                             "input": {"query": "multimodal learning in K-12"}}],
                "stop_reason": "tool_use",
            }
        return {"content": [{"type": "text", "text": "I'm searching now."}],
                "stop_reason": "end_turn"}

    events = list(run_chat_turn(store, uid, cid, "find me journals", call_model=fake_model,
                                title_fn=lambda u: "T"))
    types = [e["type"] for e in events]
    assert "search_run" in types
    sr = next(e for e in events if e["type"] == "search_run")
    assert sr["query"] == "multimodal learning in K-12"
    assert sr["run_id"] == submitted["run_id"]
    assert types[-1] == "done"
    # a discovery run was created + linked to the conversation
    runs = store.discovery_runs_for_conversation(uid, cid)
    assert len(runs) == 1 and runs[0]["query"] == "multimodal learning in K-12"
