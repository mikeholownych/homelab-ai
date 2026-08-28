#!/bin/sh
# Failure-notification hook for aihost systemd units. Invoked by
# aihost-alert@.service with the failed unit name as $1.
#
# Behavior: append a structured line to the local alert log always; if an alert
# command is configured in /etc/local-ai/alert.env (AIHOST_ALERT_COMMAND), it is
# executed via argv expansion only - unit names and log content are passed as
# arguments, never interpolated into a shell string.
set -eu

# Runtime configuration lands in monitoring.env (role-templated). The script is
# installed via copy, so it carries no Jinja markers itself and uses defaults
# when the config file is absent.
ENV_FILE="${AIHOST_MONITORING_ENV:-/etc/local-ai/monitoring.env}"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

LOG_DIR="${MONITORING_ALERT_LOG_DIR:-/var/log/local-ai/alerts}"
LOG_FILE="$LOG_DIR/alerts.log"
ALERT_ENV_FILE="/etc/local-ai/alert.env"

unit="${1:-unknown-unit}"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$LOG_DIR"
printf '%s unit=%s state=failed\n' "$ts" "$unit" >>"$LOG_FILE"

if [ ! -f "$ALERT_ENV_FILE" ]; then
    exit 0
fi
# shellcheck disable=SC1090
. "$ALERT_ENV_FILE"

if [ -n "${AIHOST_ALERT_COMMAND:-}" ]; then
    # Deliberate exec-by-name: no shell interpolation of untrusted content.
    "$AIHOST_ALERT_COMMAND" "$unit" "$ts"
fi