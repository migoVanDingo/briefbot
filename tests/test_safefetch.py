"""SSRF guard tests for bbv2.safefetch — fully offline (resolver injected)."""

from __future__ import annotations

import pytest

from bbv2 import safefetch
from bbv2.safefetch import UnsafeURLError, _ip_is_global, _validate


def _resolve_to(ip: str):
    return lambda host: [ip]


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "192.168.1.1",  # private
        "172.16.0.1",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",  # unspecified
        "::1",  # ipv6 loopback
        "fd00::1",  # ipv6 ULA (private)
        "fe80::1",  # ipv6 link-local
    ],
)
def test_private_and_reserved_ips_rejected(ip):
    assert _ip_is_global(ip) is False
    with pytest.raises(UnsafeURLError):
        _validate("http://host.example/", allow_private=False, resolve=_resolve_to(ip))


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_public_ips_allowed(ip):
    assert _ip_is_global(ip) is True
    _validate("https://example.com/feed", allow_private=False, resolve=_resolve_to(ip))


def test_non_http_scheme_rejected():
    for url in ("file:///etc/passwd", "ftp://example.com", "gopher://x"):
        with pytest.raises(UnsafeURLError):
            _validate(url, allow_private=False, resolve=_resolve_to("8.8.8.8"))


def test_no_host_rejected():
    with pytest.raises(UnsafeURLError):
        _validate("http:///nohost", allow_private=False, resolve=_resolve_to("8.8.8.8"))


def test_allow_private_escape_hatch_skips_check():
    # With allow_private=True the resolver is never consulted (dev opt-out).
    _validate("http://127.0.0.1:8080/", allow_private=True, resolve=_resolve_to("127.0.0.1"))


def test_mixed_records_rejected():
    # A host with one public and one private address must be rejected.
    assert (
        safefetch._host_is_safe("h", resolve=lambda host: ["8.8.8.8", "10.0.0.1"])
        is False
    )


def test_unresolvable_host_rejected():
    import socket

    def boom(host):
        raise socket.gaierror("nope")

    assert safefetch._host_is_safe("nx.invalid", resolve=boom) is False


# ---- safe_get redirect + body-cap behavior (fake session, no network) --------


class _FakeResp:
    def __init__(self, status_code, headers=None, body=b"ok"):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.closed = False
        self._content = None
        self._content_consumed = False

    def iter_content(self, _n):
        yield self._body

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self._responses.pop(0)


_PUBLIC = lambda host: ["8.8.8.8"]  # noqa: E731 - test resolver stub


def test_safe_get_follows_redirect_and_revalidates():
    sess = _FakeSession(
        [
            _FakeResp(302, {"Location": "https://example.com/final"}),
            _FakeResp(200, body=b"feed-body"),
        ]
    )
    resp = safefetch.safe_get(
        "https://example.com/start", session=sess, timeout=5, resolve=_PUBLIC
    )
    assert resp.status_code == 200 and resp._content == b"feed-body"
    assert sess.calls == ["https://example.com/start", "https://example.com/final"]


def test_safe_get_redirect_without_location_returns_readable_body():
    # Regression: a 3xx with no Location must NOT come back closed+bodyless (which
    # made downstream .content/.text raise). It should be read + returned.
    sess = _FakeSession([_FakeResp(302, {}, body=b"")])
    resp = safefetch.safe_get(
        "https://example.com/x", session=sess, timeout=5, resolve=_PUBLIC
    )
    assert resp.status_code == 302 and resp._content == b""


def test_safe_get_blocks_redirect_to_private_host():
    sess = _FakeSession([_FakeResp(302, {"Location": "http://169.254.169.254/"})])

    def resolve(host):
        return ["8.8.8.8"] if host == "example.com" else ["169.254.169.254"]

    with pytest.raises(UnsafeURLError):
        safefetch.safe_get(
            "https://example.com/start", session=sess, timeout=5, resolve=resolve
        )


def test_safe_get_enforces_byte_cap():
    sess = _FakeSession([_FakeResp(200, body=b"x" * 100)])
    with pytest.raises(UnsafeURLError):
        safefetch.safe_get(
            "https://example.com/big",
            session=sess,
            timeout=5,
            max_bytes=10,
            resolve=_PUBLIC,
        )
