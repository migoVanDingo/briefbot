"""In-memory per-key sliding-window rate limiter.

Single-process (one uvicorn): resets on restart, not shared across processes —
enough to stop spam / runaway LLM bills on a personal app. `now` is injectable
for tests. The dashboard wires this onto the expensive create/provision routes
and returns 429 + Retry-After on exceed.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from time import time as _time
from typing import Any


class RateLimiter:
    # Periodically drop keys idle longer than this so the dict can't grow without
    # bound as users/tokens accumulate over the process lifetime.
    _MAX_IDLE_S = 3600.0
    _SWEEP_EVERY = 1000

    def __init__(self) -> None:
        self._hits: dict[Any, deque] = defaultdict(deque)
        self._since_sweep = 0
        # FastAPI runs sync routes on the anyio worker-thread pool, so check()/
        # _sweep() are called concurrently from multiple threads. Without this lock
        # two threads can both pass the limit, and _sweep iterating `_hits` while
        # another thread inserts a key raises "dict changed size during iteration".
        self._lock = threading.Lock()

    def check(
        self, key: Any, *, limit: int, window_s: float, now: float | None = None
    ) -> tuple[bool, float]:
        """Record a hit for `key`. Returns (allowed, retry_after_seconds)."""
        now = _time() if now is None else now
        with self._lock:
            dq = self._hits[key]
            cutoff = now - window_s
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False, max(0.0, window_s - (now - dq[0]))
            dq.append(now)
            self._since_sweep += 1
            if self._since_sweep >= self._SWEEP_EVERY:
                self._sweep(now)
            return True, 0.0

    def _sweep(self, now: float) -> None:
        """Evict keys with no hit in the last `_MAX_IDLE_S` (they'd prune to empty
        on next access anyway). Caller holds `self._lock`."""
        self._since_sweep = 0
        idle = now - self._MAX_IDLE_S
        stale = [k for k, dq in self._hits.items() if not dq or dq[-1] <= idle]
        for k in stale:
            del self._hits[k]


# Process-wide limiter shared by the API routes.
limiter = RateLimiter()


def rate_limit_error(retry_after: float):
    """The canonical 429 for an exceeded rate limit — one shape across the consumer
    API, dashboard, and chat (was copy-pasted in three places)."""
    from fastapi import HTTPException

    return HTTPException(
        status_code=429,
        detail="Too many requests — slow down.",
        headers={"Retry-After": str(int(retry_after) + 1)},
    )
