"""Dashboard API routes (`/api/*`) — Firebase-authenticated, read+write.

Attached to bbv2's FastAPI app alongside the consumer API. The token verifier is
injectable so the routes are testable offline.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from . import config, rbac, usage
from .api import _bearer, _item_dict
from .authjwt import decode_access_token
from .dashboard_chat import add_chat_routes
from .dashboard_favorites import add_favorite_routes
from .dashboard_metrics import add_metrics_routes
from .dashboard_prefs import add_prefs_routes
from .dashboard_schedule import add_schedule_routes
from .moderation import ModerationError, moderate_topic, sanitize_name
from .ratelimit import limiter
from .store import Store
from .util import titlecase

Verifier = Callable[[str], dict[str, Any]]
MAX_LIMIT = 200


def _opt_int(v: Any) -> int | None:
    """Parse an optional integer field; '' / None / junk → None (clear override)."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _topic_image_status(topic_row: Any) -> str:
    return (topic_row["image_status"] if "image_status" in topic_row.keys() else "none") or "none"


def _serialize_brief(topic_row: Any, brief_row: Any) -> dict[str, Any]:
    status = _topic_image_status(topic_row)
    return {
        "topic_slug": topic_row["slug"],
        "topic_name": topic_row["name"],
        "date": brief_row["date"],
        "title": brief_row["title"],
        "summary": brief_row["summary"],
        # Per-topic Grok Imagine header image (0024).
        "image_status": status,
        "image_url": f"/api/topics/{topic_row['slug']}/image" if status == "ready" else None,
        "trending": json.loads(brief_row["trending_json"] or "[]"),
        "sources": json.loads(brief_row["sources_json"] or "[]"),
    }


def _make_current_user(store: Store):
    """Dependency: authenticate via bbv2's OWN access token (0019), read from the
    HttpOnly `access` cookie or an `Authorization: Bearer <access-jwt>` header.
    The Firebase token is exchanged once at /api/auth/exchange — never here."""

    def current_user(request: Request) -> dict[str, Any]:
        token = request.cookies.get(config.cookie_access_name()) or _bearer(
            request.headers.get("authorization", "")
        )
        if not token:
            raise HTTPException(status_code=401, detail="not authenticated")
        try:
            claims = decode_access_token(token)
            uid = int(claims["sub"])
        except Exception:
            raise HTTPException(status_code=401, detail="invalid or expired session")
        sid = claims.get("sid")
        # Immediate revocation: a force-logged-out session stops working at once.
        if not sid or not store.session_active(sid):
            raise HTTPException(status_code=401, detail="session revoked")
        row = store.get_user_by_id(uid)
        if not row:
            raise HTTPException(status_code=401, detail="unknown user")
        if (row["status"] or "active") != "active":
            raise HTTPException(status_code=403, detail="account disabled")
        caps = rbac.global_capabilities(row["role"])
        return {
            "id": uid,
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "capabilities": sorted(caps),
            "session_id": sid,
        }

    return current_user


