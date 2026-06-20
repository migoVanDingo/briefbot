from bbv2.agent import execute_tool, run_chat_turn
from bbv2.store import Store


def _seed(store: Store) -> int:
    uid = store.add_user("Me", "me@example.com")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    store.subscribe(uid, tid)
    store.upsert_item(
        {
            "item_id": "ITM1",
            "dedupe_key": "url:itm1",
            "canonical_url": "https://e/1",
            "source_id": str(sid),
            "source_name": "X",
            "title": "Bitcoin rallies on ETF approval",
            "url": "https://e/1",
            "published_at": "2025-01-08T08:00:00+00:00",
            "fetched_at": "2025-01-08T08:00:00+00:00",
            "summary": "BTC up.",
            "score": 2.0,
            "raw": {},
        }
    )
    store.map_item_topic("ITM1", tid)
    return uid


def test_conversation_message_roundtrip():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)
    assert cid.startswith("CON")
    store.append_message(cid, uid, "user", "hi")
    store.append_message(cid, uid, "assistant", "hello", tool_calls=[{"name": "x", "summary": "y"}])
    msgs = store.get_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert [m["seq"] for m in msgs] == [1, 2]
    assert store.list_conversations(uid)[0]["message_count"] == 2


def test_run_chat_turn_text_only():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)

    def fake_model(messages, tools=None, system=None):
        return {"content": [{"type": "text", "text": "Hi there!"}], "stop_reason": "end_turn"}

    events = list(
        run_chat_turn(
            store, uid, cid, "hello", call_model=fake_model, title_fn=lambda u: "Greeting"
        )
    )
    types = [e["type"] for e in events]
    assert "token" in types and types[-1] == "done"
    assert any(e.get("text") == "Hi there!" for e in events if e["type"] == "token")
    assert any(e["type"] == "title" and e["title"] == "Greeting" for e in events)

    msgs = store.get_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "Hi there!"
    assert store.get_conversation(uid, cid)["title"] == "Greeting"


def test_run_chat_turn_runs_a_tool():
    store = Store(":memory:")
    uid = _seed(store)
    cid = store.create_conversation(uid)
    calls = {"n": 0}

    def fake_model(messages, tools=None, system=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "search_stories",
                        "input": {"query": "bitcoin"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        return {"content": [{"type": "text", "text": "Found it."}], "stop_reason": "end_turn"}

    events = list(
        run_chat_turn(store, uid, cid, "find bitcoin", call_model=fake_model, title_fn=lambda u: "t")
    )
    types = [e["type"] for e in events]
    assert "tool_start" in types and "tool_end" in types
    end = next(e for e in events if e["type"] == "tool_end")
    assert "stories" in end["summary"]
    assert store.get_messages(cid)[-1]["content"] == "Found it."


def test_execute_tool_favorites_via_query():
    store = Store(":memory:")
    uid = _seed(store)
    res, _ = execute_tool(store, uid, "add_favorite", {"query": "bitcoin"}, lambda *a, **k: "")
    assert res["saved"] is True
    listed, summary = execute_tool(store, uid, "list_favorites", {}, lambda *a, **k: "")
    assert [i["title"] for i in listed["items"]] == ["Bitcoin rallies on ETF approval"]
