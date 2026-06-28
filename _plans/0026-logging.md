# 0026 — Application logging

Right now nothing meaningful lands in the logs. Add structured, level-based
logging across the app (server, CLI/cron, LLM, background jobs, auth) with a
verbose/debug mode. Stdlib `logging` only — no new deps; the systemd unit and
cron already capture stdout/stderr (see `devops.md`), so logging to stderr is
enough to make `journalctl -u bbv2` and the cron logs useful.

## Goals

- One init point: `bbv2/logging_setup.py::configure_logging()` — idempotent,
  called by `serve`, `tick`, `nightly`, and the CLI entrypoint.
- Levels: ERROR / WARNING / INFO (default) / DEBUG (verbose). Env-driven:
  `BBV2_LOG_LEVEL` (default `INFO`), `BBV2_LOG_FORMAT` (`text` default | `json`),
  `--verbose/-v` CLI flag → DEBUG.
- Per-module loggers via `logging.getLogger("bbv2.<module>")` — no root spam;
  quiet noisy third parties (`httpx`, `urllib3`, `feedparser`) to WARNING.
- Don't log secrets (tokens, keys, cookies, full Authorization headers).

## Phases

- **P1 — Core.** `logging_setup.py`: `configure_logging(level=None, fmt=None)`
  builds a `StreamHandler(sys.stderr)` with a compact formatter
  (`%(asctime)s %(levelname)s %(name)s %(message)s`) or a JSON formatter when
  `BBV2_LOG_FORMAT=json`. Idempotent (guard against double-handlers). Add the
  config getters (`log_level()`, `log_format()`).
- **P2 — Entrypoints.** Call it at the top of `serve`, `tick`, `nightly`, and
  `main()` in `cli.py`; add a global `-v/--verbose` arg. Pass uvicorn
  `log_config=None` / align uvicorn access logs to our level so request logs show.
- **P3 — Instrument hot paths (INFO + DEBUG).**
  - LLM (`llm.py`/`httpclient.py`): DEBUG per request (model, purpose, token
    in/out, latency, retries); WARNING on retry; ERROR on give-up. Never log
    bodies at INFO.
  - Background jobs (`provision_runner.py`, `topic_image.py`): INFO on
    start/stage/done/error per run (already have run rows; add logs).
  - Collect/discover/nightly/tick: INFO summary lines (counts, durations).
  - Auth (`auth_api.py`): INFO login/refresh/logout/denied (mirror `auth_events`),
    never the token.
  - Errors: replace silent `except: pass` with `logger.exception(...)` /
    `logger.warning(...)` where a failure is being swallowed (e.g. click beacon,
    image gen) so they're at least visible at DEBUG/WARNING.
- **P4 — Request errors.** A FastAPI exception log: 5xx → `logger.exception`,
  4xx stays quiet (expected). Add a tiny middleware or use the existing handlers.

## Tests

- `configure_logging` is idempotent (no duplicate handlers on repeat calls).
- Level resolves from env + explicit arg (arg wins).
- A smoke test that an instrumented path emits the expected logger/level via
  `caplog`.

No behavior changes — purely observability. Keep diffs small per module.
</content>
