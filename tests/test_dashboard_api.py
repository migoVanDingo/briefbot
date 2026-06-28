import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import bbv2.ratelimit as _ratelimit
from bbv2.dashboard_api import add_dashboard_routes
from bbv2.store import Store


def _fake_verifier(token: str) -> dict:
    if token == "good":
        return {"email": "me@example.com", "name": "Me"}
    raise ValueError("bad token")


def _allow_gen(*a, **k):  # default moderation stub → allow (no network)
    return '{"allowed": true, "category": "ok", "reason": "ok"}'


AUTH = {"Authorization": "Bearer good"}


def _client(store: Store, moderate_generate=_allow_gen, *, login: bool = True) -> TestClient:
    app = FastAPI()
    add_dashboard_routes(app, store, _fake_verifier, moderate_generate=moderate_generate)
    c = TestClient(app)
    if login:
        # Exchange the (fake) Firebase token for a bbv2 session; TestClient keeps
        # the cookies, so later calls authenticate via the session (0019). The
        # leftover `headers=AUTH` on those calls is harmless — the cookie wins.
        r = c.post("/api/auth/exchange", headers=AUTH)
        assert r.status_code == 200, r.text
    return c


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    _ratelimit.limiter._hits.clear()
    yield


def test_auth_required():
    c = _client(Store(":memory:", check_same_thread=False), login=False)
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


def test_admin_routes_require_admin():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)  # provisions a regular (non-admin) user
    store.add_topic("crypto", "Crypto")

    # /api/me reports the role; default is non-admin
    assert c.get("/api/me", headers=AUTH).json()["user"]["role"] == "human"

    # curation routes are gated → 403 for a non-admin
    assert c.get("/api/topics/crypto/sources", headers=AUTH).status_code == 403
    assert c.post("/api/topics/crypto/discover", headers=AUTH).status_code == 403
    assert c.post("/api/sources/1/approve", headers=AUTH).status_code == 403
    assert c.post("/api/topics/crypto/brief", headers=AUTH).status_code == 403

    # open routes stay accessible to a non-admin
    assert c.get("/api/headlines", headers=AUTH).status_code == 200

    # promote (the only path is ADMIN_EMAILS in prod; here we set the role directly)
    store.set_user_role("me@example.com", "admin")
    assert c.get("/api/me", headers=AUTH).json()["user"]["role"] == "admin"
    assert c.get("/api/topics/crypto/sources", headers=AUTH).status_code == 200


def test_create_topic_moderation_denies():
    store = Store(":memory:", check_same_thread=False)
    deny = lambda *a, **k: '{"allowed": false, "category": "weapons", "reason": "no"}'
    c = _client(store, moderate_generate=deny)
    c.get("/api/me", headers=AUTH)
    r = c.post("/api/topics", json={"slug": "bombs", "name": "bomb stuff"}, headers=AUTH)
    assert r.status_code == 422
    assert c.get("/api/topics", headers=AUTH).json()["topics"] == []  # never created


def test_create_topic_existing_returns_existed():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    first = c.post("/api/topics", json={"slug": "crypto", "name": "Crypto"}, headers=AUTH)
    assert first.json()["existed"] is False
    again = c.post("/api/topics", json={"slug": "crypto", "name": "Crypto"}, headers=AUTH)
    assert again.json()["existed"] is True


def test_create_topic_rate_limited():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    for i in range(5):  # default cap is 5/hr
        assert c.post("/api/topics", json={"slug": f"t{i}", "name": "x"}, headers=AUTH).status_code == 200
    assert c.post("/api/topics", json={"slug": "t6", "name": "x"}, headers=AUTH).status_code == 429


def test_provision_unknown_topic_404():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    assert c.post("/api/topics/nope/provision", headers=AUTH).status_code == 404


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
    store.set_user_role("me@example.com", "admin")  # curation routes are admin-only
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


