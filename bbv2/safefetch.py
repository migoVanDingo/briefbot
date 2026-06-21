"""SSRF-safe outbound GET.

User-driven fetches — the chat `summarize_article` tool, feed discovery, and RSS
collection — can be pointed at arbitrary URLs by whatever a feed or a user
supplies. This wraps `httpclient.request_with_backoff` with guards so those
fetches can't be steered at internal or cloud-metadata addresses:

- only `http`/`https` schemes;
- the host must resolve **entirely** to global (public) IPs — any loopback,
  link-local (incl. `169.254.169.254`), private (RFC-1918 / ULA), multicast,
  reserved, or unspecified address rejects the request;
- automatic redirects are disabled and each hop is re-validated (so an allowed
  host can't 302 to an internal one);
- the response body is capped (`max_bytes`) to bound memory.

Set `BBV2_ALLOW_PRIVATE_FETCH=true` to disable the IP guard for local dev.

Residual: validation resolves DNS once, then `requests` re-resolves at connect
time, leaving a small DNS-rebinding window. Acceptable for the trusted personal
deploy; pin the resolved IP into the connection if the surface ever widens.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

from . import config
from .httpclient import request_with_backoff

DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class UnsafeURLError(Exception):
    """The target URL/host is not allowed (bad scheme or private/reserved IP)."""


def _ip_is_global(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    """All IPs a host maps to. Literal IPs resolve without a DNS lookup."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _host_is_safe(host: str, resolve: Callable[[str], list[str]] = _resolve) -> bool:
    try:
        ips = resolve(host)
    except socket.gaierror:
        return False
    # Reject if ANY resolved address is non-global — a host with one public and
    # one private A record must not slip through.
    return bool(ips) and all(_ip_is_global(ip) for ip in ips)


def _validate(
    url: str, allow_private: bool, resolve: Callable[[str], list[str]] = _resolve
) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme not allowed: {parsed.scheme or '(none)'!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    if not allow_private and not _host_is_safe(host, resolve):
        raise UnsafeURLError(f"host resolves to a private/reserved address: {host}")


def _read_capped(resp: requests.Response, max_bytes: int) -> requests.Response:
    """Read the streamed body up to `max_bytes` and cache it on the response so
    `.content`/`.text` work downstream. Raises if the body exceeds the cap."""
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            resp.close()
            raise UnsafeURLError(f"response exceeds {max_bytes} byte cap")
        chunks.append(chunk)
    resp._content = b"".join(chunks)  # requests caches body here for .content/.text
    resp._content_consumed = True
    return resp


def safe_get(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: int,
    headers: dict[str, str] | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_attempts: int = 4,
    allow_private: bool | None = None,
    resolve: Callable[[str], list[str]] = _resolve,
) -> requests.Response:
    """GET `url` with SSRF guards, backoff retries, manual redirect re-validation,
    and a body-size cap. Raises `UnsafeURLError` if any hop is unsafe."""
    if allow_private is None:
        allow_private = config.allow_private_fetch()
    sess = session or requests.Session()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _validate(current, allow_private, resolve)
        resp = request_with_backoff(
            lambda u=current: sess.get(
                u,
                timeout=timeout,
                headers=headers or {},
                allow_redirects=False,
                stream=True,
            ),
            max_attempts=max_attempts,
        )
        if resp.status_code in _REDIRECT_STATUSES and resp.headers.get("Location"):
            location = resp.headers["Location"]
            resp.close()
            current = urljoin(current, location)
            continue
        # Terminal response (incl. a redirect with no Location, and 304s): read the
        # capped body so `.content`/`.text` are usable downstream.
        return _read_capped(resp, max_bytes)
    raise UnsafeURLError(f"too many redirects (> {MAX_REDIRECTS})")
