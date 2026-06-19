from bbv2.digest import run_digests
from bbv2.store import Store


def _item(iid: str, fetched_at: str, title: str = "t") -> dict:
    return {
        "item_id": iid,
        "dedupe_key": f"url:{iid}",
        "canonical_url": f"https://e/{iid}",
        "source_id": "1",
        "source_name": "S",
        "title": title,
        "url": f"https://e/{iid}",
        "published_at": fetched_at,
        "fetched_at": fetched_at,
        "summary": "",
        "score": 1.0,
        "raw": {},
    }


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))


def test_visibility_follows_subscriptions():
    store = Store(":memory:")
    crypto = store.add_topic("crypto", "Crypto")
    politics = store.add_topic("politics", "Politics")
    uid = store.add_user("Mom", "mom@e.com")

    store.upsert_item(_item("a", "2025-01-01T00:00:00+00:00"))
    store.map_item_topic("a", crypto)
    store.upsert_item(_item("b", "2025-01-02T00:00:00+00:00"))
    store.map_item_topic("b", politics)

    store.subscribe(uid, crypto)
    assert {r["item_id"] for r in store.items_for_user(uid)} == {"a"}  # not politics

    store.unsubscribe(uid, crypto)
    assert store.items_for_user(uid) == []
    store.close()


def test_settings_defaults_and_roundtrip():
    store = Store(":memory:")
    uid = store.add_user("Bro", "bro@e.com")
    s = store.get_user_settings(uid)
    assert s["email_enabled"] == 1 and s["digest_limit"] == 10
    store.set_user_settings(uid, email_enabled=False, digest_limit=5)
    s = store.get_user_settings(uid)
    assert s["email_enabled"] == 0 and s["digest_limit"] == 5
    store.close()


def test_digest_sends_then_checkpoints():
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    uid = store.add_user("Mom", "mom@e.com")
    store.subscribe(uid, tid)
    for iid, fa in [("a", "2025-01-01T00:00:00+00:00"), ("b", "2025-01-02T00:00:00+00:00")]:
        store.upsert_item(_item(iid, fa))
        store.map_item_topic(iid, tid)

    fake = FakeNotifier()
    stats = run_digests(store, fake)
    assert stats["sent"] == 1 and len(fake.sent) == 1
    to, subject, _ = fake.sent[0]
    assert to == "mom@e.com" and "2 new" in subject

    # Second run: checkpoint advanced → nothing new.
    stats2 = run_digests(store, fake)
    assert stats2["sent"] == 0 and stats2["skipped"] == 1
    assert len(fake.sent) == 1
    store.close()


def test_digest_respects_email_disabled():
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    uid = store.add_user("Mom", "mom@e.com")
    store.subscribe(uid, tid)
    store.upsert_item(_item("a", "2025-01-01T00:00:00+00:00"))
    store.map_item_topic("a", tid)
    store.set_user_settings(uid, email_enabled=False)

    fake = FakeNotifier()
    assert run_digests(store, fake)["sent"] == 0
    assert fake.sent == []
    store.close()
