"""Human-friendly labels for LLM-usage purposes (0027).

The `purpose` strings recorded in `token_usage` are terse internal tags. The admin
metrics surface answers "where are my tokens going and for what" — so it shows
these labels + one-line descriptions instead. Unknown purposes fall back to a
title-cased label.
"""

from __future__ import annotations

# purpose → (label, description). Keep in sync with the metering call sites
# (grep `metered_generate`/`record_usage`/`meter_usage` for the purpose strings).
PURPOSE_META: dict[str, tuple[str, str]] = {
    "chat": ("Agent chat", "Your conversations with the Briefbot chat agent."),
    "chat-turn": ("Chat turns", "Count of chat turns (no token cost of its own)."),
    "summarize": ("Article summaries", "On-demand article/paper summaries from chat."),
    "rundown": ("Topic rundowns", "On-demand 'today' brief built when you open a topic."),
    "brief": ("Brief generation", "Admin-triggered regeneration of a topic's brief."),
    "nightly": ("Nightly briefs", "The overnight per-topic briefs + email."),
    "discovery": ("Source discovery", "LLM crafting search queries to find new sources."),
    "provision": ("Topic provisioning", "Setting up a new topic (discover → review)."),
    "moderation": ("Topic moderation", "Safety/relevance check when creating a topic."),
    "review": ("Relevance review", "Filtering collected stories for topic relevance."),
    "relevance": ("Relevance review", "Scheduled relevance filtering during collection."),
    "image": ("Header images", "Grok Imagine topic/profile images (priced per image)."),
}


def purpose_label(purpose: str | None) -> str:
    if not purpose:
        return "Other"
    meta = PURPOSE_META.get(purpose)
    return meta[0] if meta else purpose.replace("-", " ").replace("_", " ").title()


def purpose_description(purpose: str | None) -> str:
    meta = PURPOSE_META.get(purpose or "")
    return meta[1] if meta else ""
