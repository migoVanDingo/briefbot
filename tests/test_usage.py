"""Token-usage accounting + two-tier budget enforcement."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bbv2.ratelimit as _ratelimit
from bbv2 import usage
from bbv2.dashboard_api import add_dashboard_routes
from bbv2.store import Store


def _fake_verifier(token: str) -> dict:
    if token == "good":
        return {"email": "me@example.com", "name": "Me"}
    raise ValueError("bad token")


def _allow_gen(*a, **k):
    return '{"allowed": true, "category": "ok", "reason": "ok"}'


def _client(store: Store) -> TestClient:
    app = FastAPI()
    add_dashboard_routes(app, store, _fake_verifier, moderate_generate=_allow_gen)
    return TestClient(app)


AUTH = {"Authorization": "Bearer good"}


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    _ratelimit.limiter._hits.clear()
    yield


def _uid(store: Store) -> int:
    return store.add_user("Me", "me@example.com")


def test_record_and_window_aggregates():
    store = Store(":memory:", check_same_thread=False)
    uid = _uid(store)
    store.record_usage(uid, "chat", "haiku", 100, 50)
    store.record_usage(uid, "chat", "haiku", 200, 25)
    store.record_usage(uid, "chat-turn", None, 0, 0, interaction=1)

    agg = store.usage_window(uid, "1970-01-01T00:00:00+00:00")
    assert agg["total_tokens"] == 375
    assert agg["interactions"] == 1


def test_budget_blocks_at_single_limit(monkeypatch):
    store = Store(":memory:", check_same_thread=False)
    uid = _uid(store)
    monkeypatch.setattr(
        usage.config,
        "token_budget",
        lambda: {"enabled": True, "window_s": 86400.0, "limit": 100_000},
    )

    assert usage.budget_status(store, uid)["allowed"]

    store.record_usage(uid, "chat", "haiku", 60_000, 0)
    assert usage.budget_status(store, uid)["allowed"]  # still under 100k

    store.record_usage(uid, "provision", "haiku", 50_000, 0)  # user-initiated counts
    st = usage.budget_status(store, uid)
    assert not st["allowed"]
    assert "resets in" in st["message"]


def test_system_bucket_not_charged_to_user(monkeypatch):
    store = Store(":memory:", check_same_thread=False)
    uid = _uid(store)
    monkeypatch.setattr(
        usage.config,
        "token_budget",
        lambda: {"enabled": True, "window_s": 86400.0, "limit": 100_000},
    )
    # A huge system-bucket spend must not touch the user's budget.
    store.record_usage(usage.SYSTEM_USER_ID, "nightly", "haiku", 5_000_000, 0)
    st = usage.budget_status(store, uid)
    assert st["used"] == 0
    assert st["allowed"]


def test_budget_disabled_never_blocks(monkeypatch):
    store = Store(":memory:", check_same_thread=False)
    uid = _uid(store)
    monkeypatch.setattr(
        usage.config,
        "token_budget",
        lambda: {"enabled": False, "window_s": 86400.0, "limit": 1},
    )
    store.record_usage(uid, "chat", "haiku", 999_999, 0)
    assert usage.budget_status(store, uid)["allowed"]


def test_usage_endpoint_reports_counts(monkeypatch):
    # Pin the budget so the assertion is independent of any .env overrides.
    monkeypatch.setattr(
        usage.config,
        "token_budget",
        lambda: {"enabled": True, "window_s": 86400.0, "limit": 100_000},
    )
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)  # provision the user
    uid = store.get_user("me@example.com")["id"]
    store.record_usage(uid, "chat", "haiku", 1_000, 500)
    store.record_usage(uid, "chat-turn", None, 0, 0, interaction=1)

    body = c.get("/api/usage", headers=AUTH).json()
    assert body["tokens_used"] == 1_500
    assert body["interactions"] == 1
    assert body["limit"] == 100_000
    assert body["blocked"] is False


def test_create_topic_blocked_over_limit(monkeypatch):
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    uid = store.get_user("me@example.com")["id"]
    monkeypatch.setattr(
        usage.config,
        "token_budget",
        lambda: {"enabled": True, "window_s": 86400.0, "limit": 100_000},
    )
    store.record_usage(uid, "chat", "haiku", 120_000, 0)

    r = c.post("/api/topics", json={"slug": "crypto", "name": "Crypto"}, headers=AUTH)
    assert r.status_code == 429
    assert "limit" in r.json()["detail"].lower()
