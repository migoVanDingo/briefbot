"""bbv2 configuration — env-driven paths and HTTP settings.

bbv2 owns its own database and data dir; it never touches the original briefbot.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional at runtime
    pass

USER_AGENT = "bbv2/0.1"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.getenv("BBV2_DB_PATH", str(_root() / "data" / "bbv2.db")))


def log_dir() -> Path:
    return Path(os.getenv("BBV2_LOG_DIR", str(_root() / "data" / "logs")))


def http_timeout() -> int:
    try:
        return int(os.getenv("BBV2_HTTP_TIMEOUT", "20"))
    except ValueError:
        return 20


def allow_private_fetch() -> bool:
    """Allow outbound fetches to resolve to private/reserved IPs. Default False so
    user-driven fetches (chat summarize, discovery, RSS) can't be steered at
    internal/metadata addresses. Set BBV2_ALLOW_PRIVATE_FETCH=true for local dev."""
    return _bool_env("BBV2_ALLOW_PRIVATE_FETCH", False)


def allowed_origins() -> list[str]:
    """CORS allowlist for the dashboard. An explicit list — never '*' with
    credentials. Defaults to the local Vite dev origins; set ALLOWED_ORIGINS
    (comma-separated) to add the Tailscale origin(s) for the family deploy."""
    raw = os.getenv("ALLOWED_ORIGINS", "")
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:5180", "http://127.0.0.1:5180"]


def serve_host() -> str:
    """Default bind host for `bbv2 serve` (override per-run with --host). Set
    BBV2_SERVE_HOST to the tailscale interface address for the family deploy."""
    return os.getenv("BBV2_SERVE_HOST", "127.0.0.1")


def brave_api_key() -> str | None:
    return os.getenv("BRAVESEARCH_API_KEY") or None


# LLM — bbv2 uses Claude Haiku for all LLM work (cost).
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or None


def anthropic_model() -> str:
    return os.getenv("ANTHROPIC_MODEL") or ANTHROPIC_DEFAULT_MODEL


# xAI Grok — a cheap model for high-volume, low-stakes structured work (story
# relevance classification). xAI's API is OpenAI-compatible. grok-3-mini is ~10x
# cheaper than Haiku for in/out tokens; set GROK_MODEL to a current id if the
# default is retired on your account.
GROK_DEFAULT_MODEL = "grok-3-mini"


def grok_api_key() -> str | None:
    return os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or None


def grok_model() -> str:
    return os.getenv("GROK_MODEL") or GROK_DEFAULT_MODEL


def relevance_provider() -> str:
    """Which provider classifies story relevance: 'grok' (default when a Grok key
    is set) or 'anthropic'. Grok work falls back to Haiku on error regardless."""
    explicit = os.getenv("RELEVANCE_PROVIDER")
    if explicit:
        return explicit.strip().lower()
    return "grok" if grok_api_key() else "anthropic"


def firebase_config_path() -> str | None:
    return os.getenv("FIREBASE_CONFIG") or None


def dashboard_url() -> str:
    """Public dashboard base URL, used in the nightly 'brief ready' email link."""
    return (os.getenv("DASHBOARD_URL") or "http://localhost:5180").rstrip("/")


def admin_emails() -> set[str]:
    """Owner-only admin allowlist (lowercased). The ONLY way to grant admin —
    there is no API/UI/CLI to promote users. Set `ADMIN_EMAILS` in `.env`."""
    raw = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


# ---- Auth sessions (0019): own access JWT + refresh token over cookies ----

import secrets as _secrets

# Process-stable fallback secret when BBV2_JWT_SECRET is unset (dev). Tokens then
# don't survive a restart — fine locally; `bbv2 serve` warns. Set BBV2_JWT_SECRET
# in production (see _documentation/devops.md) so sessions persist across deploys.
_FALLBACK_JWT_SECRET = _secrets.token_urlsafe(48)


def jwt_secret() -> str:
    return os.getenv("BBV2_JWT_SECRET") or _FALLBACK_JWT_SECRET


def jwt_secret_is_default() -> bool:
    """True when no BBV2_JWT_SECRET is configured (ephemeral per-process secret)."""
    return not os.getenv("BBV2_JWT_SECRET")


def access_ttl_s() -> int:
    """Lifetime of the short-lived access JWT (default 15 min)."""
    return _int_env("BBV2_ACCESS_TTL_S", 900)


def refresh_ttl_s() -> int:
    """Lifetime of the opaque refresh token / session (default 30 days)."""
    return _int_env("BBV2_REFRESH_TTL_S", 2_592_000)


def cookie_access_name() -> str:
    return os.getenv("BBV2_COOKIE_ACCESS", "bbv2_access")


def cookie_refresh_name() -> str:
    return os.getenv("BBV2_COOKIE_REFRESH", "bbv2_refresh")


def cookie_secure() -> bool:
    """Mark auth cookies Secure (HTTPS-only). Default False for local http dev;
    set BBV2_COOKIE_SECURE=true for the Tailscale HTTPS deploy."""
    return _bool_env("BBV2_COOKIE_SECURE", False)


def cookie_samesite() -> str:
    """SameSite policy for auth cookies. Strict is safe because the dashboard and
    API are same-site (nginx proxies /api in prod; same host in dev)."""
    val = (os.getenv("BBV2_COOKIE_SAMESITE", "strict") or "strict").strip().lower()
    return val if val in {"strict", "lax", "none"} else "strict"


def moderation_fail_closed() -> bool:
    """If the LLM moderation call fails, deny by default (safer). Set
    `MODERATION_FAIL_OPEN=true` to allow-on-error instead."""
    return os.getenv("MODERATION_FAIL_OPEN", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def token_budget() -> dict[str, Any]:
    """Per-user LLM token budget over a rolling window (default: 24h).

    A single limit covers the user's own agent work — chat, agent tasks, and the
    topic provisioning they initiate. Background/system work (scheduled collection,
    discovery, nightly briefs, shared rundowns) is metered to a system bucket and
    never charged to a user. Env-overridable; `TOKEN_LIMIT_ENABLED=false` tracks
    without enforcing. `TOKEN_CHAT_LIMIT` is still read for back-compat.
    """
    return {
        "enabled": _bool_env("TOKEN_LIMIT_ENABLED", True),
        "window_s": float(_int_env("TOKEN_WINDOW_S", 86400)),
        "limit": _int_env("TOKEN_LIMIT", _int_env("TOKEN_CHAT_LIMIT", 100_000)),
    }


def ratelimit_topic_create() -> tuple[int, float]:
    """(limit, window_seconds) for topic creation per user."""
    return _int_env("RL_TOPIC_CREATE_PER_HOUR", 5), 3600.0


def ratelimit_provision() -> tuple[int, float]:
    """(limit, window_seconds) for topic provisioning per user."""
    return _int_env("RL_PROVISION_PER_HOUR", 10), 3600.0


def ratelimit_default() -> tuple[int, float]:
    """General per-user limit applied to every dashboard `/api/*` route.
    Generous so normal browsing never trips it; just a runaway-client backstop."""
    return _int_env("RL_DEFAULT_PER_MIN", 120), 60.0


def ratelimit_chat() -> tuple[int, float]:
    """Tighter per-user limit for chat turns (each one costs tokens)."""
    return _int_env("RL_CHAT_PER_MIN", 20), 60.0


def ratelimit_consumer() -> tuple[int, float]:
    """Per-token limit for the read-only consumer API (per service account)."""
    return _int_env("RL_CONSUMER_PER_MIN", 120), 60.0


def default_discover_interval_min() -> int:
    """Default source-discovery cadence (minutes) when a topic has no override."""
    return _int_env("DISCOVER_INTERVAL_MIN_DEFAULT", 10_080)  # weekly


def default_collect_interval_min() -> int:
    """Default story-collection cadence (minutes) when a source/topic has none."""
    return _int_env("COLLECT_INTERVAL_MIN_DEFAULT", 360)  # 6h


def max_sources_per_topic() -> int:
    """Cap on candidate sources discovered/approved for a topic (keeps provisioning
    fast and the archive lean). Default for new topics; env-overridable."""
    return _int_env("MAX_SOURCES_PER_TOPIC", 5)


def max_stories_per_source() -> int:
    """Cap on stories ingested per source per collect (newest first)."""
    return _int_env("MAX_STORIES_PER_SOURCE", 7)


def collect_max_age_days() -> int:
    """Drop feed items whose published_at is older than this many days at collect
    time — some feeds carry stale entries that would pollute the archive. Set
    BBV2_COLLECT_MAX_AGE_DAYS=0 to disable the cutoff."""
    return _int_env("BBV2_COLLECT_MAX_AGE_DAYS", 14)


def onboard_brief_window_min() -> int:
    """How long after signup a user is still 'setting up': every topic they add in
    this window builds its Headlines brief immediately. After it, new topics defer
    to the nightly brief + on-demand rundowns. Account-age based (reload-proof)."""
    return _int_env("ONBOARD_BRIEF_WINDOW_MIN", 1440)  # 24h




def mailgun_config() -> dict[str, str] | None:
    """Mailgun settings if fully configured, else None (→ use LogNotifier).

    Auth uses the **sending** API key (MAILGUN_SENDING_API_KEY), matching the
    mass-platform convention; falls back to MAILGUN_API_KEY. Needs a from-address
    (MAILGUN_FROM or EMAIL_FROM).
    """
    api_key = os.getenv("MAILGUN_SENDING_API_KEY") or os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_DOMAIN")
    sender = os.getenv("MAILGUN_FROM") or os.getenv("EMAIL_FROM")
    if api_key and domain and sender:
        return {"api_key": api_key, "domain": domain, "from": sender}
    return None
