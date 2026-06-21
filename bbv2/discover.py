"""Feed discovery helpers for `type: site` sources.

Fetch a webpage and parse `<link rel="alternate">` tags (plus common feed-path
probes) to discover RSS/Atom feed URLs. Results are cached by the store to avoid
rediscovery on every run.

Adapted from the original briefbot (`discover.py`): autodiscovery now *requires*
a feed MIME type on `rel="alternate"` links (per the RSS autodiscovery spec), so
typeless hreflang/locale alternates aren't mistaken for feeds.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

import requests

from .httpclient import request_with_backoff

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - dependency may be missing until install
    BeautifulSoup = None

FEED_MIME_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "application/xml",
    "text/xml",
}


def discover_feeds_from_html(html: str, base_url: str) -> list[str]:
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required for feed discovery; install requirements.txt"
        )
    soup = BeautifulSoup(html, "html.parser")
    feeds: list[str] = []
    for link in soup.find_all("link"):
        rel = {r.lower() for r in (link.get("rel") or [])}
        if "alternate" not in rel:
            continue
        href = link.get("href")
        mime_type = (link.get("type") or "").split(";")[0].strip().lower()
        if not href:
            continue
        # Require a feed MIME type — typeless alternates are hreflang/locale
        # links, not feeds.
        if mime_type not in FEED_MIME_TYPES:
            continue
        absolute = urljoin(base_url, href)
        if absolute not in feeds:
            feeds.append(absolute)
    return feeds


def _looks_like_feed(content_type: str, body: str, url: str) -> bool:
    # Require the *response* to look like a feed; a feed-ish URL path alone is
    # not enough (e.g. an HTML page served at "/feed").
    ctype = (content_type or "").lower()
    if any(t in ctype for t in ("rss+xml", "atom+xml", "xml", "rdf+xml")):
        return True
    text = (body or "").lower()
    return "<rss" in text or "<feed" in text or "<rdf:rdf" in text


def _candidate_feed_urls(site_url: str, soup: "BeautifulSoup") -> list[str]:
    parsed = urlparse(site_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    base_path = parsed.path.rstrip("/")

    candidates: list[str] = []
    for hint in (
        "/feed",
        "/feed/",
        "/rss",
        "/rss/",
        "/rss.xml",
        "/atom.xml",
        "/index.xml",
        "/feeds/posts/default?alt=rss",
    ):
        candidates.append(urljoin(root + "/", hint.lstrip("/")))
        if base_path:
            candidates.append(
                urljoin(root + "/", f"{base_path.lstrip('/')}/{hint.lstrip('/')}")
            )

    # Some sites expose feed links in anchor tags instead of <link rel=alternate>.
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        href_l = href.lower()
        if "rss" in href_l or "atom" in href_l or "feed" in href_l:
            candidates.append(urljoin(site_url, href))

    deduped: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        clean = urlunparse(urlparse(url)._replace(fragment=""))
        if clean not in seen:
            seen.add(clean)
            deduped.append(clean)
    return deduped


def discover_site_feeds(
    site_url: str,
    timeout: int = 20,
    session: requests.Session | None = None,
    verify_ssl: bool = True,
) -> list[str]:
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required for feed discovery; install requirements.txt"
        )
    sess = session or requests.Session()
    resp = request_with_backoff(
        lambda: sess.get(
            site_url,
            timeout=timeout,
            headers={"User-Agent": "bbv2/0.1"},
            verify=verify_ssl,
        )
    )
    resp.raise_for_status()
    feeds = discover_feeds_from_html(resp.text, site_url)
    if feeds:
        return feeds

    soup = BeautifulSoup(resp.text, "html.parser")
    probed: list[str] = []
    for candidate in _candidate_feed_urls(site_url, soup):
        try:
            r = sess.get(
                candidate,
                timeout=timeout,
                headers={"User-Agent": "bbv2/0.1"},
                verify=verify_ssl,
            )
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        if _looks_like_feed(r.headers.get("Content-Type", ""), r.text[:3000], candidate):
            probed.append(candidate)
        if len(probed) >= 5:
            break
    return probed
