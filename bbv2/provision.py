"""Topic provisioning: discover → auto-approve → collect, as a stage stream.

A synchronous generator yielding dict **stage events** for the SSE endpoint
(`discovering` → `approving` → `collecting` → `ready`, or `error`). The
discover/collect callables are injectable so the sequence is offline-testable.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from .store import Store


def provision_topic(
    store: Store,
    topic_slug: str,
    *,
    discover: Callable[[], dict[str, Any]] | None = None,
    collect: Callable[[], dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    if not store.get_topic(topic_slug):
        yield {"type": "error", "message": "unknown topic"}
        return

    if discover is None:
        from .discovery import discover_sources

        def discover() -> dict[str, Any]:
            return discover_sources(store, topic_slug)

    if collect is None:
        from .collect import collect as _collect

        def collect() -> dict[str, Any]:
            return _collect(store, topic_slug)

    yield {"type": "stage", "stage": "discovering"}
    try:
        d = discover()
    except Exception as exc:  # best-effort; surface as an error event
        yield {"type": "error", "message": f"discovery failed: {exc}"}
        return
    candidates = int(d.get("candidates", 0))

    yield {"type": "stage", "stage": "approving", "candidates": candidates}
    approved = store.approve_all_candidates(topic_slug)

    yield {"type": "stage", "stage": "collecting"}
    try:
        c = collect()
    except Exception as exc:
        yield {"type": "error", "message": f"collect failed: {exc}"}
        return

    yield {
        "type": "stage",
        "stage": "ready",
        "sources": approved,
        "items": int(c.get("new", 0)),
    }
