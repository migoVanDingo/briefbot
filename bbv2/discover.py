"""Feed discovery helpers for `type: site` sources.

Fetch a webpage and parse `<link rel="alternate">` tags (plus common feed-path
probes) to discover RSS/Atom feed URLs. Results are cached by the store to avoid
rediscovery on every run.

Copied verbatim from the original briefbot (`discover.py`).
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

import requests

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
        if mime_type and mime_type not in FEED_MIME_TYPES:
            continue
        absolute = urljoin(base_url, href)
        if absolute not in feeds:
            feeds.append(absolute)
    return feeds


def _looks_like_feed(content_type: str, body: str, url: str) -> bool:
    ctype = (content_type or "").lower()
    if any(t in ctype for t in ("rss+xml", "atom+xml", "xml", "rdf+xml")):
        return True
    text = (body or "").lower()
    if "<rss" in text or "<feed" in text or "<rdf:rdf" in text:
        return True
    path = urlparse(url).path.lower()
    return any(token in path for token in ("/feed", "rss", "atom", ".xml"))


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
    backoff = 1.0
    resp = None
    for _ in range(3):
        resp = sess.get(
            site_url,
            timeout=timeout,
            headers={"User-Agent": "bbv2/0.1"},
            verify=verify_ssl,
        )
        if resp.status_code != 429:
            break
        retry_after = resp.headers.get("Retry-After")
        sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else backoff
        import time

        time.sleep(min(15.0, max(0.5, sleep_s)))
        backoff *= 2
    if resp is None:
        raise RuntimeError("No response while discovering feeds")
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
