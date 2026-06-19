"""RSS/Atom fetching with conditional GET + retries.

Trimmed from the original briefbot's `fetch.py` to the RSS path used by 0002.
(HN/arXiv fetchers are deferred to a later phase; the schema's `type` field
already allows them.) Returns normalized item dicts via `bbv2.normalize`.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests

from .config import USER_AGENT
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
    backoff = 1.0
    last_resp: requests.Response | None = None
    for attempt in range(1, max_attempts + 1):
        resp = session.get(url, timeout=timeout, headers=headers, verify=verify_ssl)
        last_resp = resp
        if resp.status_code != 429:
            return resp
        retry_after = resp.headers.get("Retry-After")
        sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else backoff
        time.sleep(min(15.0, max(0.5, sleep_s)))
        backoff *= 2
        if attempt == max_attempts:
            return resp
    if last_resp is None:
        raise RuntimeError("No HTTP response returned")
    return last_resp


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
