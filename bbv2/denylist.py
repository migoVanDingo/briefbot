"""Domain denylist for source discovery.

A blunt block on obviously-unwanted domains (adult, etc.) so nothing sketchy is
added as a source even if a topic slips through moderation. Substring match on
the registrable host, so subdomains are covered too. Extend `DENY_DOMAINS` as
needed; keep it conservative to avoid false positives.
"""

from __future__ import annotations

from urllib.parse import urlparse

DENY_DOMAINS: set[str] = {
    "pornhub.com",
    "xvideos.com",
    "xnxx.com",
    "xhamster.com",
    "redtube.com",
    "youporn.com",
    "onlyfans.com",
    "rule34.xxx",
    "8kun.top",
    "8ch.net",
}

# Whole-TLD blocks for categories that are ~always adult.
DENY_TLDS: set[str] = {".xxx", ".porn", ".adult", ".sex"}


def is_blocked_domain(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    if not host:
        return False
    if any(host.endswith(tld) for tld in DENY_TLDS):
        return True
    return any(host == d or host.endswith("." + d) for d in DENY_DOMAINS)
