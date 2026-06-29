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


def generate_brief_image(
    store: Store, topic_id: int, slug: str, date: str, topic_name: str, summary: str,
    *, image_fn: ImageFn | None = None,
) -> None:
    """Generate one DAY's brief image (0032), recording it on that brief row."""
    try:
        from .llm import grok_image

        data = (image_fn or grok_image)(_prompt(topic_name, summary))
        directory = config.topic_images_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{slug}-{date}.jpg"
        path.write_bytes(data)
        store.set_brief_image(topic_id, date, str(path), READY)
        # Meter one image to the system bucket (priced per-image; 0 tokens). Best-effort.
        try:
            store.record_usage(0, "image", config.grok_image_model(), 0, 0, topic_id=topic_id)
        except Exception:  # pragma: no cover - never fail the gen on metering
            pass
        log.info("brief image ready: %s %s", slug, date)
    except Exception as exc:  # noqa: BLE001 - best-effort; never crash the pool
        log.warning("brief image gen failed for %s %s: %s", slug, date, exc)
        try:
            store.set_brief_image(topic_id, date, None, ERROR)
        except Exception:  # pragma: no cover
            pass


def submit(
    store: Store, topic_id: int, slug: str, date: str, topic_name: str, summary: str,
    *, image_fn: ImageFn | None = None,
) -> None:
    _pool().submit(
        generate_brief_image, store, topic_id, slug, date, topic_name, summary, image_fn=image_fn
    )


def maybe_kick(store: Store, topic_row, brief_row) -> None:
    """Start a one-time background image gen for THIS day's brief if it has none yet
    (0032). Atomic claim so concurrent views don't double-fire the paid gen."""
    summary = brief_row["summary"] if brief_row is not None else None
    if not config.topic_images_enabled() or not (summary or "").strip():
        return
    status = brief_row["image_status"] if "image_status" in brief_row.keys() else "none"
    if status not in (None, "", "none"):
        return  # already pending / ready / errored — leave it
    topic_id, date = int(brief_row["topic_id"]), brief_row["date"]
    if not store.claim_brief_image(topic_id, date):
        return
    submit(store, topic_id, topic_row["slug"], date, topic_row["name"], summary or "")
