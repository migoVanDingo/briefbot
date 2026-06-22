"""Per-user UI state routes (0018): theme/accent preferences + write-once flags.

Persisted server-side so they follow the account across devices/browsers instead
of living in localStorage. Mounted onto the dashboard router (see dashboard_api).
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException

from .store import Store

VALID_THEMES = {"light", "dark"}
# Write-once "seen" flags the frontend may set/clear. Allowlisted so the table
# can't be filled with arbitrary keys.
ALLOWED_FLAGS = {
    "onboarding_done",
    "tour:headlines",
    "tour:stories",
    "tour:topics",
    "tour:favorites",
}


def add_prefs_routes(
    router: APIRouter, store: Store, current_user: Callable[..., dict[str, Any]]
) -> None:
    @router.patch("/preferences")
    def patch_preferences(
        body: dict = Body(...), user: dict = Depends(current_user)
    ) -> dict[str, Any]:
        """Persist editable UI preferences (theme, accent). Per-user; absent keys
        are left unchanged, an explicit "" clears back to the default."""
        kwargs: dict[str, Any] = {}
        if "theme" in body:
            theme = body.get("theme")
            if theme not in (None, "", *VALID_THEMES):
                raise HTTPException(status_code=422, detail="invalid theme")
            kwargs["theme"] = theme or ""  # "" → NULL (follow OS)
        if "accent" in body:
            accent = body.get("accent")
            if accent not in (None, "") and (
                not isinstance(accent, str) or len(accent) > 16
            ):
                raise HTTPException(status_code=422, detail="invalid accent")
            kwargs["accent"] = accent or ""
        if kwargs:
            store.set_user_settings(user["id"], **kwargs)
        return {"ok": True}

    @router.put("/flags/{flag}")
    def set_flag(flag: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        if flag not in ALLOWED_FLAGS:
            raise HTTPException(status_code=422, detail="unknown flag")
        store.set_user_flag(user["id"], flag)
        return {"ok": True, "flag": flag}

    @router.delete("/flags/{flag}")
    def clear_flag(flag: str, user: dict = Depends(current_user)) -> dict[str, Any]:
        if flag not in ALLOWED_FLAGS:
            raise HTTPException(status_code=422, detail="unknown flag")
        store.clear_user_flag(user["id"], flag)
        return {"ok": True, "flag": flag}
