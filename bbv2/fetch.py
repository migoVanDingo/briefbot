"""RSS/Atom fetching with conditional GET + retries.

Trimmed from the original briefbot's `fetch.py` to the RSS path used by 0002.
(HN/arXiv fetchers are deferred to a later phase; the schema's `type` field
already allows them.) Returns normalized item dicts via `bbv2.normalize`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import feedparser
import requests

from .config import USER_AGENT
from .httpclient import request_with_backoff
from .normalize import normalize_feed_entry


class FetchError(Exception):
    def __init__(
        self, message: str, status_code: int | None = None, url: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


def source_homepage(source: dict[str, Any], fallback_url: str | None = None) -> str | None:
    if source.get("homepage_url"):
        return source["homepage_url"]
    raw = fallback_url or source.get("url")
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


def _request_with_retries(
    session: requests.Session,
    url: str,
    timeout: int,
    headers: dict[str, str],
    verify_ssl: bool = True,
    max_attempts: int = 3,
) -> requests.Response:
    return request_with_backoff(
        lambda: session.get(url, timeout=timeout, headers=headers, verify=verify_ssl),
        max_attempts=max_attempts,
    )


def fetch_rss_feed(
    source: dict[str, Any],
    feed_url: str,
    store,
    session: requests.Session | None = None,
    timeout: int = 20,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch + parse a feed. Returns (items, status) where status is
    'ok' | 'not_modified'. Raises FetchError on transport/HTTP failures."""
    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    headers.update(store.get_feed_cache_headers(feed_url))
    verify_ssl = bool(source.get("verify_ssl", True))

    try:
        resp = _request_with_retries(
            session=sess,
            url=feed_url,
            timeout=timeout,
            headers=headers,
            verify_ssl=verify_ssl,
        )
    except requests.exceptions.SSLError as exc:
        raise FetchError(f"Feed SSL error: {feed_url} ({exc})", url=feed_url) from exc
    except requests.RequestException as exc:
        raise FetchError(f"Feed request error: {feed_url} ({exc})", url=feed_url) from exc

    if resp.status_code == 304:
        return [], "not_modified"
    if resp.status_code >= 400:
        raise FetchError(
            f"Feed HTTP {resp.status_code}: {feed_url}",
            status_code=resp.status_code,
            url=feed_url,
        )

    parsed = feedparser.parse(resp.content)
    etag = resp.headers.get("ETag") or parsed.get("etag")
    modified = resp.headers.get("Last-Modified") or parsed.get("modified")
    store.set_feed_cache_headers(feed_url, etag, modified)

    items = [normalize_feed_entry(source, dict(entry)) for entry in parsed.entries]
    return items, "ok"
