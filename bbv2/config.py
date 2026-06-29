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


def log_level() -> str:
    """Log verbosity (ERROR/WARNING/INFO/DEBUG). Default INFO; `-v` → DEBUG."""
    return (os.getenv("BBV2_LOG_LEVEL", "INFO") or "INFO").strip().upper()


def log_format() -> str:
    """Log format: 'text' (default) or 'json' for structured shipping."""
    return (os.getenv("BBV2_LOG_FORMAT", "text") or "text").strip().lower()


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


# OpenAI text embeddings (0030) — power the topic embedding index + evidence-based
# source routing. Plain HTTP (no SDK), same as our other LLM calls.
OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
OPENAI_EMBED_DEFAULT_MODEL = "text-embedding-3-small"


def openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or None


def openai_embed_model() -> str:
    return os.getenv("OPENAI_EMBED_MODEL") or OPENAI_EMBED_DEFAULT_MODEL


def embeddings_enabled() -> bool:
    """Topic embeddings + evidence-based routing need an OpenAI key. Without one,
    routing falls back to agent judgment (0030)."""
    return bool(openai_api_key())


def embed_price() -> float:
    """Estimated USD per 1M embedding tokens, for the metrics ballpark (0030)."""
    return _float_env("OPENAI_EMBED_PRICE", 0.02)


def embed_centroid_days() -> int:
    """A topic's vector = centroid of its brief embeddings over the last N days."""
    return _int_env("EMBED_CENTROID_DAYS", 30)


def placement_min() -> float:
    """Min cosine for a source to be placed in an existing topic (0030). Below this
    for every topic → create a new topic. Calibrate against real score logs."""
    return _float_env("BBV2_PLACEMENT_MIN", 0.32)


def placement_multi() -> float:
    """Cosine at/above which a source is ALSO attached to a secondary topic (0030)."""
    return _float_env("BBV2_PLACEMENT_MULTI", 0.45)


def grok_model() -> str:
    return os.getenv("GROK_MODEL") or GROK_DEFAULT_MODEL


# Grok Imagine — per-topic header images (system call; reuses GROK_API_KEY).
GROK_IMAGE_DEFAULT_MODEL = "grok-imagine-image-quality"
GROK_IMAGE_URL = "https://api.x.ai/v1/images/generations"


def grok_image_model() -> str:
    return os.getenv("GROK_IMAGE_MODEL") or GROK_IMAGE_DEFAULT_MODEL


def grok_image_url() -> str:
    return os.getenv("GROK_IMAGE_URL") or GROK_IMAGE_URL


def topic_images_dir() -> Path:
    return Path(os.getenv("BBV2_TOPIC_IMAGES_DIR", str(_root() / "data" / "topic_images")))


def topic_images_enabled() -> bool:
    """Generate a per-topic header image (Grok Imagine). Needs a Grok key; set
    TOPIC_IMAGES_ENABLED=false to turn it off."""
    return _bool_env("TOPIC_IMAGES_ENABLED", True) and bool(grok_api_key())


def avatars_dir() -> Path:
    return Path(os.getenv("BBV2_AVATARS_DIR", str(_root() / "data" / "avatars")))


def avatars_enabled() -> bool:
    """Allow Grok-generated profile avatars (0028). Needs a Grok key; the default
    identicon works regardless. Set AVATARS_ENABLED=false to disable generation."""
    return _bool_env("AVATARS_ENABLED", True) and bool(grok_api_key())


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


def provision_workers() -> int:
    """Max concurrent background provisioning runs (0023). Caps load on Brave/feeds;
    excess runs queue."""
    return _int_env("PROVISION_WORKERS", 3)


def discovery_preview_max() -> int:
    """Candidate feeds to surface in an on-demand `find_sources` preview (0030).
    Kept small so the background search stays snappy."""
    return _int_env("BBV2_DISCOVERY_PREVIEW_MAX", 6)


def scheduler_window_min() -> int:
    """The `bbv2 tick` heartbeat interval (minutes) — also the window a `daily`/
    `weekly` discovery slot fires in. MUST match the server crontab (0020 sets it
    to */15). If a tick is missed, a daily slot is skipped that day (no catch-up)."""
    return _int_env("SCHEDULER_WINDOW_MIN", 15)


def max_sources_per_topic() -> int:
    """Cap on candidate sources discovered/approved for a topic (keeps provisioning
    fast and the archive lean). Default for new topics; env-overridable."""
    return _int_env("MAX_SOURCES_PER_TOPIC", 5)


def max_stories_per_source() -> int:
    """Cap on stories ingested per source per collect (newest first)."""
    return _int_env("MAX_STORIES_PER_SOURCE", 7)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def llm_prices() -> dict[str, dict[str, float]]:
    """USD per 1M tokens, per model family, for the **estimated** cost metrics
    (0021) — there's no live billing API. Env-overridable as prices change.
    Defaults are ballpark public list prices for grok-3-mini / Claude Haiku."""
    return {
        "grok": {
            "in": _float_env("GROK_PRICE_IN", 0.30),
            "out": _float_env("GROK_PRICE_OUT", 0.50),
        },
        "haiku": {
            "in": _float_env("HAIKU_PRICE_IN", 1.00),
            "out": _float_env("HAIKU_PRICE_OUT", 5.00),
        },
    }


def image_price() -> float:
    """Estimated USD per generated image (Grok Imagine, 0027) — images bill per
    image, not per token. Env-overridable as pricing changes."""
    return _float_env("GROK_IMAGE_PRICE", 0.02)


def collect_max_age_days() -> int:
    """Drop feed items whose published_at is older than this many days at collect
    time — some feeds carry stale entries that would pollute the archive. Set
    BBV2_COLLECT_MAX_AGE_DAYS=0 to disable the cutoff."""
    return _int_env("BBV2_COLLECT_MAX_AGE_DAYS", 14)


def source_drop_threshold() -> int:
    """Disable a source after this many CONSECUTIVE droppable-4xx fetch failures
    (0029). Any successful fetch resets the streak; 410 Gone drops immediately.
    Set BBV2_SOURCE_DROP_THRESHOLD=0 to disable auto-dropping entirely."""
    return _int_env("BBV2_SOURCE_DROP_THRESHOLD", 3)


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
