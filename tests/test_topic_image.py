"""Per-DAY brief Grok Imagine header images (0024 → 0032)."""

import bbv2.config as config
import bbv2.topic_image as ti
from bbv2.store import Store


def _brief(store, tid, date, summary):
    store.upsert_brief({
        "id": f"BRF{date}", "topic_id": tid, "date": date, "title": "t",
        "summary": summary, "trending": [], "sources": [], "model": "x",
    })
    return store.get_brief(tid, date)


def test_generate_writes_dated_file_and_sets_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "topic_images_dir", lambda: tmp_path)
    store = Store(":memory:")
    tid = store.add_topic("ai", "AI")
    _brief(store, tid, "2030-06-01", "Big AI news today.")
    ti.generate_brief_image(
        store, tid, "ai", "2030-06-01", "AI", "Big AI news today.",
        image_fn=lambda prompt: b"\xff\xd8jpeg",
    )
    b = store.get_brief(tid, "2030-06-01")
    assert b["image_status"] == "ready"
    assert b["image_path"] == str(tmp_path / "ai-2030-06-01.jpg")  # dated filename
    assert (tmp_path / "ai-2030-06-01.jpg").read_bytes() == b"\xff\xd8jpeg"


def test_generate_failure_sets_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "topic_images_dir", lambda: tmp_path)
    store = Store(":memory:")
    tid = store.add_topic("ai", "AI")
    _brief(store, tid, "2030-06-01", "x")

    def moderated(prompt):
        raise RuntimeError("moderated")

    ti.generate_brief_image(store, tid, "ai", "2030-06-01", "AI", "x", image_fn=moderated)
    assert store.get_brief(tid, "2030-06-01")["image_status"] == "error"


def test_maybe_kick_is_per_day_and_idempotent(monkeypatch):
    monkeypatch.setattr(config, "topic_images_enabled", lambda: True)
    submitted = []
    monkeypatch.setattr(
        ti, "submit",
        lambda store, tid, slug, date, *a, **k: submitted.append((slug, date)),
    )
    store = Store(":memory:")
    tid = store.add_topic("ai", "AI")
    d1 = _brief(store, tid, "2030-06-01", "day one")
    d2 = _brief(store, tid, "2030-06-02", "day two")

    ti.maybe_kick(store, store.get_topic("ai"), d1)
    assert submitted == [("ai", "2030-06-01")]
    assert store.get_brief(tid, "2030-06-01")["image_status"] == "pending"

    # same day again → no second submit (already pending)
    ti.maybe_kick(store, store.get_topic("ai"), store.get_brief(tid, "2030-06-01"))
    assert submitted == [("ai", "2030-06-01")]

    # a DIFFERENT day → its own image (this is the 0032 fix)
    ti.maybe_kick(store, store.get_topic("ai"), d2)
    assert submitted == [("ai", "2030-06-01"), ("ai", "2030-06-02")]

    # no summary → never kicks
    d3 = _brief(store, tid, "2030-06-03", "")
    ti.maybe_kick(store, store.get_topic("ai"), d3)
    assert ("ai", "2030-06-03") not in submitted


def test_maybe_kick_disabled(monkeypatch):
    monkeypatch.setattr(config, "topic_images_enabled", lambda: False)
    submitted = []
    monkeypatch.setattr(ti, "submit", lambda *a, **k: submitted.append(a))
    store = Store(":memory:")
    tid = store.add_topic("ai", "AI")
    d = _brief(store, tid, "2030-06-01", "summary")
    ti.maybe_kick(store, store.get_topic("ai"), d)
    assert submitted == []
