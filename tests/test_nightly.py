"""The `bbv2 nightly` job — briefs for subscribed topics + 'brief ready' emails."""

from bbv2.nightly import run_nightly
from bbv2.store import Store
from bbv2.util import utc_now_iso


class _CapturingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))


def _seed(store: Store) -> int:
    uid = store.add_user("Me", "me@example.com")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    store.subscribe(uid, tid)
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
    return uid


def test_nightly_briefs_subscribed_topics_and_emails():
    store = Store(":memory:")
    _seed(store)
    notifier = _CapturingNotifier()

    stats = run_nightly(
        store,
        notifier,
        brief_generate=lambda *a, **k: '{"title": "Crypto Today", "summary": "BTC up."}',
    )

    assert stats["topics_briefed"] == 1
    assert stats["emails_sent"] == 1
    assert notifier.sent[0][0] == "me@example.com"
    assert "brief is ready" in notifier.sent[0][1].lower()
    # brief persisted + checkpoint advanced
    topic = store.get_topic("crypto")
    assert store.latest_brief(int(topic["id"])) is not None
    assert topic["last_briefed_at"] is None or True  # set after run
    assert store.get_topic("crypto")["last_briefed_at"] is not None


def test_nightly_skips_topics_without_subscribers():
    store = Store(":memory:")
    store.add_topic("orphan", "Orphan")  # no subscriber
    notifier = _CapturingNotifier()
    stats = run_nightly(store, notifier, brief_generate=lambda *a, **k: "{}")
    assert stats["topics_briefed"] == 0
    assert stats["emails_sent"] == 0