def test_approve_all_candidates_bulk():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    store.set_user_role("me@example.com", "admin")
    tid = store.add_topic("crypto", "Crypto")
    for i in range(3):
        sid = store.add_source("rss", f"https://x/{i}", f"S{i}", status="candidate")
        store.link_topic_source(tid, sid)

    r = c.post("/api/topics/crypto/sources/approve-all", headers=AUTH)
    assert r.status_code == 200 and r.json()["approved"] == 3
    active = c.get(
        "/api/topics/crypto/sources?status=active", headers=AUTH
    ).json()["sources"]
    assert len(active) == 3
    # candidates list is now empty
    cands = c.get(
        "/api/topics/crypto/sources?status=candidate", headers=AUTH
    ).json()["sources"]
    assert cands == []


def _put_brief(store, tid, date, title):
    store.upsert_brief(
        {
            "id": f"BRF-{date}",
            "topic_id": tid,
            "date": date,
            "title": title,
            "summary": "s",
            "trending": [],
            "sources": [],
            "model": "m",
        }
    )


def test_topic_briefs_rail_shows_today_then_brief_days():
    from datetime import datetime, timezone

    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")
    today = datetime.now(timezone.utc).date().isoformat()

    # No briefs yet → the rail still shows today as the entry point (brief null).
    days = c.get("/api/topics/crypto/briefs", headers=AUTH).json()["days"]
    assert [d["date"] for d in days] == [today]
    assert days[0]["brief"] is None

    # Once today's brief exists it shows with content — still just the one day,
    # no greyed-out empty days.
    _put_brief(store, tid, today, "Bitcoin Surges")
    days = c.get("/api/topics/crypto/briefs", headers=AUTH).json()["days"]
    assert len(days) == 1
    assert days[0]["date"] == today and days[0]["brief"]["title"] == "Bitcoin Surges"


def test_topic_briefs_rail_orders_and_caps_at_10():
    from datetime import datetime, timedelta, timezone

    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")
    base = datetime.now(timezone.utc).date()
    for i in range(12):  # 12 days of briefs ending today
        _put_brief(store, tid, (base - timedelta(days=i)).isoformat(), f"Day {i}")

    dates = [d["date"] for d in c.get("/api/topics/crypto/briefs", headers=AUTH).json()["days"]]
    assert len(dates) == 10  # capped at 10
    assert dates == sorted(dates, reverse=True)  # newest first
    assert dates[0] == base.isoformat()  # today at the top
    # the two oldest fall off the list
    assert (base - timedelta(days=10)).isoformat() not in dates
    assert (base - timedelta(days=11)).isoformat() not in dates


def test_approve_all_requires_admin():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)  # non-admin
    store.add_topic("crypto", "Crypto")
    assert (
        c.post("/api/topics/crypto/sources/approve-all", headers=AUTH).status_code
        == 403
    )


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


def test_briefs_endpoint_returns_subscribed_briefs():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")

    # not subscribed → empty
    assert c.get("/api/briefs", headers=AUTH).json()["briefs"] == []
    c.post("/api/topics/crypto/subscribe", headers=AUTH)

    store.upsert_brief(
        {
            "id": "BRF1",
            "topic_id": tid,
            "date": "2025-01-08",
            "title": "Crypto heats up",
            "summary": "S",
            "trending": [{"label": "bitcoin etf", "trend_score": 9}],
            "sources": [{"title": "a", "url": "u", "source_name": "X"}],
            "model": "m",
        }
    )
    data = c.get("/api/briefs", headers=AUTH).json()
    assert [b["title"] for b in data["briefs"]] == ["Crypto heats up"]
    assert data["briefs"][0]["sources"][0]["title"] == "a"
    assert data["briefs"][0]["trending"][0]["label"] == "bitcoin etf"
    assert [t["slug"] for t in data["topics"]] == ["crypto"]


