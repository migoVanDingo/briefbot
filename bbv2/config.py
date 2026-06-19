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
