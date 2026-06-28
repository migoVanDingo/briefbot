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

from .safefetch import UnsafeURLError, safe_get

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


# Feed URLs that are structurally never topic news (advertised on many pages):
# Wikipedia's generic featured/picture-of-the-day feeds, WordPress comment feeds.
_JUNK_FEED_MARKERS = (
    "action=featuredfeed",  # en.wikipedia.org/w/api.php?action=featuredfeed (potd/featured)
    "/comments/feed",
    "comments/feed/",
    "feed=comments",
    "comments-rss",
)


def is_junk_feed_url(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in _JUNK_FEED_MARKERS)


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
) -> list[str]:
    """Discover feed URLs for a site. SSRF-guarded + TLS-verified via `safe_get`."""
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required for feed discovery; install requirements.txt"
        )
    sess = session or requests.Session()
    headers = {"User-Agent": "bbv2/0.1"}
    resp = safe_get(site_url, session=sess, timeout=timeout, headers=headers)
    resp.raise_for_status()
    feeds = [f for f in discover_feeds_from_html(resp.text, site_url) if not is_junk_feed_url(f)]
    if feeds:
        return feeds

    soup = BeautifulSoup(resp.text, "html.parser")
    probed: list[str] = []
    for candidate in _candidate_feed_urls(site_url, soup):
        if is_junk_feed_url(candidate):
            continue
        try:
            r = safe_get(candidate, session=sess, timeout=timeout, headers=headers)
        except (requests.RequestException, UnsafeURLError):
            continue
        if r.status_code >= 400:
            continue
        if _looks_like_feed(r.headers.get("Content-Type", ""), r.text[:3000], candidate):
            probed.append(candidate)
        if len(probed) >= 5:
            break
    return probed
