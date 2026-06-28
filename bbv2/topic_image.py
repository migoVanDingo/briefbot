"""Per-topic header image generation via Grok Imagine (0024).

A topic gets ONE stable image, generated once in the background the first time it
has a brief (seeded from that brief's summary + the topic name). Best-effort: any
failure (incl. moderation) marks the topic's `image_status` 'error' and the UI
just shows no image. The image is stored on disk and served by the API.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import config
from .store import Store

log = logging.getLogger("bbv2.topic_image")

PENDING, READY, ERROR = "pending", "ready", "error"
ImageFn = Callable[..., bytes]

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="topicimg")
    return _executor


def _prompt(topic_name: str, summary: str) -> str:
    gist = (summary or "").strip().split("\n")[0][:240]
    return (
        "Editorial header illustration for a news topic. Clean modern flat vector "
        "style, cohesive muted palette, soft depth and lighting. Absolutely NO text, "
        "words, letters, captions, or logos. "
        f"Subject: {topic_name}. Evoke the current news mood: {gist}"
    )


def generate_topic_image(
    store: Store, slug: str, topic_name: str, summary: str, *, image_fn: ImageFn | None = None
) -> None:
    """Run one image generation to completion, recording the result on the topic."""
    try:
        from .llm import grok_image

        data = (image_fn or grok_image)(_prompt(topic_name, summary))
        directory = config.topic_images_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{slug}.jpg"
        path.write_bytes(data)
        store.set_topic_image(slug, str(path), READY)
        # Meter one image to the system bucket so it shows in the cost breakdown
        # (priced per-image, not per-token — input/output stay 0). Best-effort.
        try:
            topic = store.get_topic(slug)
            store.record_usage(
                0, "image", config.grok_image_model(), 0, 0,
                topic_id=int(topic["id"]) if topic else None,
            )
        except Exception:  # pragma: no cover - never fail the gen on metering
            pass
        log.info("topic image ready: %s", slug)
    except Exception as exc:  # noqa: BLE001 - best-effort; never crash the pool
        log.warning("topic image gen failed for %s: %s", slug, exc)
        try:
            store.set_topic_image(slug, None, ERROR)
        except Exception:  # pragma: no cover
            pass


def submit(
    store: Store, slug: str, topic_name: str, summary: str, *, image_fn: ImageFn | None = None
) -> None:
    _pool().submit(generate_topic_image, store, slug, topic_name, summary, image_fn=image_fn)


def maybe_kick(store: Store, topic_row, summary: str | None) -> None:
    """Start a one-time background image gen if this topic has none yet. Idempotent:
    marks the topic 'pending' immediately so concurrent brief views don't double-fire."""
    if not config.topic_images_enabled() or not (summary or "").strip():
        return
    status = topic_row["image_status"] if "image_status" in topic_row.keys() else "none"
    if status not in (None, "", "none"):
        return  # already pending / ready / errored — leave it
    slug = topic_row["slug"]
    # Atomic claim: only the thread that wins the unset→pending UPDATE submits, so
    # concurrent first-views can't both fire the (paid) image gen.
    if not store.claim_topic_image(slug):
        return
    submit(store, slug, topic_row["name"], summary or "")
