"""Rundown (build-once-cache), admin cadence, and onboarding endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bbv2.config as config
import bbv2.dashboard_api as dashboard_api
import bbv2.ratelimit as _ratelimit
from bbv2.brief import get_or_build_brief
from bbv2.store import Store
from bbv2.util import utc_now_iso


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    _ratelimit.limiter._hits.clear()
    yield


def _fake_verifier(token: str) -> dict:
    if token == "good":
        return {"email": "me@example.com", "name": "Me"}
    raise ValueError("bad token")


AUTH = {"Authorization": "Bearer good"}


def _client(store: Store) -> TestClient:
    app = FastAPI()
    dashboard_api.add_dashboard_routes(app, store, _fake_verifier, moderate_generate=lambda *a, **k: "{}")
    return TestClient(app)


def _seed_topic_with_item(store: Store) -> int:
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    store.upsert_item(
        {
            "item_id": "ITM1",
            "dedupe_key": "url:itm1",
            "canonical_url": "https://e/1",
            "source_id": str(sid),
            "source_name": "X",
            "title": "Bitcoin rallies",
            "url": "https://e/1",
            "published_at": utc_now_iso(),
            "fetched_at": utc_now_iso(),
            "summary": "BTC up.",
            "score": 2.0,
            "raw": {},
        }
    )
    store.map_item_topic("ITM1", tid)
    return tid


def test_get_or_build_brief_builds_once_then_caches():
    store = Store(":memory:")
    _seed_topic_with_item(store)
    calls = {"n": 0}

    def gen(*a, **k):
        calls["n"] += 1
        return '{"title": "Crypto Today", "summary": "BTC up."}'

    first = get_or_build_brief(store, "crypto", generate=gen)
    second = get_or_build_brief(store, "crypto", generate=gen)
    assert first["title"] == "Crypto Today"
    assert second["title"] == "Crypto Today"
    assert calls["n"] == 1  # second visit reused the cache (shared rundown)


def test_rundown_endpoint_shared(monkeypatch):
    store = Store(":memory:", check_same_thread=False)
    _seed_topic_with_item(store)
    monkeypatch.setattr(
        dashboard_api.usage,
        "metered_generate",
        lambda *a, **k: (lambda *aa, **kk: '{"title": "Crypto Today", "summary": "BTC up."}'),
    )
    c = _client(store)
    r = c.post("/api/topics/crypto/rundown", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["rundown"]["title"] == "Crypto Today"


def test_onboarding_flow():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    assert c.get("/api/me", headers=AUTH).json()["onboarded"] is False
    assert c.post("/api/me/onboarded", headers=AUTH).status_code == 200
    assert c.get("/api/me", headers=AUTH).json()["onboarded"] is True


def test_admin_cadence_endpoints(monkeypatch):
    monkeypatch.setattr(config, "admin_emails", lambda: {"me@example.com"})
    store = Store(":memory:", check_same_thread=False)
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    c = _client(store)

    assert c.patch(
        "/api/topics/crypto/cadence",
        json={"discover_interval_min": 10080, "collect_interval_min": 60},
        headers=AUTH,
    ).status_code == 200
    assert c.patch(
        f"/api/sources/{sid}/cadence", json={"collect_interval_min": 60}, headers=AUTH
    ).status_code == 200

    t = store.get_topic("crypto")
    assert t["discover_interval_min"] == 10080 and t["collect_interval_min"] == 60
    assert store.sources_for_scheduler()[0]["collect_interval_min"] == 60


def test_cadence_requires_admin():
    store = Store(":memory:", check_same_thread=False)
    store.add_topic("crypto", "Crypto")
    c = _client(store)
    # default user is not admin → 403
    assert c.patch(
        "/api/topics/crypto/cadence", json={"collect_interval_min": 60}, headers=AUTH
    ).status_code == 403
