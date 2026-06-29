"""Background execution of on-demand discovery runs (0030).

`run_discovery` drives `discover_for_query` for a free-text query and stores the
preview (candidate feeds + sample headlines + web results) on the run row, so the
chat results card can poll for it and survive navigation. `submit` dispatches on a
small bounded pool. Tests monkeypatch `submit` to run synchronously.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import requests

from . import config
from .store import Store

log = logging.getLogger("bbv2.discovery_run")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=config.provision_workers(), thread_name_prefix="discovery"
            )
    return _executor


def run_discovery(
    store: Store,
    run_id: str,
    query: str,
    *,
    query_generate: Callable[..., str] | None = None,
) -> None:
    """Execute one discovery search to completion, recording the preview + status.
    Best-effort: any failure marks the run 'error' rather than raising."""
    try:
        from .discovery import discover_for_query, feed_headline_finder

        session = requests.Session()
        store.set_discovery_stage(run_id, "probing")
        res = discover_for_query(
            query,
            store=store,
            generate=query_generate,
            headline_finder=feed_headline_finder(store, session),
            max_candidates=config.discovery_preview_max(),
            attempts=2,
        )
        store.finish_discovery_run(run_id, "done", result=res)
        log.info(
            "discovery run %s done: %d candidate(s) for %r",
            run_id, len(res.get("candidates") or []), query,
        )
    except Exception as exc:  # noqa: BLE001 - background work must never crash the pool
        log.warning("discovery run %s failed (%r): %s", run_id, query, exc)
        try:
            store.finish_discovery_run(run_id, "error", error=str(exc))
        except Exception:  # pragma: no cover - DB already unhappy
            pass


def submit(
    store: Store, run_id: str, query: str, *, query_generate: Callable[..., str] | None = None
) -> Any:
    """Dispatch a discovery run on the background pool. Tests replace this."""
    return _pool().submit(run_discovery, store, run_id, query, query_generate=query_generate)
