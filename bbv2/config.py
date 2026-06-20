"""bbv2 configuration — env-driven paths and HTTP settings.

bbv2 owns its own database and data dir; it never touches the original briefbot.
"""

from __future__ import annotations

import os
from pathlib import Path

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


def brave_api_key() -> str | None:
    return os.getenv("BRAVESEARCH_API_KEY") or None


# LLM — bbv2 uses Claude Haiku for all LLM work (cost).
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or None


def anthropic_model() -> str:
    return os.getenv("ANTHROPIC_MODEL") or ANTHROPIC_DEFAULT_MODEL


def firebase_config_path() -> str | None:
    return os.getenv("FIREBASE_CONFIG") or None


def admin_emails() -> set[str]:
    """Owner-only admin allowlist (lowercased). The ONLY way to grant admin —
    there is no API/UI/CLI to promote users. Set `ADMIN_EMAILS` in `.env`."""
    raw = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


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


def ratelimit_topic_create() -> tuple[int, float]:
    """(limit, window_seconds) for topic creation per user."""
    return _int_env("RL_TOPIC_CREATE_PER_HOUR", 5), 3600.0


def ratelimit_provision() -> tuple[int, float]:
    """(limit, window_seconds) for topic provisioning per user."""
    return _int_env("RL_PROVISION_PER_HOUR", 10), 3600.0




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
