"""Outbound exponential-backoff retry (`bbv2.httpclient`)."""

import requests

from bbv2.httpclient import request_with_backoff


class _Resp:
    def __init__(self, status_code: int, retry_after: str | None = None):
        self.status_code = status_code
        self.headers = {"Retry-After": retry_after} if retry_after else {}


def _no_sleep(_seconds):  # record nothing, never actually wait
    pass


def test_retries_then_succeeds():
    seq = [_Resp(429), _Resp(503), _Resp(200)]
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        return seq.pop(0)

    out = request_with_backoff(do, sleep=_no_sleep, rand=lambda: 0.0)
    assert out.status_code == 200
    assert calls["n"] == 3


def test_non_retryable_returns_immediately():
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        return _Resp(404)

    out = request_with_backoff(do, sleep=_no_sleep)
    assert out.status_code == 404
    assert calls["n"] == 1


def test_gives_up_after_max_attempts():
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        return _Resp(429)

    out = request_with_backoff(do, max_attempts=3, sleep=_no_sleep, rand=lambda: 0.0)
    assert out.status_code == 429
    assert calls["n"] == 3  # no extra attempt beyond the cap


def test_honors_numeric_retry_after():
    waits = []
    seq = [_Resp(429, retry_after="7"), _Resp(200)]

    out = request_with_backoff(
        lambda: seq.pop(0), sleep=waits.append, rand=lambda: 0.0
    )
    assert out.status_code == 200
    assert waits == [7.0]


def test_retries_connection_errors_then_raises():
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise requests.ConnectionError("boom")

    try:
        request_with_backoff(do, max_attempts=3, sleep=_no_sleep, rand=lambda: 0.0)
        assert False, "expected ConnectionError to propagate"
    except requests.ConnectionError:
        pass
    assert calls["n"] == 3
