from fastapi import FastAPI
from fastapi.testclient import TestClient

from bbv2.dashboard_api import add_dashboard_routes
from bbv2.store import Store


def _fake_verifier(token: str) -> dict:
    if token == "good":
        return {"email": "me@example.com", "name": "Me"}
    raise ValueError("bad token")


def _client(store: Store) -> TestClient:
    app = FastAPI()
    add_dashboard_routes(app, store, _fake_verifier)
    return TestClient(app)


AUTH = {"Authorization": "Bearer good"}


def test_auth_required():
    c = _client(Store(":memory:", check_same_thread=False))
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_me_auto_provisions_user():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    r = c.get("/api/me", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "me@example.com"
    assert body["settings"]["email_enabled"] is True
    assert body["subscriptions"] == []
    # user row was created
    assert store.get_user("me@example.com") is not None


def test_topics_create_subscribe_flag():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)  # provision user

    c.post("/api/topics", json={"slug": "crypto", "name": "Crypto"}, headers=AUTH)
    before = c.get("/api/topics", headers=AUTH).json()["topics"]
    assert before[0]["subscribed"] is False

    assert c.post("/api/topics/crypto/subscribe", headers=AUTH).status_code == 200
    after = c.get("/api/topics", headers=AUTH).json()["topics"]
    assert after[0]["subscribed"] is True

    c.delete("/api/topics/crypto/subscribe", headers=AUTH)
    assert c.get("/api/topics", headers=AUTH).json()["topics"][0]["subscribed"] is False


def test_subscribe_unknown_topic_404():
    c = _client(Store(":memory:", check_same_thread=False))
    c.get("/api/me", headers=AUTH)
    assert c.post("/api/topics/nope/subscribe", headers=AUTH).status_code == 404


def test_settings_roundtrip():
    c = _client(Store(":memory:", check_same_thread=False))
    c.get("/api/me", headers=AUTH)
    c.put("/api/settings", json={"email_enabled": False, "digest_limit": 7}, headers=AUTH)
    s = c.get("/api/settings", headers=AUTH).json()
    assert s["email_enabled"] is False and s["digest_limit"] == 7


def test_sources_list_approve_and_empty_collect():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X", status="candidate")
    store.link_topic_source(tid, sid)

    cands = c.get(
        "/api/topics/crypto/sources?status=candidate", headers=AUTH
    ).json()["sources"]
    assert [s["id"] for s in cands] == [sid]

    assert c.post(f"/api/sources/{sid}/approve", headers=AUTH).status_code == 200
    active = c.get(
        "/api/topics/crypto/sources?status=active", headers=AUTH
    ).json()["sources"]
    assert [s["id"] for s in active] == [sid]

    # collect on a topic with no active sources is network-free and returns zeros.
    store.add_topic("empty", "Empty")
    stats = c.post("/api/topics/empty/collect", headers=AUTH).json()
    assert stats["sources"] == 0 and stats["new"] == 0


def test_headlines_only_subscribed():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")
    store.upsert_item(
        {
            "item_id": "a",
            "dedupe_key": "url:a",
            "canonical_url": "https://e/a",
            "source_id": "1",
            "source_name": "S",
            "title": "Hello",
            "url": "https://e/a",
            "published_at": "2025-01-01T00:00:00+00:00",
            "fetched_at": "2025-01-01T00:00:00+00:00",
            "summary": "",
            "score": 1.0,
            "raw": {},
        }
    )
    store.map_item_topic("a", tid)
    # not subscribed yet → empty
    assert c.get("/api/headlines", headers=AUTH).json()["items"] == []
    c.post("/api/topics/crypto/subscribe", headers=AUTH)
    items = c.get("/api/headlines", headers=AUTH).json()["items"]
    assert [i["item_id"] for i in items] == ["a"]


def _story(store, tid, iid, title, when):
    store.upsert_item(
        {
            "item_id": iid,
            "dedupe_key": f"url:{iid}",
            "canonical_url": f"https://e/{iid}",
            "source_id": "1",
            "source_name": "S",
            "title": title,
            "url": f"https://e/{iid}",
            "published_at": when,
            "fetched_at": when,
            "summary": "",
            "score": 1.0,
            "raw": {},
        }
    )
    store.map_item_topic(iid, tid)


def test_stories_query_search_sort_and_feedback():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")
    _story(store, tid, "ITM1", "Bitcoin rallies", "2025-01-02T00:00:00+00:00")
    _story(store, tid, "ITM2", "Ethereum update", "2025-01-01T00:00:00+00:00")

    # not subscribed → empty
    assert c.post("/api/stories", json={}, headers=AUTH).json()["items"] == []
    c.post("/api/topics/crypto/subscribe", headers=AUTH)

    # newest first by default
    items = c.post("/api/stories", json={}, headers=AUTH).json()["items"]
    assert [i["item_id"] for i in items] == ["ITM1", "ITM2"]
    assert items[0]["feedback_vote"] is None

    # search narrows
    found = c.post("/api/stories", json={"search": "ethereum"}, headers=AUTH).json()
    assert [i["item_id"] for i in found["items"]] == ["ITM2"]

    # oldest first
    asc = c.post("/api/stories", json={"order": "asc"}, headers=AUTH).json()["items"]
    assert [i["item_id"] for i in asc] == ["ITM2", "ITM1"]

    # feedback roundtrips into the next query
    assert (
        c.post(
            "/api/stories/feedback", json={"item_id": "ITM1", "vote": 1}, headers=AUTH
        ).status_code
        == 200
    )
    voted = c.post("/api/stories", json={}, headers=AUTH).json()["items"]
    assert voted[0]["item_id"] == "ITM1" and voted[0]["feedback_vote"] == 1

    # bad vote rejected
    assert (
        c.post(
            "/api/stories/feedback", json={"item_id": "ITM1", "vote": 5}, headers=AUTH
        ).status_code
        == 400
    )

    # sources list
    assert c.get("/api/stories/sources", headers=AUTH).json()["sources"] == ["S"]
