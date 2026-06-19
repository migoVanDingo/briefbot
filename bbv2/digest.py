"""Per-user recent-items digest (non-LLM; the LLM brief comes in a later phase).

For each email-enabled user, gather items from their subscribed topics newer than
their last digest, email them, and advance the checkpoint so the next run only
sends newer items.
"""

from __future__ import annotations

from typing import Any

from .notify import Notifier
from .store import Store


def render_digest(user: Any, items: list[Any]) -> str:
    lines = [f"Hi {user['name']}, here {'is' if len(items) == 1 else 'are'} "
             f"{len(items)} new item(s) from your topics:\n"]
    for it in items:
        when = it["published_at"] or it["fetched_at"]
        lines.append(f"- {it['title']}  [{it['source_name']}] — {when}")
        if it["url"]:
            lines.append(f"  {it['url']}")
    return "\n".join(lines)


def run_digests(store: Store, notifier: Notifier) -> dict[str, int]:
    stats = {"users": 0, "sent": 0, "skipped": 0}
    for user in store.users_with_email_enabled():
        stats["users"] += 1
        settings = store.get_user_settings(user["id"])
        items = store.items_for_user(
            user["id"],
            since_iso=settings["last_digest_at"],
            limit=settings["digest_limit"],
        )
        if not items:
            stats["skipped"] += 1
            continue
        subject = f"Your news digest ({len(items)} new)"
        notifier.send(user["email"], subject, render_digest(user, items))
        # items are newest-first → items[0].fetched_at is the new checkpoint.
        store.set_user_settings(user["id"], last_digest_at=items[0]["fetched_at"])
        stats["sent"] += 1
    return stats
