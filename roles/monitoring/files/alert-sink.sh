#!/bin/sh
# Failure notification delivery sink for aihost.
# Invoked by local-ai-alert with argv expansion only.
# Arguments: $1=unit, $2=timestamp, $3=context (optional)
set -eu

AUDIT_LOG="${AIHOST_ALERT_AUDIT_LOG:-/var/log/local-ai/alerts/audit.log}"
unit="${1:-unknown}"
ts="${2:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
context="${3:-none}"

mkdir -p "$(dirname "$AUDIT_LOG")"
printf '%s delivery=local_sink status=delivered unit=%s event_ts=%s context=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$unit" "$ts" "$context" >> "$AUDIT_LOG"
