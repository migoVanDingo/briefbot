"""bbv2 consumer API — token-authenticated, read-only.

Thin layer: validate the bearer token (→ allowed topic slugs), call store
queries, serialize. No business logic beyond scope enforcement.

Data routes live under the **`/consumer`** prefix (0022) so they don't collide
with the dashboard SPA routes when nginx serves the SPA at `/`. `GET /health`
stays at root — the deploy health check curls it directly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query

from . import config
from .ratelimit import limiter
from .store import Store

MAX_LIMIT = 500
DEFAULT_LIMIT = 100

_ITEM_FIELDS = (
    "item_id",
    "title",
    "url",
    "canonical_url",
    "source_name",
    "published_at",
    "fetched_at",
    "summary",
    "score",
)


def _bearer(authorization: str) -> str | None:
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _item_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in _ITEM_FIELDS}


def create_app(store: Store) -> FastAPI:
    app = FastAPI(title="bbv2 consumer API", version="0.1.0")

    def require_scope(authorization: str = Header(default="")) -> list[str]:
        token = _bearer(authorization)
        if not token or store.get_token(token) is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        # Per-token rate limit (service accounts). /health is exempt — it never
        # reaches here, so uptime monitoring stays unthrottled.
        limit, window = config.ratelimit_consumer()
        ok, retry = limiter.check(("consumer", token), limit=limit, window_s=window)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — slow down.",
                headers={"Retry-After": str(int(retry) + 1)},
            )
        return store.token_topic_slugs(token)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Data routes under /consumer so nginx can proxy just `location /consumer/`
    # without colliding with the SPA (0022). Auth/scoping/rate-limit unchanged.
    consumer = APIRouter(prefix="/consumer")

    @consumer.get("/topics")
    def topics(scope: list[str] = Depends(require_scope)) -> dict[str, Any]:
        allowed = set(scope)
        items = [
            {"slug": t["slug"], "name": t["name"], "description": t["description"]}
            for t in store.list_topics()
            if t["slug"] in allowed
        ]
        return {"topics": items}

    @consumer.get("/items")
    def items(
        topic: str = Query(...),
        since: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_LIMIT),
        scope: list[str] = Depends(require_scope),
    ) -> dict[str, Any]:
        if topic not in set(scope):
            raise HTTPException(status_code=403, detail="topic not in token scope")
        limit = max(1, min(limit, MAX_LIMIT))
        rows = store.items_for_consumer(topic, since_iso=since, limit=limit)
        results = [_item_dict(r) for r in rows]
        # Ascending by fetched_at → last row is the newest; consumers checkpoint it.
        next_since = rows[-1]["fetched_at"] if rows else since
        return {"items": results, "count": len(results), "next_since": next_since}

    app.include_router(consumer)
    return app
