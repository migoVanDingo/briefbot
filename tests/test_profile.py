"""User profile + avatar + identicon (0028)."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bbv2.ratelimit as _ratelimit
from bbv2.dashboard_api import add_dashboard_routes
from bbv2.identicon import identicon_svg
from bbv2.store import Store


def _fake_verifier(token: str) -> dict:
    return {"email": "me@example.com", "name": "Me", "email_verified": True}


def _allow_gen(*a, **k):
    return '{"allowed": true, "category": "ok", "reason": "ok"}'


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    _ratelimit.limiter._hits.clear()
    yield


def _client(store: Store) -> TestClient:
    app = FastAPI()
    add_dashboard_routes(app, store, _fake_verifier, moderate_generate=_allow_gen)
    c = TestClient(app)
    assert c.post("/api/auth/exchange", headers={"Authorization": "Bearer good"}).status_code == 200
    return c


# ---- identicon ----

def test_identicon_deterministic_and_symmetric():
    a = identicon_svg("me@example.com")
    b = identicon_svg("me@example.com")
    assert a == b  # deterministic
    assert identicon_svg("other@example.com") != a  # varies by seed
    assert a.startswith("<svg") and a.rstrip().endswith("</svg>")
    assert "<rect" in a  # has cells


# ---- avatar claim idempotency ----

def test_claim_avatar_idempotent_while_pending():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    assert store.claim_avatar(uid, "a cat") is True  # first claim wins
    assert store.claim_avatar(uid, "a dog") is False  # already pending → no double-fire
    store.set_avatar(uid, "/tmp/x.jpg", "ready")
    assert store.claim_avatar(uid, "a bird") is True  # can re-generate once settled


# ---- profile stats ----

def test_user_profile_stats_windows():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    tid = store.add_topic("ai", "AI")
    store.subscribe(uid, tid)
    store.record_usage(uid, "chat", "claude-haiku", 1000, 500)
    stats = store.user_profile_stats(uid, "2030-01-01T00:00:00+00:00")
    assert [s["slug"] for s in stats["subscriptions"]] == ["ai"]
    for window in ("day", "week", "month", "year", "all"):
        assert window in stats["usage"]
        assert "tokens" in stats["usage"][window] and "cost" in stats["usage"][window]
    assert stats["usage"]["all"]["tokens"] == 1500
    assert stats["usage"]["all"]["cost"] > 0
    # the spend is "today" relative to a far-future now → not in the day window
    assert stats["usage"]["day"]["tokens"] == 0


# ---- routes ----

def test_profile_route_and_avatar():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    r = c.get("/api/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "me@example.com"
    assert body["user"]["avatar_status"] == "none"
    assert "usage" in body and "all" in body["usage"]

    # default avatar → identicon SVG
    uid = body["user"]["id"]
    img = c.get(f"/api/avatar/{uid}")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/svg+xml")
    assert img.text.startswith("<svg")


def test_avatar_generate_requires_prompt():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    assert c.post("/api/profile/avatar", json={}).status_code == 400


def test_reset_avatar():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    uid = c.get("/api/profile").json()["user"]["id"]
    store.set_avatar(uid, "/tmp/x.jpg", "ready")
    assert c.delete("/api/profile/avatar").status_code == 200
    assert store.get_user_by_id(uid)["avatar_status"] == "none"


# ---- code-review fixes ----

def test_avatar_409_while_pending_does_not_burn_rate_limit(monkeypatch):
    """A repeat tap while one avatar is generating must 409 WITHOUT consuming a
    rate-limit slot — else a handful of retries locks the user out for an hour."""
    import bbv2.config as cfg

    monkeypatch.setattr(cfg, "avatars_enabled", lambda: True)
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    uid = c.get("/api/profile").json()["user"]["id"]
    store.claim_avatar(uid, "a cat")  # put it in 'pending'
    # Far more attempts than the 10/hr limiter cap — all must be 409, never 429.
    codes = {c.post("/api/profile/avatar", json={"prompt": "x"}).status_code for _ in range(15)}
    assert codes == {409}


def test_reset_orphaned_image_jobs():
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    tid = store.add_topic("ai", "AI")
    store.upsert_brief({
        "id": "BRF1", "topic_id": tid, "date": "2030-06-01", "title": "t",
        "summary": "s", "trending": [], "sources": [], "model": "x",
    })
    store.claim_avatar(uid, "x")               # avatar → pending
    store.claim_brief_image(tid, "2030-06-01")  # per-day brief image → pending
    n = store.reset_orphaned_image_jobs()
    assert n == 2
    assert store.get_user_by_id(uid)["avatar_status"] == "none"
    assert store.get_brief(tid, "2030-06-01")["image_status"] == "none"
    # now re-claimable (the stuck-forever case is fixed)
    assert store.claim_avatar(uid, "y") is True
    assert store.claim_brief_image(tid, "2030-06-01") is True
