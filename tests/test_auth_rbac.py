"""Auth sessions, RBAC capabilities, and the spaces foundation (0019)."""

import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bbv2.ratelimit as _ratelimit
from bbv2 import authjwt, rbac
from bbv2.dashboard_api import add_dashboard_routes
from bbv2.store import Store


def _fake_verifier(token: str) -> dict:
    if token == "good":
        return {"email": "me@example.com", "name": "Me"}
    raise ValueError("bad token")


def _allow_gen(*a, **k):
    return '{"allowed": true, "category": "ok", "reason": "ok"}'


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    _ratelimit.limiter._hits.clear()
    yield


def _app(store: Store) -> TestClient:
    app = FastAPI()
    add_dashboard_routes(app, store, _fake_verifier, moderate_generate=_allow_gen)
    return TestClient(app)


def _login(c: TestClient, token: str = "good") -> dict:
    r = c.post("/api/auth/exchange", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


AUTH = {"Authorization": "Bearer good"}


# ---- rbac unit ----

def test_rbac_capability_resolution():
    assert rbac.has_capability(rbac.global_capabilities("owner"), "anything:at:all")
    admin = rbac.global_capabilities("admin")
    assert "sources:approve" in admin and "user:manage" not in admin
    # legacy 'human' role maps to the baseline user caps
    assert rbac.global_capabilities("human") == rbac.global_capabilities("user")
    # space membership unions in space caps
    caps = rbac.resolve_capabilities("user", space_role="editor")
    assert "space:write" in caps and "space:read" in caps


def test_access_jwt_roundtrip_and_audience():
    tok = authjwt.build_access_token(7, "SES123")
    claims = authjwt.decode_access_token(tok)
    assert claims["sub"] == "7" and claims["sid"] == "SES123"
    # wrong audience is rejected
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(
            tok, __import__("bbv2.config", fromlist=["jwt_secret"]).jwt_secret(),
            algorithms=["HS256"], issuer="bbv2", audience="someone.else",
        )
    # expired is rejected
    expired = authjwt.build_access_token(7, "SES123", now=int(time.time()) - 100, ttl_s=10)
    with pytest.raises(jwt.ExpiredSignatureError):
        authjwt.decode_access_token(expired)


# ---- exchange / session / logout ----

def test_exchange_opens_session_and_personal_space():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    uid = store.get_user("me@example.com")["id"]
    # a personal space exists with the user as owner
    spaces = c.get("/api/spaces", headers=AUTH).json()["spaces"]
    assert len(spaces) == 1
    assert spaces[0]["type"] == "personal" and spaces[0]["role"] == "owner"
    # login audited + last_login stamped
    events = [e["event"] for e in store.list_auth_events(user_id=uid)]
    assert "login" in events
    assert store.get_user_by_id(uid)["last_login_at"] is not None


def test_refresh_rotates_session_after_access_expiry():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    old_refresh = c.cookies.get("bbv2_refresh")

    # Simulate the access token expiring: drop just the access cookie.
    c.cookies.delete("bbv2_access")
    assert c.get("/api/me").status_code == 401

    # The refresh endpoint rotates and re-issues an access cookie.
    assert c.get("/api/auth/session").status_code == 200
    assert c.get("/api/me", headers=AUTH).status_code == 200
    # old refresh token is now revoked, with the rotation chain recorded
    old = store.get_session_by_refresh(old_refresh)
    assert old is None  # revoked → not active


def test_logout_revokes_session():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    assert c.get("/api/me", headers=AUTH).status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    # cookies cleared + session revoked → no longer authenticated
    assert c.get("/api/me").status_code == 401


def test_disabled_user_is_blocked():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    store.set_user_status("me@example.com", "disabled")
    # existing session is rejected (status checked every request)
    assert c.get("/api/me", headers=AUTH).status_code == 403
    # and a fresh exchange is refused
    assert c.post("/api/auth/exchange", headers=AUTH).status_code == 403


def test_revoke_sessions_forces_logout():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    uid = store.get_user("me@example.com")["id"]
    assert store.revoke_user_sessions(uid) == 1
    assert c.get("/api/me", headers=AUTH).status_code == 401


# ---- capability gating ----

def test_admin_user_management_requires_owner():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    # plain user (role 'human') can't manage users
    assert c.get("/api/auth/admin/users").status_code == 403

    # promote to owner (bootstrap path is ADMIN_EMAILS; here direct)
    store.set_user_role("me@example.com", "owner")
    assert c.get("/api/auth/admin/users").status_code == 200

    # owner can change another user's role + disable them (revoking sessions)
    bob = store.add_user("Bob", "bob@example.com")
    bob_sid, _ = store.create_session(bob)
    assert c.patch(f"/api/auth/admin/users/{bob}", json={"role": "admin"}).status_code == 200
    assert store.get_user("bob@example.com")["role"] == "admin"
    assert c.patch(f"/api/auth/admin/users/{bob}", json={"status": "disabled"}).status_code == 200
    assert store.get_user("bob@example.com")["status"] == "disabled"
    assert store.session_active(bob_sid) is False  # disabling revoked Bob's session

    # owner role itself can't be reassigned away
    me = store.get_user("me@example.com")["id"]
    assert c.patch(f"/api/auth/admin/users/{me}", json={"role": "user"}).status_code == 403
    # invalid role rejected
    assert c.patch(f"/api/auth/admin/users/{bob}", json={"role": "wizard"}).status_code == 422


def test_curation_routes_gated_by_capability():
    store = Store(":memory:", check_same_thread=False)
    c = _app(store)
    _login(c)
    store.add_topic("crypto", "Crypto")
    # plain user → 403 on curation
    assert c.post("/api/topics/crypto/discover", headers=AUTH).status_code == 403
    # admin role → allowed (has the curation caps)
    store.set_user_role("me@example.com", "admin")
    assert c.get("/api/topics/crypto/sources", headers=AUTH).status_code == 200
