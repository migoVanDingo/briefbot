from fastapi.testclient import TestClient

from bbv2.api import create_app
from bbv2.store import Store


def _item(item_id: str, fetched_at: str, title: str) -> dict:
    return {
        "item_id": item_id,
        "dedupe_key": f"url:{item_id}",
        "canonical_url": f"https://example.com/{item_id}",
        "source_id": "1",
        "source_name": "Example",
        "title": title,
        "url": f"https://example.com/{item_id}",
        "published_at": fetched_at,
        "fetched_at": fetched_at,
        "summary": "",
        "score": 1.0,
        "raw": {},
    }


def _seed():
    # check_same_thread=False: TestClient runs endpoints on a worker thread.
    store = Store(":memory:", check_same_thread=False)
    tid = store.add_topic("crypto", "Crypto", "")
    store.add_topic("politics", "Politics", "")
    store.upsert_item(_item("a", "2025-01-01T00:00:00+00:00", "First"))
    store.upsert_item(_item("b", "2025-01-02T00:00:00+00:00", "Second"))
    store.map_item_topic("a", tid)
    store.map_item_topic("b", tid)
    token = store.create_token("trader", ["crypto"])  # scoped to crypto only
    return store, token


def _client():
    store, token = _seed()
    return TestClient(create_app(store)), token


def test_health_is_open():
    client, _ = _client()
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_or_invalid_token_is_401():
    client, _ = _client()
    assert client.get("/consumer/topics").status_code == 401
    assert client.get("/consumer/topics", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_topics_are_scoped_to_token():
    client, token = _client()
    r = client.get("/consumer/topics", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    slugs = [t["slug"] for t in r.json()["topics"]]
    assert slugs == ["crypto"]  # not 'politics'


def test_items_in_scope_and_out_of_scope():
    client, token = _client()
    h = {"Authorization": f"Bearer {token}"}

    ok = client.get("/consumer/items", params={"topic": "crypto"}, headers=h)
    assert ok.status_code == 200
    assert ok.json()["count"] == 2

    denied = client.get("/consumer/items", params={"topic": "politics"}, headers=h)
    assert denied.status_code == 403


def test_since_filters_and_orders_ascending():
    client, token = _client()
    h = {"Authorization": f"Bearer {token}"}
    r = client.get(
        "/consumer/items",
        params={"topic": "crypto", "since": "2025-01-01T00:00:00+00:00"},
        headers=h,
    )
    body = r.json()
    assert [i["item_id"] for i in body["items"]] == ["b"]  # only newer than 'since'
    assert body["next_since"] == "2025-01-02T00:00:00+00:00"
