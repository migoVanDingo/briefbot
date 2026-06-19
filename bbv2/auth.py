"""Firebase auth for the dashboard API.

`verify_token` checks a Firebase ID token via firebase-admin (initialized from the
service-account JSON at FIREBASE_CONFIG). The dashboard routes take the verifier
as an injectable callable so they can be tested offline with a fake.
"""

from __future__ import annotations

from typing import Any

from .config import firebase_config_path

_initialized = False


def _init_firebase() -> None:
    global _initialized
    if _initialized:
        return
    import firebase_admin
    from firebase_admin import credentials

    if not firebase_admin._apps:
        path = firebase_config_path()
        if not path:
            raise RuntimeError("FIREBASE_CONFIG is not set")
        firebase_admin.initialize_app(credentials.Certificate(path))
    _initialized = True


def verify_token(id_token: str) -> dict[str, Any]:
    """Verify a Firebase ID token → decoded claims (email, name, uid, …)."""
    _init_firebase()
    from firebase_admin import auth as fb_auth

    # clock_skew tolerance mirrors mass-platform (absorbs VM clock drift).
    return fb_auth.verify_id_token(id_token, clock_skew_seconds=10)
