"""Topic embedding index — generation + routing (0030).

Generation is decoupled from how a brief was built: a `meta` vector (name+desc)
is the always-present floor, and a sweep embeds any recent brief lacking a vector
(catches nightly + on-demand briefs alike). Routing embeds a free-text query and
cosine-ranks it against every topic's centroid — the evidence the agent routes on.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .embeddings import Embedder, cosine, default_embedder
from .store import Store

log = logging.getLogger("bbv2.topic_index")


def _meta_text(name: str | None, description: str | None) -> str:
    name = (name or "").strip()
    desc = (description or "").strip()
    return f"{name}. {desc}" if desc else (name or "?")


def metered_embedder(store: Store) -> Embedder:
    """An OpenAI embedder that meters tokens to the system bucket (purpose
    `embedding`), so embedding spend shows in the 0027 cost view."""

    def _on_usage(tokens: int, model: str) -> None:
        try:
            store.record_usage(0, "embedding", model, tokens, 0)
        except Exception:  # pragma: no cover - metering is best-effort
            pass

    return default_embedder(_on_usage)


def ensure_meta_embeddings(store: Store, *, embedder: Embedder | None = None) -> int:
    """Embed name+description for every topic lacking a `meta` vector (the floor).
    Returns the number embedded."""
    rows = store.topics_missing_meta_embedding()
    if not rows:
        return 0
    embedder = embedder or metered_embedder(store)
    res = embedder([_meta_text(r["name"], r["description"]) for r in rows])
    for r, vec in zip(rows, res.vectors):
        store.upsert_topic_embedding(int(r["id"]), "meta", "", res.model, vec)
    log.info("embedded meta vectors for %d topic(s)", len(rows))
    return len(rows)


def embed_topic_meta(
    store: Store, topic_id: int, name: str, description: str | None,
    *, embedder: Embedder | None = None,
) -> None:
    """Embed/refresh one topic's meta vector (best-effort; called on topic create)."""
    embedder = embedder or metered_embedder(store)
    res = embedder([_meta_text(name, description)])
    if res.vectors:
        store.upsert_topic_embedding(int(topic_id), "meta", "", res.model, res.vectors[0])


def embed_pending_briefs(
    store: Store, *, days: int | None = None, embedder: Embedder | None = None, batch: int = 64
) -> int:
    """Embed any brief in the last `days` lacking a `brief` vector (nightly sweep)."""
    days = days if days is not None else config.embed_centroid_days()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = store.briefs_missing_embedding(since)
    if not rows:
        return 0
    embedder = embedder or metered_embedder(store)
    done = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        res = embedder([(r["summary"] or "").strip() for r in chunk])
        for r, vec in zip(chunk, res.vectors):
            store.upsert_topic_embedding(int(r["topic_id"]), "brief", r["date"], res.model, vec)
        done += len(chunk)
    log.info("embedded %d brief(s)", done)
    return done


def rank_topics(
    store: Store, query: str, *, embedder: Embedder | None = None, days: int | None = None
) -> list[dict[str, Any]]:
    """Cosine-rank a query against every topic's centroid → evidence for routing.
    Returns [{id, slug, name, score}] desc. Ensures the meta floor first so a topic
    is never invisible. Empty list if embeddings are disabled / no topics."""
    if not config.embeddings_enabled():
        return []
    days = days if days is not None else config.embed_centroid_days()
    embedder = embedder or metered_embedder(store)
    ensure_meta_embeddings(store, embedder=embedder)  # lazy floor
    topics = store.topics_with_any_embedding()
    if not topics:
        return []
    res = embedder([query])
    if not res.vectors:
        return []
    qv = res.vectors[0]
    ranked: list[dict[str, Any]] = []
    for t in topics:
        c = store.topic_centroid(int(t["id"]), days)
        if not c:
            continue
        ranked.append(
            {"id": int(t["id"]), "slug": t["slug"], "name": t["name"], "score": cosine(qv, c)}
        )
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
