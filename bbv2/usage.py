"""Per-user token budget + metering helpers.

A single per-user daily budget covers the user's **own** agent work — chat, agent
tasks, and the topic provisioning they initiate. **System/background work**
(scheduled collection, source discovery, nightly briefs, shared on-demand
rundowns) is metered to a **system bucket** (`SYSTEM_USER_ID`) and never charged
to a real user.

`budget_status` decides whether a user may run more agent work; `meter_usage` /
`metered_generate` record spend (use `SYSTEM_USER_ID` for background work).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import config
from .llm import generate_text
from .store import Store

# Sentinel "owner" for background/system LLM spend — not a real user id (users
# autoincrement from 1), so it's naturally excluded from any user's budget.
SYSTEM_USER_ID = 0


def _window_start_iso(window_s: float) -> str:
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=window_s)
    return start.isoformat()


def meter_usage(store: Store, user_id: int, purpose: str, usage: Any, model: str | None) -> None:
    """Record an Anthropic/Grok `usage` block ({input_tokens, output_tokens})."""
    if not isinstance(usage, dict):
        return
    store.record_usage(
        user_id,
        purpose,
        model,
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
    )


def metered_generate(store: Store, user_id: int, purpose: str) -> Callable[..., str]:
    """A `generate_text` (Haiku) drop-in that meters each call's tokens to
    `user_id` (pass `SYSTEM_USER_ID` for background work)."""

    def _generate(prompt: str, **kwargs: Any) -> str:
        def _on_usage(usage: dict[str, Any], model: str) -> None:
            meter_usage(store, user_id, purpose, usage, model)

        return generate_text(prompt, on_usage=_on_usage, **kwargs)

    return _generate


def metered_relevance_generate(store: Store, user_id: int, purpose: str) -> Callable[..., str]:
    """Like `metered_generate` but routed to the cheap relevance model (Grok →
    Haiku fallback). Used for story relevance review (collection + provisioning)."""
    from .models import relevance_generate

    def _on_usage(usage: dict[str, Any], model: str) -> None:
        meter_usage(store, user_id, purpose, usage, model)

    return relevance_generate(on_usage=_on_usage)


def format_reset(seconds: float) -> str:
    """Human 'resets in …' phrase from a remaining-seconds value."""
    secs = max(0, int(seconds))
    if secs >= 3600:
        h = round(secs / 3600)
        return f"{h} hour{'s' if h != 1 else ''}"
    if secs >= 60:
        m = round(secs / 60)
        return f"{m} minute{'s' if m != 1 else ''}"
    return "less than a minute"


def budget_status(store: Store, user_id: int) -> dict[str, Any]:
    """Whether this user may run more agent work right now, plus usage figures.

    Returns: allowed, used, limit, window_s, resets_in (seconds until the oldest
    in-window usage rolls off), interactions, and a ready-made `message` on block.
    """
    cfg = config.token_budget()
    window_s = cfg["window_s"]
    limit = cfg["limit"]
    agg = store.usage_window(user_id, _window_start_iso(window_s))
    used = int(agg["total_tokens"])

    resets_in = 0.0
    earliest = agg.get("earliest_at")
    if earliest:
        try:
            earliest_dt = datetime.fromisoformat(earliest)
            elapsed = (datetime.now(timezone.utc) - earliest_dt).total_seconds()
            resets_in = max(0.0, window_s - elapsed)
        except (TypeError, ValueError):
            resets_in = window_s

    allowed = (not cfg["enabled"]) or used < limit
    message = None
    if not allowed:
        message = f"You've hit your daily usage limit — resets in {format_reset(resets_in)}."
    return {
        "allowed": allowed,
        "used": used,
        "limit": limit,
        "window_s": window_s,
        "resets_in": resets_in,
        "interactions": int(agg["interactions"]),
        "message": message,
    }