def test_favorites_folders_items_roundtrip():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)

    # default folder auto-created on first read
    folders = c.get("/api/favorites/folders", headers=AUTH).json()["folders"]
    assert [f["name"] for f in folders] == ["favorites"]
    default_id = folders[0]["id"]

    # add a favorite (no folder_id → default)
    r = c.post(
        "/api/favorites/items",
        json={"title": "T", "url": "https://e/x", "item_id": "ITM1"},
        headers=AUTH,
    )
    assert r.status_code == 200
    fav_id = r.json()["id"]

    listed = c.get(f"/api/favorites/items?folder_id={default_id}", headers=AUTH).json()
    assert [i["title"] for i in listed["items"]] == ["T"]
    assert listed["folder"]["name"] == "favorites"

    # dedup per folder+url (same url upserts in place)
    c.post(
        "/api/favorites/items",
        json={"title": "T2", "url": "https://e/x"},
        headers=AUTH,
    )
    again = c.get(f"/api/favorites/items?folder_id={default_id}", headers=AUTH).json()["items"]
    assert len(again) == 1 and again[0]["title"] == "T2"
    assert c.get("/api/favorites/folders", headers=AUTH).json()["folders"][0]["count"] == 1

    # create a named folder
    nf = c.post("/api/favorites/folders", json={"name": "Reading"}, headers=AUTH).json()
    assert nf["name"] == "Reading"

    # remove the favorite
    assert c.delete(f"/api/favorites/items?favorite_id={fav_id}", headers=AUTH).status_code == 200
    assert c.get(f"/api/favorites/items?folder_id={default_id}", headers=AUTH).json()["items"] == []

    # validation
    assert c.post("/api/favorites/items", json={"title": "x"}, headers=AUTH).status_code == 400
    assert c.delete("/api/favorites/items?favorite_id=nope", headers=AUTH).status_code == 404


def test_conversations_crud():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)

    cid = c.post("/api/conversations", headers=AUTH).json()["id"]
    assert cid.startswith("CON")
    assert [x["id"] for x in c.get("/api/conversations", headers=AUTH).json()["conversations"]] == [cid]

    got = c.get(f"/api/conversations/{cid}", headers=AUTH).json()
    assert got["messages"] == [] and got["title"] is None

    assert c.patch(f"/api/conversations/{cid}", json={"title": "Renamed"}, headers=AUTH).status_code == 200
    assert c.get(f"/api/conversations/{cid}", headers=AUTH).json()["title"] == "Renamed"

    assert c.delete(f"/api/conversations/{cid}", headers=AUTH).status_code == 200
    assert c.get(f"/api/conversations/{cid}", headers=AUTH).status_code == 404

    # unknown conversation paths (message post 404s before any model call)
    assert c.get("/api/conversations/nope", headers=AUTH).status_code == 404
    assert (
        c.post("/api/conversations/nope/messages", json={"content": "hi"}, headers=AUTH).status_code
        == 404
    )


def test_preferences_persist_and_validate():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    me = c.get("/api/me", headers=AUTH).json()
    assert me["preferences"] == {"theme": None, "accent": None}  # default: follow OS

    assert c.patch("/api/preferences", json={"theme": "dark"}, headers=AUTH).status_code == 200
    assert c.get("/api/me", headers=AUTH).json()["preferences"]["theme"] == "dark"

    # accent persists; "" clears a value back to the default (NULL)
    c.patch("/api/preferences", json={"accent": "#7c5cff"}, headers=AUTH)
    assert c.get("/api/me", headers=AUTH).json()["preferences"]["accent"] == "#7c5cff"
    c.patch("/api/preferences", json={"theme": ""}, headers=AUTH)
    assert c.get("/api/me", headers=AUTH).json()["preferences"]["theme"] is None

    # invalid values are rejected, leaving state untouched
    assert c.patch("/api/preferences", json={"theme": "neon"}, headers=AUTH).status_code == 422
    assert c.patch("/api/preferences", json={"accent": "x" * 40}, headers=AUTH).status_code == 422


def test_ui_flags_round_trip():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    assert c.get("/api/me", headers=AUTH).json()["flags"] == []

    assert c.put("/api/flags/tour:headlines", headers=AUTH).status_code == 200
    assert c.put("/api/flags/onboarding_done", headers=AUTH).status_code == 200
    # idempotent
    assert c.put("/api/flags/tour:headlines", headers=AUTH).status_code == 200

    # flags survive a fresh /api/me — the localStorage-replay regression guard
    flags = c.get("/api/me", headers=AUTH).json()["flags"]
    assert flags == ["onboarding_done", "tour:headlines"]

    # unknown flags can't fill the table
    assert c.put("/api/flags/bogus", headers=AUTH).status_code == 422
    assert c.delete("/api/flags/bogus", headers=AUTH).status_code == 422

    assert c.delete("/api/flags/tour:headlines", headers=AUTH).status_code == 200
    assert c.get("/api/me", headers=AUTH).json()["flags"] == ["onboarding_done"]