def add_dashboard_routes(
    app: FastAPI,
    store: Store,
    verifier: Verifier,
    *,
    moderate_generate: Any | None = None,
) -> None:
    """`moderate_generate` overrides the LLM used by topic moderation (tests
    inject a stub so creation never hits the network). `verifier` is the Firebase
    ID-token verifier — used only by the auth-exchange route, not per request."""
    current_user = _make_current_user(store)
    router = APIRouter(prefix="/api")

    def require_capability(cap: str):
        """Dependency factory: 403 unless the caller holds `cap` (owner has '*')."""

        def dep(user: dict = Depends(current_user)) -> dict[str, Any]:
            if not rbac.has_capability(set(user["capabilities"]), cap):
                raise HTTPException(status_code=403, detail="forbidden")
            return user

        return dep

    # Capability-gated dependencies replacing the old role=='admin' check. Owner
    # and admin both satisfy these (admin holds the curation caps; owner holds '*').
    require_curate = require_capability("topics:curate")
    require_sources = require_capability("sources:approve")
    require_brief = require_capability("brief:generate")
    require_cadence = require_capability("cadence:set")
    require_metrics = require_capability("metrics:read")

    def _enforce_rate(action: str, user_id: int, conf: tuple[int, float]) -> None:
        limit, window = conf
        ok, retry = limiter.check((action, user_id), limit=limit, window_s=window)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — slow down.",
                headers={"Retry-After": str(int(retry) + 1)},
            )

    def _rate_limited(user: dict = Depends(current_user)) -> dict[str, Any]:
        """Router-wide general per-user rate limit (every `/api/*` route).
        `current_user` is dependency-cached, so this reuses the same auth result."""
        _enforce_rate("api", user["id"], config.ratelimit_default())
        return user

    def _enforce_budget(user_id: int) -> None:
        status = usage.budget_status(store, user_id)
        if not status["allowed"]:
            raise HTTPException(
                status_code=429,
                detail=status["message"],
                headers={"Retry-After": str(int(status["resets_in"]) + 1)},
            )

    def _topic_or_404(slug: str):
        topic = store.get_topic(slug)
        if not topic:
            raise HTTPException(status_code=404, detail="unknown topic")
        return topic

    @router.get("/me")
    def me(user: dict = Depends(current_user)) -> dict[str, Any]:
        from .agent import GREETING

        s = store.get_user_settings(user["id"])
        subs = [t["slug"] for t in store.user_subscriptions(user["id"])]
        onboarded = bool(s["onboarded_at"])
        # Onboarding completes when the user RETURNS with topics set up. `/me` is
        # fetched once per session (on auth), so a first session — where they had no
        # topics at login — stays "not onboarded" the whole time, letting every
        # topic they add build the first Headlines. From the next session on, they're
        # onboarded and new topics defer to nightly + on-demand rundowns.
        if subs and not onboarded:
            store.mark_onboarded(user["id"])
            onboarded = True
        # Don't leak the internal session id in the profile payload.
        pub_user = {k: user[k] for k in ("id", "email", "name", "role", "capabilities")}
        return {
            "user": pub_user,
            "settings": {
                "email_enabled": bool(s["email_enabled"]),
                "digest_limit": s["digest_limit"],
            },
            # UI state that now lives in the DB (0018), not localStorage.
            "preferences": {"theme": s["theme"], "accent": s["accent"]},
            "flags": sorted(store.get_user_flags(user["id"])),
            "subscriptions": subs,
            "onboarded": onboarded,
            "greeting": GREETING,
        }

    @router.post("/me/onboarded")
    def set_onboarded(user: dict = Depends(current_user)) -> dict[str, Any]:
        """Mark the first-visit onboarding tour complete (one-time)."""
        store.mark_onboarded(user["id"])
        return {"ok": True}

    @router.get("/usage")
    def get_usage(user: dict = Depends(current_user)) -> dict[str, Any]:
        """The signed-in user's token spend over the budget window, for the chat
        sidebar counter. A single per-user daily budget (system work excluded)."""
        st = usage.budget_status(store, user["id"])
        return {
            "interactions": st["interactions"],
            "tokens_used": st["used"],
            "limit": st["limit"],
            "window_s": st["window_s"],
            "resets_in": int(st["resets_in"]),
            "enabled": config.token_budget()["enabled"],
            "blocked": not st["allowed"],
        }

    @router.get("/spaces")
    def list_spaces(user: dict = Depends(current_user)) -> dict[str, Any]:
        """The caller's spaces + their membership role (0019 foundation). Every
        user has at least a personal space, created at first login."""
        return {
            "spaces": [
                {
                    "id": s["id"],
                    "type": s["type"],
                    "name": s["name"],
                    "role": s["role"],
                    "is_owner": s["owner_user_id"] == user["id"],
                }
                for s in store.user_spaces(user["id"])
            ]
        }

    @router.get("/topics")
    def topics(user: dict = Depends(current_user)) -> dict[str, Any]:
        subs = {t["slug"] for t in store.user_subscriptions(user["id"])}
        is_admin = rbac.has_capability(set(user["capabilities"]), "admin:read")
        return {
            "topics": [
                {
                    "slug": t["slug"],
                    "name": t["name"],
                    "description": t["description"],
                    "subscribed": t["slug"] in subs,
                    # Cadence is admin-only context for the cadence controls.
                    **(
                        {
                            "discover_interval_min": t["discover_interval_min"],
                            "collect_interval_min": t["collect_interval_min"],
                            "last_discovered_at": t["last_discovered_at"],
                        }
                        if is_admin
                        else {}
                    ),
                }
                for t in store.list_topics()
            ]
        }

    @router.post("/topics")
    def create_topic(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        _enforce_rate("create", user["id"], config.ratelimit_topic_create())
        _enforce_budget(user["id"])
        # Meter the moderation LLM call to the acting user (tests inject a stub).
        mod_gen = moderate_generate or usage.metered_generate(store, user["id"], "moderation")
        try:
            clean = moderate_topic(
                body.get("slug") or "",
                body.get("name") or body.get("slug") or "",
                mod_gen,
                fail_closed=config.moderation_fail_closed(),
            )
        except ModerationError as exc:
            raise HTTPException(status_code=422, detail=exc.reason)
        slug, name = clean["slug"], titlecase(clean["name"])
        existed = store.get_topic(slug) is not None
        store.add_topic(slug, name, body.get("description") or "")
        return {"ok": True, "slug": slug, "name": name, "existed": existed}

    def _run_dict(r: Any) -> dict[str, Any]:
        return {
            "id": r["id"],
            "slug": r["topic_slug"],
            "name": r["topic_name"],
            "stage": r["stage"],
            "status": r["status"],
            "failed": r["status"] == "error",
            "error": r["error"],
            "surface": r["surface"],
            "conversation_id": r["conversation_id"],
            "message_id": r["message_id"],
        }

    @router.post("/topics/{slug}/provision")
    def provision(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        """User-driven: discover → approve → collect → review as a **background run**
        (0023). Returns the run id immediately; the client polls `/api/provisioning`
        for live stage progress. Rate-limited + budget-checked."""
        from . import provision_runner

        _enforce_rate("provision", user["id"], config.ratelimit_provision())
        _enforce_budget(user["id"])
        topic = _topic_or_404(slug)
        tid = int(topic["id"])
        # Query crafting is a cheap system call → Grok (Haiku fallback), not Haiku.
        query_generate = usage.metered_relevance_generate(store, user["id"], "discovery", tid)
        review_generate = usage.metered_relevance_generate(store, user["id"], "provision", tid)
        # Build the first brief only during the initial setup window (account age);
        # afterwards nightly + on-demand rundowns cover new topics (no per-add cost).
        brief_generate = (
            usage.metered_generate(store, usage.SYSTEM_USER_ID, "rundown", tid)
            if store.is_recent_user(user["id"], config.onboard_brief_window_min() * 60)
            else None
        )
        run_id = store.create_run(user["id"], slug, topic["name"], surface="topics")
        provision_runner.submit(
            store, run_id, slug, query_generate=query_generate,
            review_generate=review_generate, brief_generate=brief_generate,
        )
        return {"run_id": run_id}

    @router.get("/provisioning")
    def provisioning(
        conversation: str | None = None, user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        """The caller's in-progress + just-finished provision runs (0023) — the poll
        source for the chat pills and the Topics-page cards."""
        if conversation:
            rows = store.runs_for_conversation(user["id"], conversation)
        else:
            rows = store.runs_for_user(user["id"])
        return {"runs": [_run_dict(r) for r in rows]}

    @router.post("/topics/{slug}/subscribe")
    def subscribe(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.subscribe(user["id"], int(_topic_or_404(slug)["id"]))
        return {"ok": True}

    @router.delete("/topics/{slug}/subscribe")
    def unsubscribe(slug: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        store.unsubscribe(user["id"], int(_topic_or_404(slug)["id"]))
        return {"ok": True}

    @router.post("/topics/{slug}/discover")
    def discover(slug: str, user: dict = Depends(require_curate)) -> dict[str, Any]:
        from .brave import DiscoveryError
        from .discovery import discover_sources

        topic = _topic_or_404(slug)
        # Use the LLM (Grok) query crafter + retry, same as the chat/provision path.
        query_gen = usage.metered_relevance_generate(store, user["id"], "discovery", int(topic["id"]))
        try:
            return discover_sources(store, slug, generate=query_gen)
        except DiscoveryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/topics/{slug}/collect")
    def collect_topic(slug: str, user: dict = Depends(require_curate)) -> dict[str, Any]:
        from .collect import collect as run_collect
        from .review import quickscan_topic

        topic = _topic_or_404(slug)
        stats = run_collect(store, slug)
        # Run the relevance review too (mirrors `tick`/provision) so off-topic items
        # the feeds carried are filtered out — otherwise unreviewed items show.
        review_gen = usage.metered_relevance_generate(store, user["id"], "review", int(topic["id"]))
        try:
            review = quickscan_topic(store, slug, generate=review_gen)
            stats = {**stats, "reviewed": review.get("reviewed", 0), "dropped": review.get("dropped", 0)}
        except Exception:  # best-effort — collection already succeeded
            pass
        return stats

    @router.get("/topics/{slug}/sources")
    def sources(
        slug: str, status: str = "active", user: dict = Depends(require_sources)
    ) -> dict[str, Any]:
        if status == "candidate":
            rows = store.list_candidates(slug)
        elif status == "managed":  # approved sources, active + paused (0020 admin)
            rows = [s for s in store.list_sources(slug) if s["status"] in ("active", "disabled")]
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
                    "collect_interval_min": s["collect_interval_min"],
                    "last_collected_at": s["last_collected_at"],
                }
                for s in rows
            ]
        }

    @router.post("/sources/{source_id}/approve")
    def approve(source_id: int, user: dict = Depends(require_sources)) -> dict[str, Any]:
        store.set_source_status(source_id, "active")
        return {"ok": True}

    @router.post("/sources/{source_id}/reject")
    def reject(source_id: int, user: dict = Depends(require_sources)) -> dict[str, Any]:
        store.set_source_status(source_id, "rejected")
        return {"ok": True}

    @router.post("/sources/{source_id}/disable")
    def disable_source(source_id: int, user: dict = Depends(require_sources)) -> dict[str, Any]:
        """Pause an active source (excluded from collection until re-enabled)."""
        store.set_source_status(source_id, "disabled")
        return {"ok": True}

    @router.post("/sources/{source_id}/enable")
    def enable_source(source_id: int, user: dict = Depends(require_sources)) -> dict[str, Any]:
        store.set_source_status(source_id, "active")
        return {"ok": True}

    @router.delete("/sources/{source_id}")
    def delete_source(source_id: int, user: dict = Depends(require_sources)) -> dict[str, Any]:
        """Remove a source entirely (and its topic links). Collected items remain."""
        store.delete_source(source_id)
        return {"ok": True}

    @router.post("/topics/{slug}/sources/approve-all")
    def approve_all(slug: str, user: dict = Depends(require_sources)) -> dict[str, Any]:
        """Approve every candidate source on a topic in one transaction — avoids
        the frontend firing N parallel approve POSTs."""
        approved = store.approve_all_candidates(slug)
        return {"ok": True, "approved": approved}

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
            search=sanitize_name(body.get("search") or "") or None,  # strip tags/ctrl
            source_name=(body.get("source") or "").strip() or None,
            topic_slug=(body.get("topic") or "").strip() or None,
            from_iso=(body.get("from") or "").strip() or None,
            to_iso=(body.get("to") or "").strip() or None,
            order=body.get("order") or "desc",
            limit=max(1, min(limit, MAX_LIMIT)),
        )
        return {
            "items": [
                {
                    **_item_dict(r),
                    "feedback_vote": r["feedback_vote"],
                    "is_saved": bool(r["is_saved"]),
                }
                for r in rows
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
                topic_image.maybe_kick(store, t, b["summary"])  # one-time, background
                out.append(_serialize_brief(t, b))
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
        topic = _topic_or_404(slug)
        limit = max(1, min(limit, 30))
        today = datetime.now(timezone.utc).date().isoformat()
        rows = store.recent_briefs(int(topic["id"]), limit)
        if rows:  # one-time, background image gen seeded from the latest brief
            from . import topic_image

            topic_image.maybe_kick(store, topic, rows[0]["summary"])
        by_date = {r["date"]: r for r in rows}
        dates = [today] if today not in by_date else []
        dates += [r["date"] for r in rows]
        dates = dates[:limit]  # newest-first; today is >= every brief date
        return {
            "days": [
                {"date": d, "brief": _serialize_brief(topic, by_date[d]) if d in by_date else None}
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
        topic = _topic_or_404(slug)
        brief = store.get_brief(int(topic["id"]), date)
        if brief is None:
            return {"items": []}
        sources = json.loads(brief["sources_json"] or "[]")
        item_ids = [s["item_id"] for s in sources if s.get("item_id")]
        rows = store.stories_by_ids(user["id"], item_ids)
        return {
            "items": [
                {**_item_dict(r), "feedback_vote": r["feedback_vote"], "is_saved": bool(r["is_saved"])}
                for r in rows
            ]
        }

    @router.post("/topics/{slug}/brief")
    def generate_brief(slug: str, user: dict = Depends(require_brief)) -> dict[str, Any]:
        """Generate (Haiku) + persist a topic's brief now — replaces today's brief.
        Reflected on Headlines on its next load (no live push). Admin affordance."""
        from .brief import build_brief

        topic = _topic_or_404(slug)
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

        topic = _topic_or_404(slug)
        gen = usage.metered_generate(store, usage.SYSTEM_USER_ID, "rundown")
        try:
            row = get_or_build_brief(store, slug, generate=gen)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if row is None:
            return {"rundown": None, "reason": "no recent items to summarize"}
        from . import topic_image

        topic_image.maybe_kick(store, topic, row["summary"])  # one-time, background
        return {"rundown": _serialize_brief(topic, row)}

    @router.patch("/topics/{slug}/cadence")
    def set_topic_cadence(
        slug: str, body: dict = Body(...), user: dict = Depends(require_cadence)
    ) -> dict[str, Any]:
        """Admin: per-topic source-discovery + story-collection cadence (minutes;
        0/empty clears the override → default)."""
        _topic_or_404(slug)
        store.set_topic_cadence(
            slug,
            discover_interval_min=_opt_int(body.get("discover_interval_min")),
            collect_interval_min=_opt_int(body.get("collect_interval_min")),
        )
        return {"ok": True}

    @router.patch("/sources/{source_id}/cadence")
    def set_source_cadence(
        source_id: int, body: dict = Body(...), user: dict = Depends(require_cadence)
    ) -> dict[str, Any]:
        """Admin: per-source story-collection cadence override (minutes)."""
        store.set_source_cadence(source_id, _opt_int(body.get("collect_interval_min")))
        return {"ok": True}

    add_favorite_routes(router, store, current_user)
    add_prefs_routes(router, store, current_user)  # 0018 theme/flags
    add_chat_routes(router, store, current_user, moderate_generate)  # chat/conversations
    add_schedule_routes(router, store, require_cadence)  # 0020 admin scheduling + caps
    add_metrics_routes(router, store, require_metrics)  # 0021 admin metrics

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

    # Public (no auth): a topic's generated header image (0024). Mounted on `app`
    # rather than `router` so an <img> tag can load it cross-origin in dev without
    # the session cookie. The image is a non-sensitive AI illustration.
    @app.get("/api/topics/{slug}/image")
    def topic_image_file(slug: str):
        row = store.get_topic(slug)
        path = row["image_path"] if row and "image_path" in row.keys() else None
        status = row["image_status"] if row and "image_status" in row.keys() else "none"
        if status != "ready" or not path or not os.path.exists(path):
            raise HTTPException(status_code=404, detail="no image")
        return FileResponse(path, media_type="image/jpeg")

    app.include_router(router, dependencies=[Depends(_rate_limited)])

    # Auth (exchange/session/logout) + owner-only user management. Mounted WITHOUT
    # the per-user rate-limit dep — exchange runs before the user has a session.
    from .auth_api import add_auth_routes

    add_auth_routes(app, store, verifier, current_user, require_capability("user:manage"))
