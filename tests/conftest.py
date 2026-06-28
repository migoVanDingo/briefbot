"""Shared pytest setup.

Keep the suite **hermetic** — independent of whatever is in the developer's (or
CI's) `.env`. In particular the auth tests (0019) exchange a session cookie via
the FastAPI TestClient, which talks plain `http://testserver`; if a real `.env`
sets `BBV2_COOKIE_SECURE=true`, the client silently refuses to store the Secure
cookie and every authenticated request 401s. Force the auth-relevant config to
test-safe values here so results don't depend on the environment.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _hermetic_auth_env():
    # Cookies must be storable over http://testserver, and the JWT secret stable.
    os.environ["BBV2_COOKIE_SECURE"] = "false"
    os.environ["BBV2_COOKIE_SAMESITE"] = "lax"
    os.environ.setdefault("BBV2_JWT_SECRET", "test-secret-not-for-prod")
    # Never fire real Grok image generation from a test (brief endpoints kick it).
    os.environ["TOPIC_IMAGES_ENABLED"] = "false"
    yield
