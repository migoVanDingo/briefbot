"""Auth + session routes (0019): Firebase exchange → bbv2 session, refresh, logout,
and owner-only user management.

The Firebase ID token is verified ONCE here, at /api/auth/exchange, and traded for
bbv2's own short-lived access JWT + an opaque refresh token (both HttpOnly
cookies). Everything else under /api/* authenticates against that session (see
dashboard_api.current_user). This is the only place the Firebase verifier runs.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Request, Response

from . import config, rbac
from .api import _bearer
from .authjwt import build_access_token
from .store import Store

log = logging.getLogger("bbv2.auth")

Verifier = Callable[[str], dict[str, Any]]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    common = dict(
        httponly=True,
        secure=config.cookie_secure(),
        samesite=config.cookie_samesite(),
        path="/",
    )
    response.set_cookie(
        config.cookie_access_name(), access, max_age=config.access_ttl_s(), **common
    )
    response.set_cookie(
        config.cookie_refresh_name(), refresh, max_age=config.refresh_ttl_s(), **common
    )


def _clear_auth_cookies(response: Response) -> None:
    # Mirror every attribute used when setting (path/samesite/secure/httponly) so
    # strict browsers reliably match and drop the cookie.
    for name in (config.cookie_access_name(), config.cookie_refresh_name()):
        response.delete_cookie(
            name,
            path="/",
            samesite=config.cookie_samesite(),
            secure=config.cookie_secure(),
            httponly=True,
        )


def add_auth_routes(
    app: FastAPI,
    store: Store,
    verifier: Verifier,
    current_user: Callable[..., dict[str, Any]],
    require_user_manage: Callable[..., dict[str, Any]],
) -> None:
    router = APIRouter(prefix="/api/auth")

    @router.post("/exchange")
    def exchange(
        request: Request,
        response: Response,
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        """Verify the Firebase ID token, upsert the user, open a session, and set
        the auth cookies. Auto-provisions the user's personal space (0019)."""
        token = _bearer(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="missing bearer token")
        try:
            claims = verifier(token)
        except Exception:
            raise HTTPException(status_code=401, detail="invalid token")
        email = claims.get("email")
        if not email:
            raise HTTPException(status_code=401, detail="token has no email")
        # Reject explicitly-unverified emails: Firebase email/password (and some
        # providers) issue valid tokens with email_verified=false before the user
        # proves they own the address. Trusting that would let an attacker register
        # the owner's email and inherit the owner account/role. Google sign-in (the
        # app's method) always sets it true; we only block an explicit false.
        if claims.get("email_verified") is False:
            raise HTTPException(status_code=403, detail="email not verified")
        name = claims.get("name") or email.split("@")[0]
        ip, ua = _client_ip(request), request.headers.get("user-agent")

        uid = store.add_user(name, email)  # upsert (auto-provision)
        # Owner-only bootstrap: an ADMIN_EMAILS match → 'owner'. Never demotes. An
        # explicitly-unverified email was already rejected above, so reaching here
        # means the email is verified (or the claim is absent, e.g. a test fake).
        if email.lower() in config.admin_emails():
            store.set_user_role(email, "owner")
        row = store.get_user(email)
        if row and (row["status"] or "active") != "active":
            store.log_auth_event(uid, "denied", ip, ua)
            log.warning("exchange denied: user %s is disabled", uid)
            raise HTTPException(status_code=403, detail="account disabled")

        store.touch_last_login(uid)
        store.ensure_personal_space(uid, name)
        sid, refresh = store.create_session(uid, ip, ua, config.refresh_ttl_s())
        _set_auth_cookies(response, build_access_token(uid, sid), refresh)
        store.log_auth_event(uid, "login", ip, ua)
        log.info("login: user %s (%s) from %s", uid, email, ip or "?")
        return {"ok": True, "user": {"id": uid, "email": email, "name": name}}

    @router.get("/session")
    def refresh_session(request: Request, response: Response) -> dict[str, Any]:
        """Rotate the refresh token and mint a fresh access JWT. The frontend calls
        this when an access token has expired (401)."""
        refresh = request.cookies.get(config.cookie_refresh_name())
        ip, ua = _client_ip(request), request.headers.get("user-agent")
        rotated = store.rotate_session(refresh or "", ip, ua, config.refresh_ttl_s()) if refresh else None
        if not rotated:
            _clear_auth_cookies(response)
            raise HTTPException(status_code=401, detail="no valid session")
        uid, new_sid, new_refresh = rotated
        row = store.get_user_by_id(uid)
        if not row or (row["status"] or "active") != "active":
            store.revoke_session(new_sid)
            _clear_auth_cookies(response)
            raise HTTPException(status_code=401, detail="account unavailable")
        _set_auth_cookies(response, build_access_token(uid, new_sid), new_refresh)
        store.log_auth_event(uid, "refresh", ip, ua)
        return {"ok": True}

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, Any]:
        refresh = request.cookies.get(config.cookie_refresh_name())
        if refresh:
            sess = store.get_session_by_refresh(refresh)
            store.revoke_session_by_refresh(refresh)
            if sess:
                store.log_auth_event(
                    int(sess["user_id"]), "logout", _client_ip(request),
                    request.headers.get("user-agent"),
                )
                log.info("logout: user %s", sess["user_id"])
        _clear_auth_cookies(response)
        return {"ok": True}

    # ---- owner-only user management (capability: user:manage) ----

    def _user_or_404(user_id: int):
        row = store.get_user_by_id(user_id)
        if not row:
            raise HTTPException(status_code=404, detail="unknown user")
        return row

    @router.get("/admin/users")
    def list_users(admin: dict = Depends(require_user_manage)) -> dict[str, Any]:
        return {
            "users": [
                {
                    "id": u["id"],
                    "email": u["email"],
                    "name": u["name"],
                    "role": u["role"],
                    "status": (u["status"] if "status" in u.keys() else "active") or "active",
                    "last_login_at": u["last_login_at"] if "last_login_at" in u.keys() else None,
                }
                for u in store.list_users()
            ]
        }

    @router.patch("/admin/users/{user_id}")
    def update_user(
        user_id: int, body: dict = Body(...), admin: dict = Depends(require_user_manage)
    ) -> dict[str, Any]:
        """Set a user's role and/or status. Owner is bootstrap-only (ADMIN_EMAILS),
        so it can't be assigned here; disabling also revokes the user's sessions."""
        row = _user_or_404(user_id)
        if "role" in body:
            role = body.get("role")
            if role not in rbac.ASSIGNABLE_ROLES:
                raise HTTPException(status_code=422, detail="invalid role")
            if row["role"] == "owner":
                raise HTTPException(status_code=403, detail="cannot change the owner")
            store.set_user_role(row["email"], role)
        if "status" in body:
            status = body.get("status")
            if status not in ("active", "disabled"):
                raise HTTPException(status_code=422, detail="invalid status")
            if row["role"] == "owner":
                raise HTTPException(status_code=403, detail="cannot disable the owner")
            store.set_user_status(row["email"], status)
            if status == "disabled":
                store.revoke_user_sessions(user_id)
                store.log_auth_event(user_id, "disabled")
        return {"ok": True}

    @router.post("/admin/users/{user_id}/revoke-sessions")
    def revoke_sessions(
        user_id: int, admin: dict = Depends(require_user_manage)
    ) -> dict[str, Any]:
        _user_or_404(user_id)
        revoked = store.revoke_user_sessions(user_id)
        store.log_auth_event(user_id, "revoked", None, None)
        return {"ok": True, "revoked": revoked}

    @router.get("/admin/auth-events")
    def auth_events(
        limit: int = 100, user_id: int | None = None, admin: dict = Depends(require_user_manage)
    ) -> dict[str, Any]:
        rows = store.list_auth_events(limit=max(1, min(limit, 500)), user_id=user_id)
        return {
            "events": [
                {
                    "id": e["id"],
                    "user_id": e["user_id"],
                    "event": e["event"],
                    "ip": e["ip"],
                    "created_at": e["created_at"],
                }
                for e in rows
            ]
        }

    app.include_router(router)
