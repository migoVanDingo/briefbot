"""Topic provisioning: discover → auto-approve → collect, as a stage stream.

A synchronous generator yielding dict **stage events** for the SSE endpoint
(`discovering` → `approving` → `collecting` → `ready`, or `error`). The
discover/collect callables are injectable so the sequence is offline-testable.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterator

from .store import Store

log = logging.getLogger("bbv2.provision")


def provision_topic(
    store: Store,
    topic_slug: str,
    *,
    discover: Callable[[], dict[str, Any]] | None = None,
    collect: Callable[[], dict[str, Any]] | None = None,
    query_generate: Callable[..., str] | None = None,
    review_generate: Callable[..., str] | None = None,
    brief_generate: Callable[..., str] | None = None,
) -> Iterator[dict[str, Any]]:
    if not store.get_topic(topic_slug):
        yield {"type": "error", "message": "unknown topic"}
        return

    if discover is None:
        from .discovery import discover_sources

        def discover() -> dict[str, Any]:
            return discover_sources(store, topic_slug, generate=query_generate)

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

    # No usable sources found (after retries) and none already active → tell the
    # user plainly rather than leaving an empty "ready" topic.
    if candidates == 0 and not store.topic_has_sources(topic_slug):
        yield {
            "type": "error",
            "message": "couldn't find good sources for this topic — try a more specific name or description",
        }
        return

    yield {"type": "stage", "stage": "approving", "candidates": candidates}
    approved = store.approve_all_candidates(topic_slug)

    yield {"type": "stage", "stage": "collecting"}
    try:
        c = collect()
    except Exception as exc:
        yield {"type": "error", "message": f"collect failed: {exc}"}
        return

    # Final step: LLM quickscan drops off-topic stories the source carried.
    yield {"type": "stage", "stage": "reviewing"}
    try:
        from .review import quickscan_topic

        review = quickscan_topic(store, topic_slug, generate=review_generate)
    except Exception:
        review = {"kept": None, "dropped": None}

    # Optional: build the topic's first brief so /headlines is populated the moment
    # the topic is ready (best-effort — Headlines builds it lazily otherwise).
    if brief_generate is not None:
        yield {"type": "stage", "stage": "summarizing"}
        try:
            from .brief import get_or_build_brief

            get_or_build_brief(store, topic_slug, generate=brief_generate)
        except Exception as exc:  # noqa: BLE001 - best-effort
            log.warning("brief failed for %s: %s", topic_slug, exc)

    yield {
        "type": "stage",
        "stage": "ready",
        "sources": approved,
        "items": int(c.get("new", 0)),
        "dropped": review.get("dropped"),
    }
