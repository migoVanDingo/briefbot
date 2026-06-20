"""Deterministic, in-memory clustering of items into storylines + trend scores.

Ported and simplified from the original briefbot's `cluster.py`: the same token-
similarity approach (rapidfuzz token-set ratio when available, else Jaccard over
title/domain/tag signatures) and the same trend-score shape. Trimmed for bbv2 —
a pure function over a list of item dicts (no DB, no cluster events/purge), so
it's unit-testable and cheap at family scale. Feeds the brief's "Trending"
section.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from dateutil import parser as dtparser

try:
    from rapidfuzz.fuzz import token_set_ratio  # type: ignore

    HAS_RAPIDFUZZ = True
except Exception:
    HAS_RAPIDFUZZ = False


STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "for", "in", "on", "of", "with", "at",
    "is", "are", "new", "how", "why", "from", "into", "by", "about", "as", "it",
    "its", "via", "you", "your", "this", "that", "their", "will", "can", "using",
    "use", "after", "before", "during", "while", "who", "whom", "whose", "what",
    "which", "when", "where", "but", "not", "one", "first", "self", "time",
    "year", "years", "day", "days", "long", "fine",
}


@dataclass
class _Cluster:
    item_ids: list[str] = field(default_factory=list)
    source_ids: set[str] = field(default_factory=set)
    token_counts: Counter = field(default_factory=Counter)
    centroid_tokens: set[str] = field(default_factory=set)
    titles: list[str] = field(default_factory=list)
    members: list[dict[str, Any]] = field(default_factory=list)


def _to_dt(value: str | None) -> datetime:
    if value:
        try:
            dt = dtparser.parse(value)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    clean = []
    for ch in (text or "").lower():
        clean.append(ch if (ch.isalnum() or ch in {"-", "_", " ", "."}) else " ")
    tokens = []
    for t in "".join(clean).replace("_", " ").replace("-", " ").split():
        if len(t) <= 2 or t in STOPWORDS:
            continue
        tokens.append(t)
    return set(tokens)


def _signature(item: dict[str, Any]) -> set[str]:
    toks = set(_tokenize(item.get("title") or ""))
    domain = urlparse(item.get("url") or "").netloc.lower().replace("www.", "")
    if domain:
        toks.add(f"domain:{domain}")
    for tag in item.get("tags", []) or []:
        t = str(tag).lower().strip()
        if t:
            toks.add(f"tag:{t}")
    return toks


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _similarity(item: dict[str, Any], cluster: _Cluster, sig: set[str]) -> float:
    if HAS_RAPIDFUZZ and cluster.titles:
        best = 0.0
        title = item.get("title") or ""
        for candidate in cluster.titles[-6:]:
            score = token_set_ratio(title, candidate) / 100.0
            best = max(best, score)
        return best
    return _jaccard(sig, cluster.centroid_tokens)


def _threshold() -> float:
    return 0.72 if HAS_RAPIDFUZZ else 0.35


def _label(cluster: _Cluster) -> str:
    top = [
        tok
        for tok, _ in cluster.token_counts.most_common(3)
        if not tok.startswith(("domain:", "cat:", "tag:"))
    ]
    return " ".join(top) if top else "general update"


def _trend_score(v1: int, v3: int, v7: int, sources_count: int) -> float:
    base = v1 * 3 + v3 * 2 + v7
    multiplier = 1 + 0.35 * max(0, sources_count - 1)
    return round(base * multiplier, 4)


def cluster_items(
    items: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Group items into storylines and rank by trend score (highest first).

    Each returned cluster: ``label``, ``trend_score``, ``item_count``,
    ``sources_count``, ``representative_title``/``representative_url``, ``item_ids``.
    """
    now = now or datetime.now(timezone.utc)
    clusters: list[_Cluster] = []

    for item in items:
        sig = _signature(item)
        title_toks = _tokenize(item.get("title") or "")
        best: _Cluster | None = None
        best_score = -1.0
        for c in clusters:
            sim = _similarity(item, c, sig)
            if sim > best_score:
                best_score, best = sim, c

        if best is None or best_score < _threshold():
            best = _Cluster()
            clusters.append(best)

        best.item_ids.append(item.get("item_id") or "")
        best.source_ids.add(str(item.get("source_id") or item.get("source_name") or ""))
        best.token_counts.update(title_toks)
        best.centroid_tokens |= sig
        best.titles.append(item.get("title") or "")
        best.members.append(item)

    d1, d3, d7 = now - timedelta(days=1), now - timedelta(days=3), now - timedelta(days=7)
    out: list[dict[str, Any]] = []
    for c in clusters:
        times = [_to_dt(m.get("published_at") or m.get("fetched_at")) for m in c.members]
        v1 = sum(1 for t in times if t >= d1)
        v3 = sum(1 for t in times if t >= d3)
        v7 = sum(1 for t in times if t >= d7)
        rep = sorted(
            c.members,
            key=lambda x: (float(x.get("score") or 0.0), x.get("published_at") or ""),
            reverse=True,
        )[0]
        out.append(
            {
                "label": _label(c),
                "trend_score": _trend_score(v1, v3, v7, len(c.source_ids)),
                "item_count": len(c.item_ids),
                "sources_count": len(c.source_ids),
                "representative_title": rep.get("title"),
                "representative_url": rep.get("url"),
                "item_ids": list(c.item_ids),
            }
        )

    out.sort(key=lambda c: c["trend_score"], reverse=True)
    return out
