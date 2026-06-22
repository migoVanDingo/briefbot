"""Prefixed ULID identifiers for bbv2 primary keys.

Every PK is an uppercase entity prefix concatenated (no separator) with a ULID
body — Crockford base32, 26 chars, e.g. ``SRC01J9Z3K7Q8XF6M2NQH4WZ8AB``.

A ULID is a 48-bit millisecond timestamp followed by 80 bits of randomness, so
IDs are time-sortable (lexicographic order == creation order) and collide with
negligible probability. We hand-roll it (no dependency) — the timestamp lives in
the high-order chars so a newer ID always sorts after an older one regardless of
the random suffix.

The content dedupe key (``url:``/``fallback:``) is separate and unchanged; these
IDs are only the surrogate PKs.
"""

from __future__ import annotations

import secrets
import time

# Crockford base32 — excludes I, L, O, U to avoid ambiguity.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Entity prefixes (3-letter uppercase).
ITEM = "ITM"
SOURCE = "SRC"
TOPIC = "TOP"
CLUSTER = "CLU"
FAVORITE = "FAV"
FOLDER = "FLD"
CONVERSATION = "CON"
MESSAGE = "MSG"
USER = "USR"
BRIEF = "BRF"
SESSION = "SES"
SPACE = "SPC"


def _encode(value: int, length: int) -> str:
    """Encode a non-negative int as a fixed-length Crockford base32 string."""
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def ulid(now_ms: int | None = None) -> str:
    """A 26-char Crockford-base32 ULID (48-bit time + 80-bit randomness)."""
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    timestamp = _encode(now_ms, 10)  # 48 bits → 10 chars
    randomness = _encode(int.from_bytes(secrets.token_bytes(10), "big"), 16)  # 80 → 16
    return timestamp + randomness


def new_id(prefix: str) -> str:
    """Mint a prefixed ULID PK, e.g. ``new_id(ids.SOURCE)`` → ``SRC01J9…``."""
    return f"{prefix}{ulid()}"
