"""In-memory per-key sliding-window rate limiter.

Single-process (one uvicorn): resets on restart, not shared across processes —
enough to stop spam / runaway LLM bills on a personal app. `now` is injectable
for tests. The dashboard wires this onto the expensive create/provision routes
and returns 429 + Retry-After on exceed.
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import time as _time
from typing import Any


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[Any, deque] = defaultdict(deque)

    def check(
        self, key: Any, *, limit: int, window_s: float, now: float | None = None
    ) -> tuple[bool, float]:
        """Record a hit for `key`. Returns (allowed, retry_after_seconds)."""
        now = _time() if now is None else now
        dq = self._hits[key]
        cutoff = now - window_s
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False, max(0.0, window_s - (now - dq[0]))
        dq.append(now)
        return True, 0.0


# Process-wide limiter shared by the API routes.
limiter = RateLimiter()
