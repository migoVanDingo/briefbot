"""Access-token JWTs for the dashboard session (0019).

bbv2 issues its OWN short-lived access token after exchanging a Firebase ID token
(see auth_api). The token is audience-scoped so it can't be replayed against a
different verifier, mirroring mass-platform's `jwt_utils`. The refresh token is a
separate opaque string in the DB — never a JWT.
"""

from __future__ import annotations

import time
from typing import Any

import jwt

from . import config

ISSUER = "bbv2"
AUDIENCE_ACCESS = "bbv2.user.access"
ALGORITHM = "HS256"


def build_access_token(
    user_id: int, session_id: str, *, now: int | None = None, ttl_s: int | None = None
) -> str:
    issued = int(now if now is not None else time.time())
    ttl = ttl_s if ttl_s is not None else config.access_ttl_s()
    payload = {
        "sub": str(user_id),
        "sid": session_id,
        "iat": issued,
        "exp": issued + ttl,
        "iss": ISSUER,
        "aud": AUDIENCE_ACCESS,
    }
    return jwt.encode(payload, config.jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + verify an access JWT (signature, issuer, audience, expiry).
    Raises `jwt.PyJWTError` subclasses on any failure — callers map to 401."""
    return jwt.decode(
        token,
        config.jwt_secret(),
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        audience=AUDIENCE_ACCESS,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )
