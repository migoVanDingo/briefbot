"""Shared response serializers for the dashboard API.

Extracted so `dashboard_api` and the route modules split out of it
(`dashboard_briefs`, …) share one definition instead of duplicating shapes.
"""

from __future__ import annotations

import json
from typing import Any

from .api import _item_dict


def topic_image_status(topic_row: Any) -> str:
    return (topic_row["image_status"] if "image_status" in topic_row.keys() else "none") or "none"


def story_dict(row: Any) -> dict[str, Any]:
    """An item plus this user's feedback vote + saved flag — the Stories/Headlines
    row shape (was duplicated across query_stories and brief_stories)."""
    return {
        **_item_dict(row),
        "feedback_vote": row["feedback_vote"],
        "is_saved": bool(row["is_saved"]),
    }


def serialize_brief(topic_row: Any, brief_row: Any) -> dict[str, Any]:
    status = topic_image_status(topic_row)
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