def test_story_is_saved_flag_and_folder_save():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    tid = store.add_topic("crypto", "Crypto")
    _story(store, tid, "ITM1", "Bitcoin rallies", "2025-01-02T00:00:00+00:00")
    c.post("/api/topics/crypto/subscribe", headers=AUTH)

    # not saved yet
    items = c.post("/api/stories", json={}, headers=AUTH).json()["items"]
    assert items[0]["item_id"] == "ITM1" and items[0]["is_saved"] is False

    # save to the default favorites folder (what the modal does on open)
    r = c.post(
        "/api/favorites/items",
        json={"title": "Bitcoin rallies", "url": "https://e/ITM1", "item_id": "ITM1"},
        headers=AUTH,
    )
    assert r.status_code == 200

    # the flag now persists on a fresh query (the page-reload regression guard)
    again = c.post("/api/stories", json={}, headers=AUTH).json()["items"]
    assert again[0]["is_saved"] is True

    # file it into a new folder → shows up there
    fid = c.post("/api/favorites/folders", json={"name": "Reading"}, headers=AUTH).json()["id"]
    c.post(
        "/api/favorites/items",
        json={"title": "Bitcoin rallies", "url": "https://e/ITM1", "item_id": "ITM1", "folder_id": fid},
        headers=AUTH,
    )
    folder_items = c.get(f"/api/favorites/items?folder_id={fid}", headers=AUTH).json()["items"]
    assert [i["item_id"] for i in folder_items] == ["ITM1"]


def test_schedule_admin_endpoints():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    store.add_topic("tech", "Tech")
    store.set_user_role("me@example.com", "admin")  # cadence:set capability

    # GET surfaces defaults + the topic (unconfigured → null period)
    sched = c.get("/api/admin/schedule", headers=AUTH).json()
    assert sched["defaults"]["window_min"] == 15
    assert sched["topics"][0]["discover"]["period"] is None

    # run every week starting 2026-06-22 @ 02:00 + a story cap
    r = c.patch(
        "/api/topics/tech/schedule",
        json={
            "discover_period": "week",
            "discover_start_date": "2026-06-22",
            "discover_at_min": 120,
            "max_stories_per_source": 20,
        },
        headers=AUTH,
    )
    assert r.status_code == 200
    t = c.get("/api/admin/schedule", headers=AUTH).json()["topics"][0]
    assert t["discover"]["period"] == "week" and t["discover"]["at_min"] == 120
    assert t["discover"]["start_date"] == "2026-06-22"
    assert t["caps"]["max_stories_per_source"] == 20

    # validation: bad period / out-of-range minute / bad date
    assert c.patch("/api/topics/tech/schedule", json={"discover_period": "hourly"}, headers=AUTH).status_code == 422
    assert c.patch("/api/topics/tech/schedule", json={"discover_at_min": 2000}, headers=AUTH).status_code == 422
    assert c.patch("/api/topics/tech/schedule", json={"discover_start_date": "nope"}, headers=AUTH).status_code == 422

    # reset → back to defaults
    c.post("/api/topics/tech/schedule/reset", headers=AUTH)
    t = c.get("/api/admin/schedule", headers=AUTH).json()["topics"][0]
    assert t["discover"]["period"] is None and t["caps"]["max_stories_per_source"] is None


def test_schedule_admin_requires_capability():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)  # plain user
    assert c.get("/api/admin/schedule", headers=AUTH).status_code == 403


def test_story_click_beacon_and_metrics_gating():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    uid = store.get_user("me@example.com")["id"]

    # plain user can record a click but can't read metrics
    assert c.post("/api/stories/click", json={"item_id": "ITM1"}, headers=AUTH).status_code == 204
    assert c.get("/api/admin/metrics/llm", headers=AUTH).status_code == 403
    assert c.get("/api/admin/metrics/users", headers=AUTH).status_code == 403

    store.set_user_role("me@example.com", "admin")  # grants metrics:read
    llm = c.get("/api/admin/metrics/llm?range=7d", headers=AUTH).json()
    assert llm["range"] == "7d" and "by_topic" in llm and "prices" in llm

    users = c.get("/api/admin/metrics/users", headers=AUTH).json()
    me = next(u for u in users["users"] if u["id"] == uid)
    assert me["clicks"] == 1  # the beacon above
    assert users["totals"]["user_count"] >= 1


