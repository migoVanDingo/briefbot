"""Normalization layer for converting raw source payloads into one schema.

Provides source-specific normalizers that produce fields expected by
storage/scoring, including canonical URL and dedupe keys.

Copied from the original briefbot (`normalize.py`); HN/arXiv normalizers are
retained for when those source types land (collect uses RSS/site in 0002).
"""

from __future__ import annotations

from typing import Any

from .util import (
    canonicalize_url,
    normalize_text,
    parse_to_utc_iso,
    stable_hash,
    utc_now_iso,
)


def _dedupe_key(
    source_id: str,
    canonical_url: str | None,
    title: str,
    source_name: str,
    published_at: str | None,
) -> str:
    if canonical_url:
        return f"url:{canonical_url}"
    fallback = stable_hash(title.lower(), source_name.lower(), published_at or "")
    return f"fallback:{source_id}:{fallback}"


def _base_item(
    source: dict[str, Any],
    title: str,
    url: str | None,
    published_at: str | None,
    author: str | None,
    summary: str | None,
    raw: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_id = source["id"]
    source_name = source.get("name", source_id)
    canonical_url = canonicalize_url(url) if url else None
    published_iso = parse_to_utc_iso(published_at)
    fetched_at = utc_now_iso()

    dedupe_key = _dedupe_key(source_id, canonical_url, title, source_name, published_iso)
    item_id = stable_hash(source_id, canonical_url or "", dedupe_key)

    return {
        "item_id": item_id,
        "dedupe_key": dedupe_key,
        "canonical_url": canonical_url,
        "source_id": source_id,
        "source_name": source_name,
        "title": normalize_text(title) or "(untitled)",
        "url": canonical_url or url,
        "published_at": published_iso,
        "fetched_at": fetched_at,
        "author": normalize_text(author),
        "summary": normalize_text(summary),
        "tags": source.get("tags", []),
        "raw": raw,
        "metrics": metrics or {},
        "score": 0.0,
    }


def normalize_feed_entry(source: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    title = entry.get("title") or ""
    url = entry.get("link")
    published = entry.get("published") or entry.get("updated")
    author = entry.get("author")
    summary = entry.get("summary") or entry.get("description")
    raw = {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "link": entry.get("link"),
        "published": entry.get("published"),
        "updated": entry.get("updated"),
        "author": entry.get("author"),
    }
    return _base_item(source, title, url, published, author, summary, raw)
