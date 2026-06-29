"""Agent tool handlers that spawn background runs (0023/0030).

Split out of `agent.py` to keep it under the size cap. These build/kick durable
runs (topic provisioning, source discovery, source commit) and yield the SSE
events the chat turn streams. Kept dependency-light (imports from usage/config/
store, lazy-imports the runners) so `agent.py` can import them without a cycle.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from . import config
from .store import Store
from .usage import (
    SYSTEM_USER_ID,
    budget_status,
    metered_generate,
    metered_relevance_generate,
)


def _slugify(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in (name or "").lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:40]


def _create_topic_events(
    store: Store,
    user_id: int,
    args: dict[str, Any],
    *,
    conversation_id: str,
    message_id: str,
    moderate_generate: Callable[..., str] | None,
    review_generate: Callable[..., str] | None,
) -> Iterator[dict[str, Any]]:
    """Create a topic and kick off its provisioning as a **background run** (0023).

    Yields `tool_start`, a `topic_run` (so the pill appears in the live message),
    then `tool_end`; returns `(result, summary)` for the model's tool_result. The
    pipeline advances in the background and is observed by polling — so it survives
    the user navigating away. The hard token budget gates this."""
    from . import provision_runner
    from .moderation import ModerationError, moderate_topic

    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "a topic name is required"}, "missing name"

    gate = budget_status(store, user_id)
    if not gate["allowed"]:
        return {"error": gate["message"], "limit_reached": True}, "limit reached"

    # Meter the moderation LLM call to the acting user (tests inject a stub).
    mod_gen = moderate_generate or metered_generate(store, user_id, "moderation")
    try:
        clean = moderate_topic(
            _slugify(name),
            name,
            mod_gen,
            fail_closed=config.moderation_fail_closed(),
        )
    except ModerationError as exc:
        return {"error": f"topic rejected: {exc.reason}"}, "rejected"
    slug, display = clean["slug"], clean["name"]
    existed = store.get_topic(slug) is not None
    store.add_topic(slug, display, (args.get("description") or "").strip())
    topic = store.get_topic(slug)
    # Subscribe now — the user asked for it; provisioning fills in the stories.
    store.subscribe(user_id, int(topic["id"]))

    # Build a brief during provisioning while the user is still in their initial
    # setup window (account age — reload-proof), so every topic they add then
    # populates the first Headlines. System bucket (shared artifact).
    building_brief = store.is_recent_user(
        user_id, config.onboard_brief_window_min() * 60
    )
    brief_generate = (
        metered_generate(store, SYSTEM_USER_ID, "rundown", topic_id=int(topic["id"]))
        if building_brief
        else None
    )

    run_id = store.create_run(
        user_id, slug, display, surface="chat",
        conversation_id=conversation_id, message_id=message_id,
    )
    # Query crafting is a cheap system call → Grok (Haiku fallback), not Haiku.
    query_generate = metered_relevance_generate(store, user_id, "discovery", int(topic["id"]))
    provision_runner.submit(
        store, run_id, slug, query_generate=query_generate,
        review_generate=review_generate, brief_generate=brief_generate,
    )

    yield {"type": "tool_start", "name": "create_topic"}
    yield {"type": "topic_run", "slug": slug, "name": display, "run_id": run_id, "stage": "discovering"}
    summary = f"setting up '{display}'…"
    yield {"type": "tool_end", "name": "create_topic", "summary": summary}
    return (
        {
            "created": not existed,
            "existed": existed,
            "slug": slug,
            "name": display,
            "subscribed": True,
            "status": "provisioning",
            # The pipeline is running in the background; the model should tell the
            # user we're setting it up now (not report final counts).
            "headline_ready": building_brief,
        },
        summary,
    )


def _find_sources_events(
    store: Store,
    user_id: int,
    args: dict[str, Any],
    *,
    conversation_id: str,
    message_id: str,
) -> Iterator[dict[str, Any]]:
    """Kick a background web search for sources (0030). Yields `tool_start`, a
    `search_run` (so the results card appears in the live message), then `tool_end`;
    returns `(result, summary)`. The search runs in the background + is polled, so
    it survives navigation. Budget-gated."""
    from . import discovery_runner

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "a search query is required"}, "missing query"

    gate = budget_status(store, user_id)
    if not gate["allowed"]:
        return {"error": gate["message"], "limit_reached": True}, "limit reached"

    run_id = store.create_discovery_run(
        user_id, query, conversation_id=conversation_id, message_id=message_id
    )
    # Query crafting is a cheap system call → Grok (Haiku fallback).
    query_generate = metered_relevance_generate(store, user_id, "discovery")
    discovery_runner.submit(store, run_id, query, query_generate=query_generate)

    yield {"type": "tool_start", "name": "find_sources"}
    yield {"type": "search_run", "run_id": run_id, "query": query, "stage": "searching"}
    summary = f"searching the web for sources on '{query}'…"
    yield {"type": "tool_end", "name": "find_sources", "summary": summary}
    return (
        {
            "status": "searching",
            "query": query,
            # The search runs in the background; a results card will appear. The model
            # should tell the user it's searching now (not report results yet).
            "note": "A results card with the found sources will appear shortly.",
        },
        summary,
    )


def _commit_sources(
    store: Store,
    user_id: int,
    conversation_id: str,
    moderate_generate: Callable[..., str] | None,
    review_generate: Callable[..., str] | None,
) -> tuple[dict[str, Any], str]:
    """Commit the conversation's latest finished source search (0030). Returns
    `(result, summary)` describing where the sources landed for the model to narrate."""
    from .discovery_commit import commit_discovery

    run = store.latest_committable_discovery(user_id, conversation_id)
    if not run:
        return {"error": "no pending source search to add"}, "nothing to add"
    decision = commit_discovery(
        store, run["id"], user_id,
        moderate_generate=moderate_generate or metered_generate(store, user_id, "moderation"),
        name_generate=metered_generate(store, user_id, "provision"),
        review_generate=review_generate,
    )
    if "error" in decision:
        return decision, decision["error"]
    where = ", ".join(t["name"] for t in decision["topics"]) or "a topic"
    verb = "created and added to" if decision["created_new"] else "added to"
    return decision, f"{verb} {where}"
