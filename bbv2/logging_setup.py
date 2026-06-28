"""Central logging configuration for bbv2 (0026).

One init point — `configure_logging()` — called by the CLI entrypoint and
`serve`. Stdlib `logging` only (no deps). Logs go to stderr (so systemd/cron
capture them, see _documentation/devops.md) plus a rotating file in the log dir.

Levels: ERROR / WARNING / INFO (default) / DEBUG (verbose). Resolved from, in
order: an explicit `level=` arg, the `--verbose` flag (→DEBUG), `BBV2_LOG_LEVEL`,
then INFO. Format is `text` (default) or `json` via `BBV2_LOG_FORMAT`.

Never log secrets (tokens, keys, cookies, Authorization headers) — instrument
points pass ids/counts/durations, never raw credentials or bodies at INFO.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys

from . import config

# Third-party loggers that are chatty at INFO/DEBUG — pin to WARNING so our own
# logs stay readable.
_NOISY = ("httpx", "httpcore", "urllib3", "requests", "feedparser", "asyncio")

_configured = False


class _JsonFormatter(logging.Formatter):
    """Compact one-line JSON per record — for log shippers / structured search."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _resolve_level(level: str | None, verbose: bool) -> int:
    name = (level or ("DEBUG" if verbose else None) or config.log_level()).upper()
    return getattr(logging, name, logging.INFO)


def configure_logging(
    *, verbose: bool = False, level: str | None = None, fmt: str | None = None
) -> None:
    """Configure the `bbv2` logger tree. Idempotent: repeat calls only adjust the
    level (so `-v` can raise verbosity without duplicating handlers)."""
    global _configured
    root = logging.getLogger("bbv2")
    lvl = _resolve_level(level, verbose)
    root.setLevel(lvl)

    if _configured:
        for h in root.handlers:
            h.setLevel(lvl)
        return

    formatter: logging.Formatter
    if (fmt or config.log_format()).lower() == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(lvl)
    root.addHandler(console)

    try:  # rotating file handler is best-effort — console logging suffices alone
        d = config.log_dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            d / "bbv2.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(formatter)
        fh.setLevel(lvl)
        root.addHandler(fh)
    except OSError:
        pass

    root.propagate = False  # we own the handlers; don't double-log via the root
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """`bbv2.<name>` child logger — the canonical way modules get a logger."""
    return logging.getLogger(f"bbv2.{name}")
