"""Admin scheduling + per-topic caps routes (0020).

Mounted on the dashboard router, gated by the `cadence:set` capability. Lets an
admin set each topic's discovery schedule (interval | daily | weekly) and its
ingest caps (sources / stories-per-source), with reset-to-default.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException

from . import config
from .store import Store

_PERIODS = {"day", "week", "month", "year"}


def _serialize(t: Any) -> dict[str, Any]:
    return {
        "slug": t["slug"],
        "name": t["name"],
        "discover": {
            "period": t["discover_period"],            # null → using the default
            "start_date": t["discover_start_date"],
            "at_min": t["discover_at_min"],
        },
        "collect": {"interval_min": t["collect_interval_min"]},
        "caps": {
            "max_sources": t["max_sources"],
            "max_stories_per_source": t["max_stories_per_source"],
        },
        "last_discovered_at": t["last_discovered_at"],
    }


def _int_field(body: dict, key: str, lo: int, hi: int) -> int | None:
    """Return a validated int for `key` if present (-1 passes through as 'clear');
    raise 422 on out-of-range. Returns None when the key is absent (unchanged)."""
    if key not in body:
        return None
    raw = body.get(key)
    if raw is None or raw == "":
        return -1  # explicit clear
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{key} must be an integer")
    if v != -1 and not (lo <= v <= hi):
        raise HTTPException(status_code=422, detail=f"{key} out of range")
    return v


def add_schedule_routes(
    router: APIRouter,
    store: Store,
    require_cadence: Callable[..., dict[str, Any]],
) -> None:
    def _defaults() -> dict[str, Any]:
        return {
            "discover_interval_min": config.default_discover_interval_min(),
            "collect_interval_min": config.default_collect_interval_min(),
            "max_sources": config.max_sources_per_topic(),
            "max_stories_per_source": config.max_stories_per_source(),
            "window_min": config.scheduler_window_min(),
        }

    @router.get("/admin/schedule")
    def get_schedule(user: dict = Depends(require_cadence)) -> dict[str, Any]:
        return {
            "defaults": _defaults(),
            "topics": [_serialize(t) for t in store.topics_for_scheduler()],
        }

    @router.patch("/topics/{slug}/schedule")
    def set_schedule(
        slug: str, body: dict = Body(...), user: dict = Depends(require_cadence)
    ) -> dict[str, Any]:
        if not store.get_topic(slug):
            raise HTTPException(status_code=404, detail="unknown topic")
        kwargs: dict[str, Any] = {}
        if "discover_period" in body:
            period = (body.get("discover_period") or "").strip()
            if period and period not in _PERIODS:
                raise HTTPException(status_code=422, detail="invalid discover_period")
            kwargs["discover_period"] = period  # "" clears → default interval
        if "discover_start_date" in body:
            sd = (body.get("discover_start_date") or "").strip()
            if sd:
                try:
                    date.fromisoformat(sd)
                except ValueError:
                    raise HTTPException(status_code=422, detail="discover_start_date must be YYYY-MM-DD")
            kwargs["discover_start_date"] = sd
        # ints: -1 (or empty) clears to default; ranges validated.
        for key, lo, hi in (
            ("discover_at_min", 0, 1439),
            ("collect_interval_min", 0, 525_600),
            ("max_sources", 0, 100),
            ("max_stories_per_source", 0, 500),
        ):
            v = _int_field(body, key, lo, hi)
            if v is not None:
                kwargs[key] = v
        if kwargs:
            store.set_topic_schedule(slug, **kwargs)
        return {"ok": True}

    @router.post("/topics/{slug}/schedule/reset")
    def reset_schedule(slug: str, user: dict = Depends(require_cadence)) -> dict[str, Any]:
        if not store.get_topic(slug):
            raise HTTPException(status_code=404, detail="unknown topic")
        store.reset_topic_schedule(slug)
        return {"ok": True}

    @router.post("/admin/schedule/reset")
    def reset_all(user: dict = Depends(require_cadence)) -> dict[str, Any]:
        n = store.reset_all_schedules()
        return {"ok": True, "reset": n}
