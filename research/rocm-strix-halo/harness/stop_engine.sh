#!/usr/bin/env bash
# Leave the APU idle: remove rocm-bake-* containers and kill the native engine
# PID recorded in /tmp/rocm-bake-engine.pid (if any). Safe to run repeatedly.
set -uo pipefail

RUNTIME="${CONTAINER_RUNTIME:-podman}"
PIDFILE="${ROCM_BAKE_PIDFILE:-/tmp/rocm-bake-engine.pid}"

if command -v "$RUNTIME" >/dev/null 2>&1; then
  ids="$("$RUNTIME" ps -a --filter 'name=^rocm-bake-' --format '{{.Names}}' 2>/dev/null || true)"
  if [[ -n "$ids" ]]; then
    # shellcheck disable=SC2086
    "$RUNTIME" rm -f -t 5 $ids >/dev/null 2>&1 || true
    echo "stop_engine: removed containers: $(echo $ids)"
  fi
fi

if [[ -f "$PIDFILE" ]]; then
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    echo "stop_engine: killed pid $pid"
  fi
  rm -f "$PIDFILE"
fi
exit 0
