"""Shared outbound HTTP retry with exponential backoff + jitter.

Every bbv2 call to a third-party API (Anthropic, Brave, RSS feeds, site/article
fetches) goes through `request_with_backoff` so transient failures and rate-limit
responses are retried consistently: retryable HTTP statuses (429 + 5xx, incl.
Anthropic's 529 "overloaded") and connection errors back off exponentially with
jitter, honoring a numeric `Retry-After`. Non-retryable responses (4xx other than
429) return immediately for the caller to handle.

`sleep` and `rand` are injectable so tests run instantly and deterministically.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Iterable

import requests

# 429 = rate-limited; 5xx = server/transient; 529 = Anthropic "overloaded".
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})


def _delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    retry_after: str | None,
    rand: Callable[[], float],
) -> float:
    """Seconds to wait before `attempt`+1: honor a numeric Retry-After, else
    exponential backoff (base·2^(attempt-1)) plus up to 25% jitter, capped."""
    if retry_after and str(retry_after).strip().isdigit():
        return min(max_delay, float(retry_after))
    backoff = base_delay * (2 ** (attempt - 1))
    return min(max_delay, backoff + backoff * 0.25 * rand())


def request_with_backoff(
    do_request: Callable[[], requests.Response],
    *,
    max_attempts: int = 4,
    retry_statuses: Iterable[int] = RETRY_STATUSES,
    base_delay: float = 0.5,
    max_delay: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> requests.Response:
    """Call `do_request` (a thunk returning a Response), retrying retryable
    failures with exponential backoff. Returns the final Response; re-raises the
    last connection error if every attempt failed to connect."""
    retry = set(retry_statuses)
    last_exc: Exception | None = None
    resp: requests.Response | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = do_request()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            sleep(_delay(attempt, base_delay, max_delay, None, rand))
            continue
        if resp.status_code not in retry or attempt == max_attempts:
            return resp
        sleep(_delay(attempt, base_delay, max_delay, resp.headers.get("Retry-After"), rand))
    if resp is not None:  # pragma: no cover - loop always returns/raises first
        return resp
    raise last_exc or RuntimeError("request_with_backoff made no attempts")
