"""Consumer-token revoke + scope behavior."""

from fastapi.testclient import TestClient

from bbv2.api import create_app
from bbv2.store import Store


def test_revoke_invalidates_token():
    store = Store(":memory:")
    store.add_topic("crypto", "Crypto")
    token = store.create_token("trader", ["crypto"])
    assert store.get_token(token) is not None

    n = store.revoke_token("trader")  # by label
    assert n == 1
    assert store.get_token(token) is None  # revoked → auth lookup fails

    listed = store.list_tokens()
    assert listed[0]["revoked_at"] is not None


def test_revoked_token_rejected_by_consumer_api():
    # check_same_thread=False: TestClient runs endpoints on a worker thread.
    store = Store(":memory:", check_same_thread=False)
    store.add_topic("crypto", "Crypto")
    token = store.create_token("trader", ["crypto"])
    client = TestClient(create_app(store))
    auth = {"Authorization": f"Bearer {token}"}

    assert client.get("/topics", headers=auth).status_code == 200
    store.revoke_token(token)  # by full token value
    assert client.get("/topics", headers=auth).status_code == 401


def test_revoke_unknown_returns_zero():
    store = Store(":memory:")
    assert store.revoke_token("nope") == 0
