"""Inbound rate limiting on the dashboard + consumer APIs."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bbv2.config as config
import bbv2.ratelimit as _ratelimit
from bbv2.api import create_app
from bbv2.dashboard_api import add_dashboard_routes
from bbv2.store import Store


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    _ratelimit.limiter._hits.clear()
    yield


def _fake_verifier(token: str) -> dict:
    if token == "good":
        return {"email": "me@example.com", "name": "Me"}
    raise ValueError("bad token")


AUTH = {"Authorization": "Bearer good"}


def test_dashboard_general_limit_blocks(monkeypatch):
    monkeypatch.setattr(config, "ratelimit_default", lambda: (3, 60.0))
    store = Store(":memory:", check_same_thread=False)
    app = FastAPI()
    add_dashboard_routes(app, store, _fake_verifier)
    c = TestClient(app)

    # 3 allowed within the window, the 4th is throttled (any /api/* route counts).
    for _ in range(3):
        assert c.get("/api/me", headers=AUTH).status_code == 200
    r = c.get("/api/me", headers=AUTH)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_consumer_token_limit_blocks(monkeypatch):
    monkeypatch.setattr(config, "ratelimit_consumer", lambda: (2, 60.0))
    store = Store(":memory:", check_same_thread=False)
    store.add_topic("crypto", "Crypto", "")
    token = store.create_token("trader", ["crypto"])
    c = TestClient(create_app(store))
    auth = {"Authorization": f"Bearer {token}"}

    assert c.get("/topics", headers=auth).status_code == 200
    assert c.get("/topics", headers=auth).status_code == 200
    assert c.get("/topics", headers=auth).status_code == 429


def test_consumer_health_is_exempt(monkeypatch):
    monkeypatch.setattr(config, "ratelimit_consumer", lambda: (1, 60.0))
    store = Store(":memory:", check_same_thread=False)
    c = TestClient(create_app(store))
    # Health never authenticates, so it never hits the per-token limiter.
    for _ in range(5):
        assert c.get("/health").status_code == 200
