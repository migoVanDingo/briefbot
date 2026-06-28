"""Role-based access control: named capabilities, resolved globally + per-space.

bbv2 uses named capability strings (e.g. ``sources:approve``) rather than
mass-platform's permission bit-masks — simpler at personal scale, still
composable. A user's GLOBAL role grants global capabilities; membership in a
SPACE grants capabilities within that space (0019 spaces foundation).

The owner role holds the wildcard ``*`` (every capability). ``has_capability``
treats ``*`` as a match for anything.
"""

from __future__ import annotations

WILDCARD = "*"

# Global role → capabilities. The legacy 'human' role (pre-0019 default) maps to
# the same baseline as 'user'.
_GLOBAL_ROLE_CAPS: dict[str, set[str]] = {
    "owner": {WILDCARD},
    "admin": {
        "topics:curate",
        "sources:approve",
        "brief:generate",
        "cadence:set",
        "token:manage",
        "user:read",
        "metrics:read",
        "admin:read",
    },
    "user": {"topics:create", "topics:subscribe", "chat:use"},
    "service": {"api:read"},
}
# Note: only the owner role holds the wildcard, so only the owner can manage users
# (disable/role/revoke). 'user:manage' is never granted to any other role.

# Space-membership role → capabilities within that space.
_SPACE_ROLE_CAPS: dict[str, set[str]] = {
    "owner": {"space:read", "space:write", "space:manage"},
    "editor": {"space:read", "space:write"},
    "viewer": {"space:read"},
}

# The full set of global roles an owner may assign (owner itself is bootstrap-only
# via ADMIN_EMAILS, so it's excluded from the assignable set).
ASSIGNABLE_ROLES = ("admin", "user", "service")


def global_capabilities(role: str | None) -> set[str]:
    if role in _GLOBAL_ROLE_CAPS:
        return set(_GLOBAL_ROLE_CAPS[role])
    return set(_GLOBAL_ROLE_CAPS["user"])  # 'human'/unknown → baseline user


def space_capabilities(space_role: str | None) -> set[str]:
    if not space_role:
        return set()
    return set(_SPACE_ROLE_CAPS.get(space_role, set()))


def resolve_capabilities(role: str | None, space_role: str | None = None) -> set[str]:
    """Effective capabilities = global role caps ∪ space-membership caps."""
    return global_capabilities(role) | space_capabilities(space_role)


def has_capability(caps: set[str], capability: str) -> bool:
    return WILDCARD in caps or capability in caps
