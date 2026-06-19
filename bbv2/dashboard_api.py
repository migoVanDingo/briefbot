"""Dashboard API routes (`/api/*`) — Firebase-authenticated, read+write.

Attached to bbv2's FastAPI app alongside the consumer API. The token verifier is
injectable so the routes are testable offline.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException

from .api import _bearer, _item_dict
from .store import Store

Verifier = Callable[[str], dict[str, Any]]
MAX_LIMIT = 200


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
