"""The `bbv2 nightly` job — build the morning briefs and email subscribers.

Run once a night (11pm) by cron, decoupled from the `tick` pull engine: it just
reads whatever stories `tick` has collected that day. For each topic with ≥1
subscriber it builds the brief (Haiku prose, metered to the **system** bucket —
not any user), then emails each email-enabled user a v1-style "your morning brief
is ready" with a link to the dashboard.

The brief generator + notifier are injectable for offline tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from . import config
from .brief import build_brief
from .notify import Notifier, default_notifier
from .store import Store
from .usage import SYSTEM_USER_ID, metered_generate


def render_brief_ready(user: Any, topics: list[Any]) -> str:
    names = ", ".join(t["name"] for t in topics)
    link = config.dashboard_url()
    return (
        f"Hi {user['name']},\n\n"
        f"Your morning brief is ready — {names}.\n\n"
        f"Read it: {link}/headlines\n"
    )


def run_nightly(
    store: Store,
    notifier: Notifier | None = None,
    *,
    brief_generate: Callable[..., str] | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    notifier = notifier or default_notifier()
    if brief_generate is None:
        brief_generate = metered_generate(store, SYSTEM_USER_ID, "nightly")
    now = now or datetime.now(timezone.utc)

    stats = {"topics_briefed": 0, "topics_skipped": 0, "emails_sent": 0}

    # 1) Build briefs for every topic that someone subscribes to.
    for t in store.topics_with_subscribers():
        try:
            brief = build_brief(store, t["slug"], generate=brief_generate, now=now)
        except Exception as exc:  # best-effort; one topic shouldn't sink the run
            print(f"[nightly] brief failed for {t['slug']}: {exc}")
            brief = None
        if brief is None:
            stats["topics_skipped"] += 1
            continue
        store.set_topic_briefed(t["slug"], now.replace(microsecond=0).isoformat())
        stats["topics_briefed"] += 1

    # 2) Email each email-enabled user with subscriptions: "brief ready".
    for user in store.users_with_email_enabled():
        subs = store.user_subscriptions(user["id"])
        if not subs:
            continue
        notifier.send(
            user["email"], "Your morning brief is ready", render_brief_ready(user, subs)
        )
        stats["emails_sent"] += 1

    return stats
