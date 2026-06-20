"""Dashboard API routes (`/api/*`) — Firebase-authenticated, read+write.

Attached to bbv2's FastAPI app alongside the consumer API. The token verifier is
injectable so the routes are testable offline.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from . import config
from .api import _bearer, _item_dict
from .moderation import ModerationError, moderate_topic
from .ratelimit import limiter
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
        # Owner-only admin: promote on ADMIN_EMAILS match; never demote.
        if email.lower() in config.admin_emails():
            store.set_user_role(email, "admin")
        row = store.get_user(email)
        role = row["role"] if row else "human"
        return {"id": uid, "email": email, "name": name, "role": role}

    return current_user


def add_dashboard_routes(
    app: FastAPI,
    store: Store,
    verifier: Verifier,
    *,
    moderate_generate: Any | None = None,
) -> None:
    """`moderate_generate` overrides the LLM used by topic moderation (tests
    inject a stub so creation never hits the network)."""
    current_user = _make_current_user(store, verifier)
    router = APIRouter(prefix="/api")

    def require_admin(user: dict = Depends(current_user)) -> dict[str, Any]:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin only")
        return user

    def _enforce_rate(action: str, user_id: int, conf: tuple[int, float]) -> None:
        limit, window = conf
        ok, retry = limiter.check((action, user_id), limit=limit, window_s=window)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — slow down.",
                headers={"Retry-After": str(int(retry) + 1)},
            )

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
        _enforce_rate("create", user["id"], config.ratelimit_topic_create())
        try:
            clean = moderate_topic(
                body.get("slug") or "",
                body.get("name") or body.get("slug") or "",
                moderate_generate,
                fail_closed=config.moderation_fail_closed(),
            )
        except ModerationError as exc:
            raise HTTPException(status_code=422, detail=exc.reason)
        slug, name = clean["slug"], clean["name"]
        existed = store.get_topic(slug) is not None
        store.add_topic(slug, name, body.get("description") or "")
        return {"ok": True, "slug": slug, "existed": existed}

    @router.post("/topics/{slug}/provision")
    def provision(slug: str, user: dict = Depends(current_user)) -> StreamingResponse:
        """User-driven: discover → auto-approve → collect, streamed as SSE stage
        events. Rate-limited; runs in the threadpool like /chat."""
        from .provision import provision_topic

        _enforce_rate("provision", user["id"], config.ratelimit_provision())
        _topic_or_404(slug)

        def gen():
            for ev in provision_topic(store, slug):
                yield f"data: {json.dumps(ev)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.post("/topics/{slug}/subscribe")
    def subscribe(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.subscribe(user["id"], int(_topic_or_404(slug)["id"]))
        return {"ok": True}

    @router.delete("/topics/{slug}/subscribe")
    def unsubscribe(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.unsubscribe(user["id"], int(_topic_or_404(slug)["id"]))
        return {"ok": True}

    @router.post("/topics/{slug}/discover")
    def discover(slug: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
        from .brave import DiscoveryError
        from .discovery import discover_sources

        _topic_or_404(slug)
        try:
            return discover_sources(store, slug)
        except DiscoveryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/topics/{slug}/collect")
    def collect_topic(slug: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
        from .collect import collect as run_collect

        _topic_or_404(slug)
        return run_collect(store, slug)

    @router.get("/topics/{slug}/sources")
    def sources(
        slug: str, status: str = "active", user: dict = Depends(require_admin)
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
    def approve(source_id: int, user: dict = Depends(require_admin)) -> dict[str, Any]:
        store.set_source_status(source_id, "active")
        return {"ok": True}

    @router.post("/sources/{source_id}/reject")
    def reject(source_id: int, user: dict = Depends(require_admin)) -> dict[str, Any]:
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
    def generate_brief(slug: str, user: dict = Depends(require_admin)) -> dict[str, Any]:
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

    # ---- chat / conversations ----
    def _conv_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": row["message_count"] if "message_count" in row.keys() else None,
        }

    @router.post("/conversations")
    def create_conversation(user: dict = Depends(current_user)) -> dict[str, Any]:
        cid = store.create_conversation(user["id"])
        return {"id": cid, "title": None, "message_count": 0}

    @router.get("/conversations")
    def list_conversations(user: dict = Depends(current_user)) -> dict[str, Any]:
        return {
            "conversations": [_conv_dict(r) for r in store.list_conversations(user["id"])]
        }

    def _conv_or_404(user_id: int, cid: str):
        conv = store.get_conversation(user_id, cid)
        if not conv:
            raise HTTPException(status_code=404, detail="unknown conversation")
        return conv

    @router.get("/conversations/{cid}")
    def get_conversation(cid: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        conv = _conv_or_404(user["id"], cid)
        messages = [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "tool_calls": json.loads(m["tool_calls_json"]) if m["tool_calls_json"] else [],
                "created_at": m["created_at"],
            }
            for m in store.get_messages(cid)
        ]
        return {
            "id": conv["id"],
            "title": conv["title"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "messages": messages,
        }

    @router.patch("/conversations/{cid}")
    def rename_conversation(
        cid: str, body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        _conv_or_404(user["id"], cid)
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title required")
        store.set_conversation_title(user["id"], cid, title[:80])
        return {"ok": True, "title": title[:80]}

    @router.delete("/conversations/{cid}")
    def delete_conversation(cid: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        if not store.delete_conversation(user["id"], cid):
            raise HTTPException(status_code=404, detail="unknown conversation")
        return {"ok": True}

    @router.post("/conversations/{cid}/messages")
    def post_message(
        cid: str, body: dict = Body(...), user: dict = Depends(current_user)
    ) -> StreamingResponse:
        from .agent import run_chat_turn

        _conv_or_404(user["id"], cid)
        text = (body.get("content") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="content required")

        def gen():
            for ev in run_chat_turn(store, user["id"], cid, text):
                yield f"data: {json.dumps(ev)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

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
