"""User profile + avatar routes (0028).

Profile = the signed-in user's personal metrics + avatar. The avatar is a stable
GitHub-style identicon by default; a user can submit a text prompt to have Grok
generate one (background job, mirrors topic images). Avatar bytes are served
publicly (non-sensitive); profile data is self-only.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse

from . import config, usage
from .identicon import identicon_svg
from .ratelimit import limiter, rate_limit_error
from .store import Store

log = logging.getLogger("bbv2.profile")

# Avatar generation is a paid image call — modest per-user cap.
_AVATAR_LIMIT, _AVATAR_WINDOW = 10, 3600.0


def add_profile_routes(
    app: FastAPI,
    router: APIRouter,
    store: Store,
    current_user: Callable[..., dict[str, Any]],
) -> None:
    @router.get("/profile")
    def profile(user: dict = Depends(current_user)) -> dict[str, Any]:
        row = store.get_user_by_id(user["id"])
        stats = store.user_profile_stats(user["id"], datetime.now(timezone.utc).isoformat())
        keys = row.keys() if row else []
        return {
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "role": user["role"],
                "avatar_status": (row["avatar_status"] if "avatar_status" in keys else "none") or "none",
                "member_since": row["created_at"] if row else None,
            },
            "avatars_enabled": config.avatars_enabled(),
            **stats,
        }

    @router.post("/profile/avatar")
    def generate_avatar(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        from .avatar_image import start_avatar

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt required")
        prompt = prompt[:300]
        if not config.avatars_enabled():
            raise HTTPException(status_code=503, detail="avatar generation is disabled")
        # Cheap pre-check so a repeat tap while one is already generating returns 409
        # WITHOUT burning a rate-limit slot (else 10 retries lock the user out for an
        # hour). The atomic claim in start_avatar still guards the rare race below.
        row = store.get_user_by_id(user["id"])
        if row and (row["avatar_status"] if "avatar_status" in row.keys() else "none") == "pending":
            raise HTTPException(status_code=409, detail="an avatar is already generating")
        ok, retry = limiter.check(
            ("avatar", user["id"]), limit=_AVATAR_LIMIT, window_s=_AVATAR_WINDOW
        )
        if not ok:
            raise rate_limit_error(retry)
        budget = usage.budget_status(store, user["id"])
        if not budget["allowed"]:
            raise HTTPException(status_code=429, detail=budget["message"])
        if not start_avatar(store, user["id"], prompt):
            # lost the race to a concurrent request that just claimed 'pending'
            raise HTTPException(status_code=409, detail="an avatar is already generating")
        log.info("avatar gen started: user %s", user["id"])
        return {"ok": True, "status": "pending"}

    @router.delete("/profile/avatar")
    def reset_avatar(user: dict = Depends(current_user)) -> dict[str, Any]:
        """Revert to the default identicon."""
        store.set_avatar(user["id"], None, "none")
        return {"ok": True}

    # Public (no auth, like topic images): the user's avatar — the stored generated
    # JPEG when ready, otherwise a deterministic identicon SVG so it always renders.
    @app.get("/api/avatar/{user_id}")
    def avatar_file(user_id: int):
        row = store.get_user_by_id(user_id)
        if not row:
            raise HTTPException(status_code=404, detail="unknown user")
        keys = row.keys()
        path = row["avatar_path"] if "avatar_path" in keys else None
        status = (row["avatar_status"] if "avatar_status" in keys else "none") or "none"
        if status == "ready" and path and os.path.exists(path):
            return FileResponse(path, media_type="image/jpeg")
        svg = identicon_svg(row["email"] or str(user_id))
        return Response(content=svg, media_type="image/svg+xml")
