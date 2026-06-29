"""Headlines / stories / briefs routes for the dashboard API.

Split out of dashboard_api to keep that module under the 600-line cap. Mounted on
the dashboard router, so auth + the general per-user rate limit apply via the
router. `topic_or_404` is injected (it's a closure in dashboard_api)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException

from . import usage
from .api import _item_dict
from .dashboard_serial import serialize_brief, story_dict
from .moderation import sanitize_name
from .store import Store

MAX_LIMIT = 200  # matches the pre-split dashboard_api cap (was unintentionally halved)


def add_brief_routes(
    router: APIRouter,
    store: Store,
    current_user: Callable[..., dict[str, Any]],
    require_brief: Callable[..., dict[str, Any]],
    topic_or_404: Callable[[str], Any],
) -> None:
    @router.get("/headlines")
    def headlines(limit: int = 50, user: dict = Depends(current_user)) -> dict[str, Any]:
        rows = store.items_for_user(user["id"], limit=max(1, min(limit, MAX_LIMIT)))
        return {"items": [_item_dict(r) for r in rows]}

    @router.get("/topics/{slug}/items")
    def topic_items(
        slug: str,
        since: str | None = None,
        limit: int = 50,
        user: dict = Depends(current_user),
    ) -> dict[str, Any]:
        rows = store.items_for_topic(slug, since_iso=since, limit=max(1, min(limit, MAX_LIMIT)))
        return {"items": [_item_dict(r) for r in rows]}

    @router.get("/stories/sources")
    def story_sources(user: dict = Depends(current_user)) -> dict[str, Any]:
        return {"sources": store.story_sources(user["id"])}

    @router.post("/stories")
    def query_stories(
        body: dict = Body(default={}), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        limit = int(body.get("limit") or 30)
        rows = store.query_stories(
            user["id"],
            search=sanitize_name(body.get("search") or "") or None,  # strip tags/ctrl
            source_name=(body.get("source") or "").strip() or None,
            topic_slug=(body.get("topic") or "").strip() or None,
            from_iso=(body.get("from") or "").strip() or None,
            to_iso=(body.get("to") or "").strip() or None,
            order=body.get("order") or "desc",
            limit=max(1, min(limit, MAX_LIMIT)),
        )
        return {"items": [story_dict(r) for r in rows]}

    @router.post("/stories/feedback")
    def story_feedback(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        item_id = (body.get("item_id") or "").strip()
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id required")
        vote = int(body.get("vote") or 0)
        if vote not in (-1, 0, 1):
            raise HTTPException(status_code=400, detail="vote must be -1, 0, or 1")
        store.set_story_feedback(user["id"], item_id, vote)
        return {"ok": True, "item_id": item_id, "vote": vote}

    @router.post("/stories/click", status_code=204)
    def story_click(body: dict = Body(...), user: dict = Depends(current_user)) -> None:
        """Best-effort engagement beacon (0021): record that the user opened a
        story's link. Fire-and-forget from the frontend; never blocks navigation."""
        item_id = (body.get("item_id") or "").strip()
        if item_id:
            store.record_click(user["id"], item_id)

    @router.get("/briefs")
    def briefs(user: dict = Depends(current_user)) -> dict[str, Any]:
        """The landing brief: latest brief per subscribed topic, plus the tab list."""
        from . import topic_image

        subs = store.user_subscriptions(user["id"])
        out = []
        for t in subs:
            b = store.latest_brief(int(t["id"]))
            if b:
                topic_image.maybe_kick(store, t, b)  # per-day image, background
                out.append(serialize_brief(t, b))
        return {
            "briefs": out,
            "topics": [{"slug": t["slug"], "name": t["name"]} for t in subs],
        }

    @router.get("/topics/{slug}/briefs")
    def topic_briefs(
        slug: str, limit: int = 10, user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        """The Headlines date rail: the most recent days that HAVE a brief (newest
        first, capped at `limit`), plus **today** at the top as the entry point
        (its brief is null here until the rundown endpoint builds it on demand).
        Read-only; never triggers an LLM build."""
        topic = topic_or_404(slug)
        limit = max(1, min(limit, 30))
        today = datetime.now(timezone.utc).date().isoformat()
        rows = store.recent_briefs(int(topic["id"]), limit)
        if rows:  # per-day image for the latest brief, seeded from its summary
            from . import topic_image

            topic_image.maybe_kick(store, topic, rows[0])
        by_date = {r["date"]: r for r in rows}
        dates = [today] if today not in by_date else []
        dates += [r["date"] for r in rows]
        dates = dates[:limit]  # newest-first; today is >= every brief date
        return {
            "days": [
                {"date": d, "brief": serialize_brief(topic, by_date[d]) if d in by_date else None}
                for d in dates
            ]
        }

    @router.get("/topics/{slug}/briefs/{date}/stories")
    def brief_stories(
        slug: str, date: str, user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        """The stories behind a given day's brief — the exact items the brief was
        built from (its persisted `sources`), hydrated with the user's vote/save
        state. Decoupled from the brief's *label* date: a nightly brief is dated for
        the next day, but its source items were collected earlier, so a date-range
        query would (correctly) find nothing. Empty list if that day has no brief."""
        topic = topic_or_404(slug)
        brief = store.get_brief(int(topic["id"]), date)
        if brief is None:
            return {"items": []}
        sources = json.loads(brief["sources_json"] or "[]")
        item_ids = [s["item_id"] for s in sources if s.get("item_id")]
        rows = store.stories_by_ids(user["id"], item_ids)
        return {"items": [story_dict(r) for r in rows]}

    @router.post("/topics/{slug}/brief")
    def generate_brief(slug: str, user: dict = Depends(require_brief)) -> dict[str, Any]:
        """Generate (Haiku) + persist a topic's brief now — replaces today's brief.
        Reflected on Headlines on its next load (no live push). Admin affordance."""
        from .brief import build_brief

        topic = topic_or_404(slug)
        gen = usage.metered_generate(store, usage.SYSTEM_USER_ID, "brief", int(topic["id"]))
        try:
            b = build_brief(store, slug, generate=gen)
        except Exception as exc:  # surface LLM/key errors to the caller
            raise HTTPException(status_code=400, detail=str(exc))
        if b is None:
            raise HTTPException(status_code=400, detail="no recent items to summarize")
        return {"ok": True, "title": b["title"]}

    @router.post("/topics/{slug}/rundown")
    def topic_rundown(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        """On-demand topic rundown — built once per topic/day, then shared. The
        first visitor that day triggers synthesis; later visitors read the cache.
        Metered to the system bucket (shared artifact, not the unlucky viewer)."""
        from .brief import get_or_build_brief

        topic = topic_or_404(slug)
        gen = usage.metered_generate(store, usage.SYSTEM_USER_ID, "rundown")
        try:
            row = get_or_build_brief(store, slug, generate=gen)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if row is None:
            return {"rundown": None, "reason": "no recent items to summarize"}
        from . import topic_image

        topic_image.maybe_kick(store, topic, row)  # per-day image, background
        return {"rundown": serialize_brief(topic, row)}
