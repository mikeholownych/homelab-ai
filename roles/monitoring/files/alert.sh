#!/bin/sh
# Failure-notification hook for aihost systemd units. Invoked by
# aihost-alert@.service with the failed unit name as $1.
#
# Behavior: append a structured line to the local alert log always; if an alert
# command is configured in /etc/local-ai/alert.env (AIHOST_ALERT_COMMAND), it is
# executed via argv expansion only - unit names and log content are passed as
# arguments, never interpolated into a shell string.
set -eu

LOG_DIR="{{ monitoring_alert_log_dir }}"
LOG_FILE="$LOG_DIR/alerts.log"
ENV_FILE="/etc/local-ai/alert.env"

unit="${1:-unknown-unit}"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$LOG_DIR"
printf '%s unit=%s state=failed\n' "$ts" "$unit" >>"$LOG_FILE"

if [ ! -f "$ENV_FILE" ]; then
    exit 0
fi
# shellcheck disable=SC1090
. "$ENV_FILE"

if [ -n "${AIHOST_ALERT_COMMAND:-}" ]; then
    # Deliberate exec-by-name: no shell interpolation of untrusted content.
    "$AIHOST_ALERT_COMMAND" "$unit" "$ts"
fi
