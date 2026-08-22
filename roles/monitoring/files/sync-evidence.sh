#!/bin/sh
# Append-only evidence mirror. Runs under aihost-evidence-sync.timer when the
# operator enables off-host durability. rsync archive without --delete so the
# source of record is never trimmed by a sync job.
set -eu

SOURCE="{{ monitoring_evidence_source_dir }}/"
DESTINATION="{{ monitoring_evidence_sync_destination }}"
LOG_FILE="{{ monitoring_log_dir }}/evidence-sync.log"

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -z "$DESTINATION" ]; then
    printf '%s destination-not-configured\n' "$ts" >>"$LOG_FILE"
    exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
rsync -a --timeout=600 "$SOURCE" "$DESTINATION" >>"$LOG_FILE" 2>&1
printf '%s sync-complete destination=%s\n' "$ts" "$DESTINATION" >>"$LOG_FILE"
