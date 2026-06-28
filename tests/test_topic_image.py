"""Per-topic Grok Imagine header images (0024)."""

import bbv2.config as config
import bbv2.topic_image as ti
from bbv2.store import Store


def test_generate_writes_file_and_sets_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "topic_images_dir", lambda: tmp_path)
    store = Store(":memory:")
    store.add_topic("ai", "AI")
    ti.generate_topic_image(
        store, "ai", "AI", "Big AI news today.", image_fn=lambda prompt: b"\xff\xd8jpeg"
    )
    row = store.get_topic("ai")
    assert row["image_status"] == "ready"
    assert row["image_path"] == str(tmp_path / "ai.jpg")
    assert (tmp_path / "ai.jpg").read_bytes() == b"\xff\xd8jpeg"


def test_generate_failure_sets_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "topic_images_dir", lambda: tmp_path)
    store = Store(":memory:")
    store.add_topic("ai", "AI")

    def moderated(prompt):
        raise RuntimeError("moderated")

    ti.generate_topic_image(store, "ai", "AI", "x", image_fn=moderated)
    assert store.get_topic("ai")["image_status"] == "error"


def test_maybe_kick_idempotent(monkeypatch):
    monkeypatch.setattr(config, "topic_images_enabled", lambda: True)
    submitted = []
    monkeypatch.setattr(ti, "submit", lambda store, slug, *a, **k: submitted.append(slug))
    store = Store(":memory:")
    store.add_topic("ai", "AI")

    ti.maybe_kick(store, store.get_topic("ai"), "summary")
    assert submitted == ["ai"]
    assert store.get_topic("ai")["image_status"] == "pending"

    # already pending → no second submit
    ti.maybe_kick(store, store.get_topic("ai"), "summary")
    assert submitted == ["ai"]

    # no summary → never kicks
    store.add_topic("b", "B")
    ti.maybe_kick(store, store.get_topic("b"), "")
    assert submitted == ["ai"]


def test_maybe_kick_disabled(monkeypatch):
    monkeypatch.setattr(config, "topic_images_enabled", lambda: False)
    submitted = []
    monkeypatch.setattr(ti, "submit", lambda *a, **k: submitted.append(a))
    store = Store(":memory:")
    store.add_topic("ai", "AI")
    ti.maybe_kick(store, store.get_topic("ai"), "summary")
    assert submitted == []
