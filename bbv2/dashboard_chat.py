"""Chat / conversation routes for the dashboard API.

Split out of dashboard_api to keep that module under the size cap. Mounted onto
the dashboard router (auth + the general per-user rate limit apply via the router).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from . import config, usage
from .ratelimit import limiter
from .store import Store


def add_chat_routes(
    router: APIRouter,
    store: Store,
    current_user: Callable[..., dict[str, Any]],
    moderate_generate: Any | None,
) -> None:
    def _conv_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": row["message_count"] if "message_count" in row.keys() else None,
        }

    def _conv_or_404(user_id: int, cid: str):
        conv = store.get_conversation(user_id, cid)
        if not conv:
            raise HTTPException(status_code=404, detail="unknown conversation")
        return conv

    @router.post("/conversations")
    def create_conversation(user: dict = Depends(current_user)) -> dict[str, Any]:
        cid = store.create_conversation(user["id"])
        return {"id": cid, "title": None, "message_count": 0}

    @router.get("/conversations")
    def list_conversations(user: dict = Depends(current_user)) -> dict[str, Any]:
        return {
            "conversations": [_conv_dict(r) for r in store.list_conversations(user["id"])]
        }

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
        limit, window = config.ratelimit_chat()
        ok, retry = limiter.check(("chat", user["id"]), limit=limit, window_s=window)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — slow down.",
                headers={"Retry-After": str(int(retry) + 1)},
            )
        text = (body.get("content") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="content required")

        review_generate = usage.metered_relevance_generate(store, user["id"], "provision")

        def gen():
            for ev in run_chat_turn(
                store,
                user["id"],
                cid,
                text,
                moderate_generate=moderate_generate,
                review_generate=review_generate,
            ):
                yield f"data: {json.dumps(ev)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")
