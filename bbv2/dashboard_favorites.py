"""Favorites routes for the dashboard API (folders + saved links + search).

Split out of `dashboard_api.py` to keep files under the size cap. `add_favorite_routes`
attaches the `/api/favorites/*` routes to the shared router, reusing the same
`current_user` dependency.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException

from .moderation import sanitize_name
from .store import Store
from .util import titlecase


def add_favorite_routes(
    router: APIRouter, store: Store, current_user: Callable[..., dict]
) -> None:
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
        name = sanitize_name(body.get("name") or "")
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        fid = store.create_folder(user["id"], name)  # store Title-cases it
        return {"ok": True, "id": fid, "name": titlecase(name)}

    @router.get("/favorites/search")
    def favorite_search(q: str = "", user: dict = Depends(current_user)) -> dict[str, Any]:
        rows = store.search_favorites(user["id"], q)
        return {
            "items": [
                {"id": r["id"], "item_id": r["item_id"], "title": r["title"], "url": r["url"]}
                for r in rows
            ]
        }

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
                {"id": r["id"], "item_id": r["item_id"], "title": r["title"], "url": r["url"]}
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
        fid = (body.get("folder_id") or "").strip() or store.ensure_default_folder(user["id"])
        if not store.get_folder(user["id"], fid):
            raise HTTPException(status_code=404, detail="unknown folder")
        row = store.add_favorite(user["id"], fid, title, url, (body.get("item_id") or None))
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
