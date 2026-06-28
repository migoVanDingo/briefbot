"""Admin metrics routes (0021): estimated LLM cost + per-user engagement.

Gated by the `metrics:read` capability. Cost is a ballpark from token volume
(`config.llm_prices()`), not a billed amount.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from . import config
from .store import Store

_RANGES = {"7d": 7, "30d": 30, "90d": 90}


def add_metrics_routes(
    router: APIRouter,
    store: Store,
    require_metrics: Callable[..., dict[str, Any]],
) -> None:
    @router.get("/admin/metrics/llm")
    def llm_metrics(
        range: str = "30d", user: dict = Depends(require_metrics)
    ) -> dict[str, Any]:
        days = _RANGES.get(range, 30)
        now = datetime.now(timezone.utc)
        since = (now - timedelta(days=days)).replace(microsecond=0)
        prev_since = (now - timedelta(days=days * 2)).replace(microsecond=0)

        summary = store.usage_summary(since.isoformat())
        # Previous equal-length window → trend delta on total estimated cost.
        prev = store.usage_summary(prev_since.isoformat(), since.isoformat())
        cur_cost = summary["overall"]["cost"]
        prev_cost = prev["overall"]["cost"]
        delta_pct = (
            round((cur_cost - prev_cost) / prev_cost * 100, 1) if prev_cost > 0 else None
        )
        return {
            "range": range if range in _RANGES else "30d",
            "since": since.isoformat(),
            **summary,
            "trend": {"prev_cost": round(prev_cost, 4), "delta_pct": delta_pct},
            "prices": config.llm_prices(),
        }

    @router.get("/admin/metrics/users")
    def user_metrics(user: dict = Depends(require_metrics)) -> dict[str, Any]:
        rows = store.user_engagement()
        users = [
            {
                "id": r["id"],
                "name": r["name"],
                "email": r["email"],
                "role": r["role"],
                "status": (r["status"] if "status" in r.keys() else "active") or "active",
                "last_login_at": r["last_login_at"],
                "tokens": int(r["tokens"] or 0),
                "topics": int(r["topics"] or 0),
                "clicks": int(r["clicks"] or 0),
                "votes": int(r["votes"] or 0),
                "saves": int(r["saves"] or 0),
                "chats": int(r["chats"] or 0),
            }
            for r in rows
        ]
        n = len(users)
        avg_topics = round(sum(u["topics"] for u in users) / n, 1) if n else 0
        return {
            "users": users,
            "totals": {
                "user_count": n,
                "avg_topics": avg_topics,
                "active_users": sum(1 for u in users if u["last_login_at"]),
            },
        }

    @router.get("/admin/metrics/users/{user_id}")
    def user_detail(
        user_id: int, range: str = "30d", user: dict = Depends(require_metrics)
    ) -> dict[str, Any]:
        """Drill-down for one user over the selected range: usage by purpose (+cost),
        access frequency, subscriptions, and 👍/👎."""
        days = _RANGES.get(range, 30)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0)
        detail = store.user_detail(user_id, since.isoformat())
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown user")
        return {"range": range if range in _RANGES else "30d", "since": since.isoformat(), **detail}
