"""Admin metrics expansion (0027): purpose labels, image cost, per-user detail."""

from bbv2.store import Store


def _seed_usage(store: Store, uid: int, tid: int) -> None:
    store.record_usage(uid, "chat", "claude-haiku", 1000, 500, topic_id=None)
    store.record_usage(uid, "rundown", "grok-3-mini", 2000, 100, topic_id=tid)
    # two images (per-image cost, 0 tokens)
    store.record_usage(0, "image", "grok-imagine", 0, 0, topic_id=tid)
    store.record_usage(0, "image", "grok-imagine", 0, 0, topic_id=None)


def test_usage_summary_labels_and_image_cost(monkeypatch):
    monkeypatch.setenv("GROK_IMAGE_PRICE", "0.05")
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    tid = store.add_topic("ai", "AI")
    _seed_usage(store, uid, tid)

    s = store.usage_summary("2000-01-01T00:00:00+00:00")
    # image accounting
    assert s["images"]["count"] == 2
    assert abs(s["images"]["cost"] - 0.10) < 1e-9
    assert abs(s["images"]["unit_price"] - 0.05) < 1e-9
    # image cost folded into overall
    assert s["overall"]["images"] == 2
    assert s["overall"]["cost"] > 0.10  # token cost + image cost
    # by_purpose carries friendly labels; the image row reflects the per-image cost
    labels = {r["purpose"]: r for r in s["by_purpose"]}
    assert labels["chat"]["label"] == "Agent chat"
    assert labels["rundown"]["label"] == "Topic rundowns"
    assert labels["image"]["calls"] == 2
    assert abs(labels["image"]["cost"] - 0.10) < 1e-9
    # background bucket is renamed + flagged
    buckets = {b["name"]: b for b in s["by_topic"]}
    assert "Not topic-specific" in buckets
    assert buckets["Not topic-specific"]["kind"] == "background"
    assert any(b.get("kind") == "topic" for b in s["by_topic"])


def test_user_detail(monkeypatch):
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    tid = store.add_topic("ai", "AI")
    store.subscribe(uid, tid)
    _seed_usage(store, uid, tid)
    store.log_auth_event(uid, "login", "1.2.3.4", "ua")
    # a thumbs up + down
    store.upsert_item({
        "item_id": "I1", "dedupe_key": "k1", "canonical_url": "u", "source_id": "1",
        "source_name": "S", "title": "T", "url": "http://x", "published_at": None,
        "fetched_at": "2025-01-01T00:00:00+00:00", "summary": "", "score": 0, "raw": {},
    })
    store.set_story_feedback(uid, "I1", 1)

    d = store.user_detail(uid, "2000-01-01T00:00:00+00:00")
    assert d is not None
    assert d["user"]["email"] == "me@example.com"
    assert d["usage"]["tokens"] == 3600  # 1500 chat + 2100 rundown
    assert d["usage"]["cost"] > 0
    assert d["access"]["logins"] == 1
    assert [s["slug"] for s in d["subscriptions"]] == ["ai"]
    assert d["feedback"]["up"] == 1 and d["feedback"]["down"] == 0
    assert d["feedback"]["recent"][0]["item_id"] == "I1"


def test_user_detail_unknown_user():
    store = Store(":memory:")
    assert store.user_detail(999, "2000-01-01T00:00:00+00:00") is None


def test_user_detail_feedback_is_range_scoped():
    """👍/👎 in the drill-down must respect the selected window (was all-time)."""
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    for iid in ("OLD", "NEW"):
        store.upsert_item({
            "item_id": iid, "dedupe_key": f"k{iid}", "canonical_url": "u", "source_id": "1",
            "source_name": "S", "title": iid, "url": "http://x", "published_at": None,
            "fetched_at": "2020-01-01T00:00:00+00:00", "summary": "", "score": 0, "raw": {},
        })
    # one vote far in the past, one recent — write updated_at directly to control the window
    store.conn.execute(
        "INSERT INTO story_feedback (user_id, item_id, vote, updated_at) VALUES (?,?,?,?)",
        (uid, "OLD", 1, "2020-01-01T00:00:00+00:00"),
    )
    store.conn.execute(
        "INSERT INTO story_feedback (user_id, item_id, vote, updated_at) VALUES (?,?,?,?)",
        (uid, "NEW", -1, "2030-06-01T00:00:00+00:00"),
    )
    store.conn.commit()

    # window starting 2030 → only the NEW (down) vote counts
    d = store.user_detail(uid, "2030-01-01T00:00:00+00:00")
    assert d["feedback"]["up"] == 0 and d["feedback"]["down"] == 1
    assert [v["item_id"] for v in d["feedback"]["recent"]] == ["NEW"]
    # a window reaching back to 2020 includes both
    d2 = store.user_detail(uid, "2019-01-01T00:00:00+00:00")
    assert d2["feedback"]["up"] == 1 and d2["feedback"]["down"] == 1


def test_usage_summary_by_model_reconciles_with_overall(monkeypatch):
    """by_model must include per-image cost so it sums to overall (was omitted)."""
    monkeypatch.setenv("GROK_IMAGE_PRICE", "0.05")
    store = Store(":memory:")
    uid = store.add_user("Me", "me@example.com")
    store.record_usage(uid, "chat", "claude-haiku", 1000, 500)
    store.record_usage(0, "image", "grok-imagine", 0, 0)
    s = store.usage_summary("2000-01-01T00:00:00+00:00")
    assert abs(sum(m["cost"] for m in s["by_model"]) - s["overall"]["cost"]) < 1e-9
    assert sum(m["calls"] for m in s["by_model"]) == s["overall"]["calls"]
