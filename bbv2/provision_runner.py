"""Background execution of provisioning runs (0023).

`run_provision` drives the existing `provision_topic` generator and writes each
stage to the run row, so any client can poll `provision_runs` for live progress.
`submit` dispatches it on a small bounded thread pool (so the work finishes even
if the initiating request/connection goes away). Tests monkeypatch `submit` to
run synchronously.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import config
from .provision import provision_topic
from .store import Store

log = logging.getLogger("bbv2.provision")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=config.provision_workers(), thread_name_prefix="provision"
            )
    return _executor


def run_provision(
    store: Store,
    run_id: str,
    slug: str,
    *,
    query_generate: Callable[..., str] | None = None,
    review_generate: Callable[..., str] | None = None,
    brief_generate: Callable[..., str] | None = None,
) -> None:
    """Execute one run to completion, recording stage progress + the final status.
    Best-effort: any failure marks the run 'error' rather than raising."""
    try:
        for ev in provision_topic(
            store, slug,
            query_generate=query_generate,
            review_generate=review_generate,
            brief_generate=brief_generate,
        ):
            kind = ev.get("type")
            if kind == "stage":
                store.set_run_stage(run_id, str(ev.get("stage")))
            elif kind == "error":
                store.finish_run(run_id, "error", error=str(ev.get("message")))
                return
        store.finish_run(run_id, "done")
    except Exception as exc:  # noqa: BLE001 - background work must never crash the pool
        log.warning("provision run %s (%s) failed: %s", run_id, slug, exc)
        try:
            store.finish_run(run_id, "error", error=str(exc))
        except Exception:  # pragma: no cover - DB already unhappy
            pass


def submit(
    store: Store,
    run_id: str,
    slug: str,
    *,
    query_generate: Callable[..., str] | None = None,
    review_generate: Callable[..., str] | None = None,
    brief_generate: Callable[..., str] | None = None,
) -> Any:
    """Dispatch a run on the background pool. Tests replace this with a sync call."""
    return _pool().submit(
        run_provision,
        store,
        run_id,
        slug,
        query_generate=query_generate,
        review_generate=review_generate,
        brief_generate=brief_generate,
    )
