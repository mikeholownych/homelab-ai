#!/bin/sh
# Sustained stability observation for vllm-top-console.service.
#
# Samples the running console every 30s for a fixed duration (default
# 3600s = 60 minutes) and appends structured, timestamped measurements to
# a CSV evidence file, plus a separate error log for anything worth
# flagging. Designed to be launched detached (nohup ... & disown) so it
# outlives any single shell/tool-call session — the observation itself
# doesn't depend on anything staying "connected" to it.
#
# Usage: stability-observation.sh <output_csv> <error_log> [duration_s] [interval_s]

set -u
OUT="${1:?output csv path required}"
ERRLOG="${2:?error log path required}"
DURATION="${3:-3600}"
INTERVAL="${4:-30}"
UNIT="vllm-top-console.service"

echo "timestamp,pid,start_time,active_state,n_restarts,rss_kib,vsz_kib,cpu_pct,threads,fd_count,child_count,zombie_count_system,zombie_count_children,xpu_smi_children" > "$OUT"

echo "$(date -u +%FT%TZ) observation started, duration=${DURATION}s interval=${INTERVAL}s" >> "$ERRLOG"

END=$(( $(date +%s) + DURATION ))
LAST_ONCE_CHECK=0

while [ "$(date +%s)" -lt "$END" ]; do
  TS="$(date -u +%FT%TZ)"
  PID="$(systemctl show -p MainPID --value "$UNIT" 2>/dev/null)"
  ACTIVE="$(systemctl show -p ActiveState --value "$UNIT" 2>/dev/null)"
  NRESTARTS="$(systemctl show -p NRestarts --value "$UNIT" 2>/dev/null)"

  if [ -n "$PID" ] && [ "$PID" != "0" ] && [ -d "/proc/$PID" ]; then
    START="$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/,/;/g' | xargs)"
    RSS="$(ps -o rss= -p "$PID" 2>/dev/null | xargs)"
    VSZ="$(ps -o vsz= -p "$PID" 2>/dev/null | xargs)"
    CPU="$(ps -o %cpu= -p "$PID" 2>/dev/null | xargs)"
    THREADS="$(ps -o nlwp= -p "$PID" 2>/dev/null | xargs)"
    FDCOUNT="$(ls "/proc/$PID/fd" 2>/dev/null | wc -l | xargs)"
    CHILDREN="$(pgrep -P "$PID" 2>/dev/null | wc -l | xargs)"
    CHILD_ZOMBIES="$(ps --ppid "$PID" -o stat= 2>/dev/null | grep -c '^Z')"
    XPUSMI="$(pgrep -f 'xpu-smi' 2>/dev/null | wc -l | xargs)"
  else
    START="none"; RSS=0; VSZ=0; CPU=0; THREADS=0; FDCOUNT=0; CHILDREN=0; CHILD_ZOMBIES=0; XPUSMI=0
    echo "$TS MainPID unavailable or process missing (PID='$PID', active='$ACTIVE')" >> "$ERRLOG"
  fi

  ZOMBIES_SYSTEM="$(ps -eo stat= 2>/dev/null | grep -c '^Z')"

  echo "$TS,$PID,\"$START\",$ACTIVE,$NRESTARTS,$RSS,$VSZ,$CPU,$THREADS,$FDCOUNT,$CHILDREN,$ZOMBIES_SYSTEM,$CHILD_ZOMBIES,$XPUSMI" >> "$OUT"

  # Every ~5 minutes, independently verify metrics collection is still
  # actually working against the real server, using the existing --once
  # diagnostic path (not a new dependency, not extra load on the console
  # itself) rather than trying to introspect the running TUI's internals.
  NOW="$(date +%s)"
  if [ $(( NOW - LAST_ONCE_CHECK )) -ge 300 ]; then
    if ! /home/mike/.cargo/bin/vllm-top -u http://127.0.0.1:8000 --once >/tmp/stability-once-check.$$ 2>&1; then
      echo "$TS --once check failed:" >> "$ERRLOG"
      cat /tmp/stability-once-check.$$ >> "$ERRLOG"
    fi
    rm -f /tmp/stability-once-check.$$
    LAST_ONCE_CHECK="$NOW"
  fi

  sleep "$INTERVAL"
done

echo "$(date -u +%FT%TZ) observation completed (ran for ${DURATION}s)" >> "$ERRLOG"
