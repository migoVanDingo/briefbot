#!/usr/bin/env bash
# Hourly collect runner for bbv2. Schedule on the always-on home server, e.g.
#   crontab:   0 * * * * /path/to/briefbot/scripts/collect.sh
#   (or a launchd plist on macOS, mirroring the original briefbot's setup)
#
# Keep this dumb: just the collect. The nightly LLM brief is a later phase.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

log_dir="${BBV2_LOG_DIR:-data/logs}"
mkdir -p "$log_dir"
python -m bbv2 collect >>"$log_dir/collect.$(date +%Y-%m-%d).log" 2>&1