def test_source_disable_enable_delete_and_managed_list():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    store.set_user_role("me@example.com", "admin")  # sources:approve capability
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    store.set_source_status(sid, "active")

    def managed():
        return c.get("/api/topics/crypto/sources?status=managed", headers=AUTH).json()["sources"]

    assert [s["status"] for s in managed()] == ["active"]

    # disable → still in the managed list, excluded from collection
    assert c.post(f"/api/sources/{sid}/disable", headers=AUTH).status_code == 200
    m = managed()
    assert m[0]["status"] == "disabled"
    assert store.active_sources("crypto") == []  # not collected while disabled

    # enable → back to active
    c.post(f"/api/sources/{sid}/enable", headers=AUTH)
    assert managed()[0]["status"] == "active"
    assert len(store.active_sources("crypto")) == 1

    # delete → gone from the list + the source table
    assert c.delete(f"/api/sources/{sid}", headers=AUTH).status_code == 200
    assert managed() == []
    assert store.delete_source(sid) is False  # already gone


def test_source_actions_require_capability():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)  # plain user
    assert c.post("/api/sources/1/disable", headers=AUTH).status_code == 403
    assert c.delete("/api/sources/1", headers=AUTH).status_code == 403


def test_provision_creates_background_run(monkeypatch):
    import bbv2.provision_runner as runner
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    c.get("/api/me", headers=AUTH)
    store.add_topic("crypto", "Crypto")
    submitted = {}
    monkeypatch.setattr(
        runner, "submit",
        lambda store, run_id, slug, **k: submitted.update(run_id=run_id, slug=slug),
    )

    r = c.post("/api/topics/crypto/provision", headers=AUTH)
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert submitted == {"run_id": run_id, "slug": "crypto"}
    # observable via the poll endpoint
    runs = c.get("/api/provisioning", headers=AUTH).json()["runs"]
    assert [x["id"] for x in runs] == [run_id]
    assert runs[0]["surface"] == "topics" and runs[0]["status"] == "running"


def test_provisioning_conversation_filter():
    store = Store(":memory:", check_same_thread=False)
    c = _client(store)
    uid = c.get("/api/me", headers=AUTH).json()["user"]["id"]
    r1 = store.create_run(uid, "a", "A", surface="chat", conversation_id="CONx", message_id="M1")
    r2 = store.create_run(uid, "b", "B", surface="topics")
    allr = c.get("/api/provisioning", headers=AUTH).json()["runs"]
    assert {x["id"] for x in allr} == {r1, r2}
    conv = c.get("/api/provisioning?conversation=CONx", headers=AUTH).json()["runs"]
    assert [x["id"] for x in conv] == [r1] and conv[0]["message_id"] == "M1"


def test_run_provision_lifecycle_and_orphans(monkeypatch):
    import bbv2.provision_runner as runner
    store = Store(":memory:")
    store.add_topic("crypto", "Crypto")

    def ok(store, slug, **k):
        yield {"type": "stage", "stage": "discovering"}
        yield {"type": "stage", "stage": "ready", "sources": 1, "items": 1}

    monkeypatch.setattr(runner, "provision_topic", ok)
    rid = store.create_run(1, "crypto", "Crypto", surface="topics")
    runner.run_provision(store, rid, "crypto")
    row = store.get_run(rid)
    assert row["status"] == "done" and row["stage"] == "ready"

    def boom(store, slug, **k):
        yield {"type": "error", "message": "discovery failed"}

    monkeypatch.setattr(runner, "provision_topic", boom)
    rid2 = store.create_run(1, "crypto", "Crypto")
    runner.run_provision(store, rid2, "crypto")
    assert store.get_run(rid2)["status"] == "error"

    # a still-'running' row is an orphan after restart → marked interrupted
    rid3 = store.create_run(1, "crypto", "Crypto")
    assert store.fail_orphaned_runs() == 1
    assert store.get_run(rid3)["status"] == "error"
    assert store.get_run(rid3)["error"] == "interrupted"
