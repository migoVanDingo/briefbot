"""Dashboard API routes (`/api/*`) — Firebase-authenticated, read+write.

Attached to bbv2's FastAPI app alongside the consumer API. The token verifier is
injectable so the routes are testable offline.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException

from .api import _bearer, _item_dict
from .store import Store

Verifier = Callable[[str], dict[str, Any]]
MAX_LIMIT = 200


def _serialize_brief(topic_row: Any, brief_row: Any) -> dict[str, Any]:
    return {
        "topic_slug": topic_row["slug"],
        "topic_name": topic_row["name"],
        "date": brief_row["date"],
        "title": brief_row["title"],
        "summary": brief_row["summary"],
        "trending": json.loads(brief_row["trending_json"] or "[]"),
        "sources": json.loads(brief_row["sources_json"] or "[]"),
    }


def _make_current_user(store: Store, verifier: Verifier):
    def current_user(authorization: str = Header(default="")) -> dict[str, Any]:
        token = _bearer(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            claims = verifier(token)
        except Exception:
            raise HTTPException(status_code=401, detail="invalid token")
        email = claims.get("email")
        if not email:
            raise HTTPException(status_code=401, detail="token has no email")
        name = claims.get("name") or email.split("@")[0]
        uid = store.add_user(name, email)  # upsert (auto-provision)
        return {"id": uid, "email": email, "name": name}

    return current_user


def add_dashboard_routes(app: FastAPI, store: Store, verifier: Verifier) -> None:
    current_user = _make_current_user(store, verifier)
    router = APIRouter(prefix="/api")

    def _topic_or_404(slug: str):
        topic = store.get_topic(slug)
        if not topic:
            raise HTTPException(status_code=404, detail="unknown topic")
        return topic

    @router.get("/me")
    def me(user: dict = Depends(current_user)) -> dict[str, Any]:
        s = store.get_user_settings(user["id"])
        subs = [t["slug"] for t in store.user_subscriptions(user["id"])]
        return {
            "user": user,
            "settings": {
                "email_enabled": bool(s["email_enabled"]),
                "digest_limit": s["digest_limit"],
            },
            "subscriptions": subs,
        }

    @router.get("/topics")
    def topics(user: dict = Depends(current_user)) -> dict[str, Any]:
        subs = {t["slug"] for t in store.user_subscriptions(user["id"])}
        return {
            "topics": [
                {
                    "slug": t["slug"],
                    "name": t["name"],
                    "description": t["description"],
                    "subscribed": t["slug"] in subs,
                }
                for t in store.list_topics()
            ]
        }

    @router.post("/topics")
    def create_topic(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        slug = (body.get("slug") or "").strip()
        if not slug:
            raise HTTPException(status_code=400, detail="slug required")
        store.add_topic(slug, body.get("name") or slug, body.get("description") or "")
        return {"ok": True, "slug": slug}

    @router.post("/topics/{slug}/subscribe")
    def subscribe(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.subscribe(user["id"], int(_topic_or_404(slug)["id"]))
        return {"ok": True}

    @router.delete("/topics/{slug}/subscribe")
    def unsubscribe(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.unsubscribe(user["id"], int(_topic_or_404(slug)["id"]))
        return {"ok": True}

    @router.post("/topics/{slug}/discover")
    def discover(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        from .brave import DiscoveryError
        from .discovery import discover_sources

        _topic_or_404(slug)
        try:
            return discover_sources(store, slug)
        except DiscoveryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/topics/{slug}/collect")
    def collect_topic(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        from .collect import collect as run_collect

        _topic_or_404(slug)
        return run_collect(store, slug)

    @router.get("/topics/{slug}/sources")
    def sources(
        slug: str, status: str = "active", user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        if status == "candidate":
            rows = store.list_candidates(slug)
        else:
            rows = [s for s in store.list_sources(slug) if s["status"] == status]
        return {
            "sources": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "url": s["url"],
                    "type": s["type"],
                    "status": s["status"],
                }
                for s in rows
            ]
        }

    @router.post("/sources/{source_id}/approve")
    def approve(source_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.set_source_status(source_id, "active")
        return {"ok": True}

    @router.post("/sources/{source_id}/reject")
    def reject(source_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.set_source_status(source_id, "rejected")
        return {"ok": True}

    @router.get("/headlines")
    def headlines(
        limit: int = 50, user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        rows = store.items_for_user(user["id"], limit=max(1, min(limit, MAX_LIMIT)))
        return {"items": [_item_dict(r) for r in rows]}

    @router.get("/topics/{slug}/items")
    def topic_items(
        slug: str,
        since: str | None = None,
        limit: int = 50,
        user: dict = Depends(current_user),
    ) -> dict[str, Any]:
        rows = store.items_for_topic(
            slug, since_iso=since, limit=max(1, min(limit, MAX_LIMIT))
        )
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
            search=(body.get("search") or "").strip() or None,
            source_name=(body.get("source") or "").strip() or None,
            from_iso=(body.get("from") or "").strip() or None,
            to_iso=(body.get("to") or "").strip() or None,
            order=body.get("order") or "desc",
            limit=max(1, min(limit, MAX_LIMIT)),
        )
        return {
            "items": [
                {**_item_dict(r), "feedback_vote": r["feedback_vote"]} for r in rows
            ]
        }

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

    @router.get("/briefs")
    def briefs(user: dict = Depends(current_user)) -> dict[str, Any]:
        """The landing brief: latest brief per subscribed topic, plus the tab list."""
        subs = store.user_subscriptions(user["id"])
        out = []
        for t in subs:
            b = store.latest_brief(int(t["id"]))
            if b:
                out.append(_serialize_brief(t, b))
        return {
            "briefs": out,
            "topics": [{"slug": t["slug"], "name": t["name"]} for t in subs],
        }

    @router.post("/topics/{slug}/brief")
    def generate_brief(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        """Generate (Haiku) + persist a topic's brief now. Admin/test affordance."""
        from .brief import build_brief

        _topic_or_404(slug)
        try:
            b = build_brief(store, slug)
        except Exception as exc:  # surface LLM/key errors to the caller
            raise HTTPException(status_code=400, detail=str(exc))
        if b is None:
            raise HTTPException(status_code=400, detail="no recent items to summarize")
        return {"ok": True, "title": b["title"]}

    @router.get("/favorites/folders")
    def favorite_folders(user: dict = Depends(current_user)) -> dict[str, Any]:
        rows = store.list_folders(user["id"])
        if not rows:  # always surface at least the default folder
            store.ensure_default_folder(user["id"])
            rows = store.list_folders(user["id"])
        return {
            "folders": [
                {"id": r["id"], "name": r["name"], "count": r["count"]} for r in rows
            ]
        }

    @router.post("/favorites/folders")
    def create_folder(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        fid = store.create_folder(user["id"], name)
        return {"ok": True, "id": fid, "name": name}

    @router.get("/favorites/items")
    def favorite_items(
        folder_id: str = "", user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        fid = folder_id or store.ensure_default_folder(user["id"])
        folder = store.get_folder(user["id"], fid)
        if not folder:
            raise HTTPException(status_code=404, detail="unknown folder")
        rows = store.list_favorites(user["id"], fid)
        return {
            "folder": {"id": folder["id"], "name": folder["name"]},
            "items": [
                {
                    "id": r["id"],
                    "item_id": r["item_id"],
                    "title": r["title"],
                    "url": r["url"],
                }
                for r in rows
            ],
        }

    @router.post("/favorites/items")
    def add_favorite(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        title = (body.get("title") or "").strip()
        url = (body.get("url") or "").strip()
        if not title or not url:
            raise HTTPException(status_code=400, detail="title and url required")
        fid = (body.get("folder_id") or "").strip() or store.ensure_default_folder(
            user["id"]
        )
        if not store.get_folder(user["id"], fid):
            raise HTTPException(status_code=404, detail="unknown folder")
        row = store.add_favorite(
            user["id"], fid, title, url, (body.get("item_id") or None)
        )
        return {"ok": True, "id": row["id"], "folder_id": fid}

    @router.delete("/favorites/items")
    def remove_favorite(
        favorite_id: str = "", user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        if not favorite_id:
            raise HTTPException(status_code=400, detail="favorite_id required")
        if not store.remove_favorite(user["id"], favorite_id):
            raise HTTPException(status_code=404, detail="unknown favorite")
        return {"ok": True}

    @router.get("/settings")
    def get_settings(user: dict = Depends(current_user)) -> dict[str, Any]:
        s = store.get_user_settings(user["id"])
        return {
            "email_enabled": bool(s["email_enabled"]),
            "digest_limit": s["digest_limit"],
        }

    @router.put("/settings")
    def put_settings(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        store.set_user_settings(
            user["id"],
            email_enabled=body.get("email_enabled"),
            digest_limit=body.get("digest_limit"),
        )
        return {"ok": True}

    app.include_router(router)
