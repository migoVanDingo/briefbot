"""Shared utility functions used across bbv2 modules.

Includes time parsing/formatting, URL canonicalization, hashing for stable IDs,
text normalization, JSON serialization helpers, and filesystem helpers.

Copied from the original briefbot (`util.py`) — kept identical so other copied
modules drop in unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dateutil import parser as dtparser


TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS_EXACT = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_to_utc_iso(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = dtparser.parse(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return url

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"

    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=True):
        key_l = key.lower()
        if key_l in TRACKING_PARAMS_EXACT:
            continue
        if any(key_l.startswith(prefix) for prefix in TRACKING_PARAMS_PREFIXES):
            continue
        query_pairs.append((key, val))
    query = urlencode(query_pairs, doseq=True)

    clean = parsed._replace(
        scheme=scheme, netloc=netloc, path=path, params="", query=query, fragment=""
    )
    return urlunparse(clean)


def stable_hash(*parts: str, length: int = 32) -> str:
    joined = "||".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), default=str)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip()
