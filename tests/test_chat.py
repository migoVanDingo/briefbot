from bbv2.agent import GREETING, _context_block, execute_tool, run_chat_turn
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
    # First-ever turn persists the canned greeting as the conversation's first
    # message, so it stays in the thread (live + on reload).
    assert [m["role"] for m in msgs] == ["assistant", "user", "assistant"]
    assert msgs[0]["content"] == GREETING
    assert msgs[1]["content"] == "hello"
    assert msgs[2]["content"] == "Hi there!"
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


def test_create_topic_tool_streams_stages_and_subscribes(monkeypatch):
    import bbv2.provision as provision

    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)

    def fake_provision(store, slug, **kwargs):
        yield {"type": "stage", "stage": "discovering"}
        yield {"type": "stage", "stage": "collecting"}
        yield {"type": "stage", "stage": "ready", "sources": 3, "items": 12, "dropped": 1}

    monkeypatch.setattr(provision, "provision_topic", fake_provision)

    calls = {"n": 0}

    def fake_model(messages, tools=None, system=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "create_topic",
                        "input": {"name": "Crypto", "description": "crypto markets"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        return {"content": [{"type": "text", "text": "All set!"}], "stop_reason": "end_turn"}

    events = list(
        run_chat_turn(
            store,
            uid,
            cid,
            "make a crypto topic",
            call_model=fake_model,
            title_fn=lambda u: "t",
            moderate_generate=lambda *a, **k: '{"allowed": true, "category": "ok", "reason": "ok"}',
        )
    )

    stages = [e["stage"] for e in events if e["type"] == "topic_stage"]
    assert stages == ["discovering", "collecting", "ready"]
    end = next(e for e in events if e["type"] == "tool_end" and e["name"] == "create_topic")
    assert "3 sources" in end["summary"]
    # Topic created and the user auto-subscribed.
    assert store.get_topic("crypto") is not None
    assert "crypto" in [t["slug"] for t in store.user_subscriptions(uid)]


def test_first_message_seeds_greeting_in_context():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid = store.create_conversation(uid)
    captured = {}

    def fake_model(messages, tools=None, system=None):
        captured["messages"] = messages
        return {"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"}

    list(run_chat_turn(store, uid, cid, "hello", call_model=fake_model, title_fn=lambda u: "t"))
    assert captured["messages"][0] == {"role": "assistant", "content": GREETING}
    assert captured["messages"][1]["role"] == "user"


def test_no_greeting_on_second_conversation():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    cid1 = store.create_conversation(uid)
    store.append_message(cid1, uid, "user", "x")
    store.append_message(cid1, uid, "assistant", "y")
    cid2 = store.create_conversation(uid)  # their second conversation
    captured = {}

    def fake_model(messages, tools=None, system=None):
        captured["messages"] = messages
        return {"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"}

    list(run_chat_turn(store, uid, cid2, "hello", call_model=fake_model, title_fn=lambda u: "t"))
    assert captured["messages"][0]["role"] == "user"  # no greeting seeded


def test_context_block_reflects_subscriptions_and_budget():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    store.add_topic("tech", "Tech")  # available, not subscribed

    # No subscriptions yet.
    block = _context_block(store, uid)
    assert "NONE yet" in block
    assert "Tech" in block  # offered as an available topic
    assert "Token budget today" in block

    # After subscribing, it shows under subscriptions and drops from "available".
    tid = store.add_topic("crypto", "Crypto")
    store.subscribe(uid, tid)
    block2 = _context_block(store, uid)
    assert "Subscriptions (1): Crypto" in block2


def test_subscribe_topic_tool():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    store.add_topic("crypto", "Crypto")

    res, summary = execute_tool(store, uid, "subscribe_topic", {"name": "Crypto"}, lambda *a, **k: "")
    assert res["subscribed"] is True
    assert "crypto" in [t["slug"] for t in store.user_subscriptions(uid)]

    missing, _ = execute_tool(store, uid, "subscribe_topic", {"name": "nope"}, lambda *a, **k: "")
    assert "error" in missing


def test_create_topic_events_carry_name(monkeypatch):
    """topic_stage events label each pipeline so the chat can show one run per
    topic (sports → crypto → world news)."""
    import bbv2.provision as provision
    from bbv2.agent import _create_topic_events

    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")

    def fake_provision(store, slug, **kwargs):
        yield {"type": "stage", "stage": "discovering"}
        yield {"type": "stage", "stage": "ready", "sources": 1, "items": 1, "dropped": 0}

    monkeypatch.setattr(provision, "provision_topic", fake_provision)
    allow = lambda *a, **k: '{"allowed": true, "category": "ok", "reason": "ok"}'

    events = []
    gen = _create_topic_events(
        store, uid, {"name": "World News"}, moderate_generate=allow, review_generate=None
    )
    try:
        while True:
            events.append(next(gen))
    except StopIteration:
        pass
    stages = [e for e in events if e["type"] == "topic_stage"]
    assert stages
    assert all(e["name"] == "World News" and e["slug"] == "world-news" for e in stages)


def test_brief_on_provision_only_during_setup_window(monkeypatch):
    import bbv2.provision as provision
    from bbv2.agent import _create_topic_events

    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    captured = []
    results = []

    def fake_provision(store, slug, **kwargs):
        captured.append(kwargs.get("brief_generate"))
        yield {"type": "stage", "stage": "ready", "sources": 1, "items": 1, "dropped": 0}

    monkeypatch.setattr(provision, "provision_topic", fake_provision)
    allow = lambda *a, **k: '{"allowed": true, "category": "ok", "reason": "ok"}'

    def run(name):
        gen = _create_topic_events(store, uid, {"name": name}, moderate_generate=allow, review_generate=None)
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            results.append(stop.value[0])

    # Fresh account → still in the setup window → every topic builds the brief.
    run("Crypto")
    run("Tech")
    assert captured[0] is not None and captured[1] is not None
    assert results[0]["headline_ready"] is True

    # Age the account past the window → new topics skip the brief (defer to nightly).
    store.conn.execute("UPDATE users SET created_at = ? WHERE id = ?", ("2020-01-01T00:00:00+00:00", uid))
    store.conn.commit()
    run("Space")
    assert captured[2] is None
    assert results[2]["headline_ready"] is False


def test_me_marks_onboarded_when_returning_with_subscriptions():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import bbv2.dashboard_api as dashboard_api

    def verifier(token):
        return {"email": "me@example.com", "name": "Me"}

    store = Store(":memory:", check_same_thread=False)
    app = FastAPI()
    dashboard_api.add_dashboard_routes(app, store, verifier)
    c = TestClient(app)
    auth = {"Authorization": "Bearer good"}

    # First session: no subscriptions → stays not onboarded.
    assert c.get("/api/me", headers=auth).json()["onboarded"] is False
    uid = store.get_user("me@example.com")["id"]
    tid = store.add_topic("crypto", "Crypto")
    store.subscribe(uid, tid)
    # Next session /me sees subscriptions → marks onboarded.
    assert c.get("/api/me", headers=auth).json()["onboarded"] is True
    assert store.is_onboarded(uid)


def test_execute_tool_favorites_via_query():
    store = Store(":memory:")
    uid = _seed(store)
    res, _ = execute_tool(store, uid, "add_favorite", {"query": "bitcoin"}, lambda *a, **k: "")
    assert res["saved"] is True
    listed, summary = execute_tool(store, uid, "list_favorites", {}, lambda *a, **k: "")
    assert [i["title"] for i in listed["items"]] == ["Bitcoin rallies on ETF approval"]
