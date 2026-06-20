from bbv2.provision import provision_topic
from bbv2.store import Store


def _seed_candidates(store: Store) -> int:
    tid = store.add_topic("crypto", "Crypto")
    for i in range(2):
        sid = store.add_source("rss", f"https://x{i}/feed", f"S{i}", status="candidate")
        store.link_topic_source(tid, sid)
    return tid


def test_provision_emits_stages_and_auto_approves():
    store = Store(":memory:")
    _seed_candidates(store)
    events = list(
        provision_topic(
            store,
            "crypto",
            discover=lambda: {"candidates": 2},
            collect=lambda: {"new": 5},
        )
    )
    stages = [e["stage"] for e in events if e["type"] == "stage"]
    assert stages == ["discovering", "approving", "collecting", "ready"]
    ready = events[-1]
    assert ready["sources"] == 2 and ready["items"] == 5
    # candidates were flipped to active
    assert store.topic_has_sources("crypto") is True
    assert store.list_candidates("crypto") == []


def test_provision_unknown_topic():
    store = Store(":memory:")
    assert list(provision_topic(store, "nope")) == [
        {"type": "error", "message": "unknown topic"}
    ]


def test_provision_discovery_error_stops():
    store = Store(":memory:")
    store.add_topic("crypto", "Crypto")

    def boom():
        raise RuntimeError("brave down")

    events = list(provision_topic(store, "crypto", discover=boom, collect=lambda: {"new": 0}))
    assert events[0]["stage"] == "discovering"
    assert events[-1]["type"] == "error" and "discovery failed" in events[-1]["message"]
