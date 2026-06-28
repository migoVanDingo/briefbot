"""Grok-generated profile avatars (0028).

Mirrors `topic_image`: a bounded background pool generates a 1:1 avatar from the
user's text prompt, stores it on disk, and flips `avatar_status` ready/error.
Best-effort — on any failure the user keeps their identicon. Metered as an
"image" so it shows in the cost breakdown (0027)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import config
from .store import Store
from .usage import SYSTEM_USER_ID

log = logging.getLogger("bbv2.avatar_image")

READY, ERROR = "ready", "error"
ImageFn = Callable[..., bytes]

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="avatar")
    return _executor


def _prompt(user_prompt: str) -> str:
    gist = (user_prompt or "").strip()[:240]
    return (
        "A single circular profile avatar, centered subject, clean modern flat "
        "vector style, bold simple shapes, cohesive palette, no text or letters. "
        f"Theme: {gist}"
    )


def generate_avatar(
    store: Store, user_id: int, user_prompt: str, *, image_fn: ImageFn | None = None
) -> None:
    """Run one avatar generation to completion, recording the result on the user."""
    try:
        from .llm import grok_image

        data = (image_fn or grok_image)(
            _prompt(user_prompt), aspect_ratio="1:1", resolution="1k"
        )
        directory = config.avatars_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{user_id}.jpg"
        path.write_bytes(data)
        store.set_avatar(user_id, str(path), READY)
        try:  # meter one image (per-image cost, 0 tokens) — best-effort
            store.record_usage(SYSTEM_USER_ID, "image", config.grok_image_model(), 0, 0)
        except Exception:  # pragma: no cover
            pass
        log.info("avatar ready: user %s", user_id)
    except Exception as exc:  # noqa: BLE001 - best-effort; never crash the pool
        log.warning("avatar gen failed for user %s: %s", user_id, exc)
        try:
            store.set_avatar(user_id, None, ERROR)
        except Exception:  # pragma: no cover
            pass


def start_avatar(store: Store, user_id: int, user_prompt: str) -> bool:
    """Claim + submit a one-shot avatar generation. Returns False if disabled or a
    generation is already pending (idempotent against double-submit)."""
    if not config.avatars_enabled() or not (user_prompt or "").strip():
        return False
    if not store.claim_avatar(user_id, user_prompt.strip()):
        return False
    _pool().submit(generate_avatar, store, user_id, user_prompt.strip())
    return True
