#!/bin/sh
# vLLM readiness observer. Spawned as a background child by the launcher
# (vllm-xpu-runner.sh) BEFORE it execs the container runtime, so it survives
# the exec and performs a lightweight, read-only readiness observation:
#   STARTING  -> written immediately (process/activation identity captured)
#   READY     -> first /health 200 AND expected model id served by /v1/models
#   STALLED   -> never became ready within the time budget (terminal evidence)
#
# It is deliberately NOT part of systemd supervision: it only grounds truth
# for monitoring/dependent services. An expensive probe can therefore never
# cause a restart loop. It shares the unit's control group, so systemd kills
# it (KillMode=control-group) when the activation ends.
set -eu

READINESS_RECORD="${READINESS_RECORD:-/var/lib/aihost/evidence/vllm_readiness.json}"
BOOT_ID_FILE="/proc/sys/kernel/random/boot_id"
HOST="${VLLM_HOST:-127.0.0.1}"
[ "$HOST" = "0.0.0.0" ] && HOST="127.0.0.1"
PORT="${VLLM_PORT:-8000}"
ENDPOINT="http://$HOST:$PORT"
EXPECTED_MODEL="${VLLM_XPU_EXPECTED_MODEL:-}"
API_KEY="${VLLM_API_KEY:-}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
POLL_SECS="${VLLM_READINESS_POLL_SECS:-10}"
TIMEOUT_SECS="${VLLM_READINESS_TIMEOUT_SECS:-1200}"
PROCESS_STARTED_AT="${1:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

boot_id="unknown"
if [ -r "$BOOT_ID_FILE" ]; then
    boot_id="$(cat "$BOOT_ID_FILE")"
fi
invocation_id="${INVOCATION_ID:-unknown}"

log() {
    printf '%s vllm-readiness-probe: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

write_record() {
    state="$1"; health_at="$2"; model_at="$3"; observed="$4"; note="${5:-}"
    health_json="null"
    [ "$health_at" != "null" ] && health_json="\"$health_at\""
    model_json="null"
    [ "$model_at" != "null" ] && model_json="\"$model_at\""
    {
        printf '{\n'
        printf '  "schema_version": "1.0.0",\n'
        printf '  "service": "vllm_xpu",\n'
        printf '  "readiness_state": "%s",\n' "$state"
        printf '  "process_started_at": "%s",\n' "$PROCESS_STARTED_AT"
        printf '  "health_ready_at": %s,\n' "$health_json"
        printf '  "model_ready_at": %s,\n' "$model_json"
        printf '  "validation_ready_at": null,\n'
        printf '  "startup_duration": %s,\n' "$(startup_duration_seconds)"
        printf '  "model_identity": {"expected": "%s", "observed": "%s"},\n' "$EXPECTED_MODEL" "$observed"
        printf '  "tensor_parallel_size": {"expected": %s, "observed": %s},\n' "$TENSOR_PARALLEL_SIZE" "$TENSOR_PARALLEL_SIZE"
        printf '  "boot_id": "%s",\n' "$boot_id"
        printf '  "service_invocation_id": "%s",\n' "$invocation_id"
        printf '  "endpoint": "%s",\n' "$ENDPOINT"
        printf '  "probe_note": "%s"\n' "$note"
        printf '}\n'
    } > "$READINESS_RECORD" 2>/dev/null || true
}

startup_duration_seconds() {
    if [ "$PROCESS_STARTED_AT" = "-" ]; then
        printf 'null'
        return
    fi
    start_epoch="$(date -u -d "$PROCESS_STARTED_AT" +%s 2>/dev/null || true)"
    now_epoch="$(date -u +%s 2>/dev/null || true)"
    if [ -z "$start_epoch" ] || [ -z "$now_epoch" ]; then
        printf 'null'
        return
    fi
    printf '%s' "$((now_epoch - start_epoch))"
}

http_code() {
    url="$1"
    if [ -n "$API_KEY" ]; then
        curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Authorization: Bearer $API_KEY" "$url" 2>/dev/null || printf '000'
    else
        curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || printf '000'
    fi
}

models_json() {
    if [ -n "$API_KEY" ]; then
        curl -s --max-time 5 -H "Authorization: Bearer $API_KEY" "$ENDPOINT/v1/models" 2>/dev/null || true
    else
        curl -s --max-time 5 "$ENDPOINT/v1/models" 2>/dev/null || true
    fi
}

first_model_id() {
    # The /v1/models response is single-line JSON: {"data":[{"id":"..."}]}
    # Anchor on the data array so the nested permission id ("modelperm-...") is not matched.
    models_json | sed -n 's/.*"data":[[:space:]]*\[[[:space:]]*{"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

expected_model_present() {
    [ -z "$EXPECTED_MODEL" ] && return 0
    models_json | grep -Fq "\"$EXPECTED_MODEL\""
}

log "observing readiness for $ENDPOINT (expected model '$EXPECTED_MODEL')"
write_record "STARTING" "null" "null" ""

deadline=$(( $(date -u +%s) + TIMEOUT_SECS ))
health_at="null"
model_at="null"
observed=""
ready=false

while [ "$(date -u +%s)" -lt "$deadline" ]; do
    code="$(http_code "$ENDPOINT/health")"
    if [ "$code" = "200" ]; then
        if [ "$health_at" = "null" ]; then
            health_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            write_record "STARTING" "$health_at" "null" ""
        fi
        if expected_model_present; then
            observed="$(first_model_id)"
            model_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            ready=true
            break
        fi
    fi
    sleep "$POLL_SECS"
done

if [ "$ready" = "true" ]; then
    log "ready: health=$health_at model=$model_at observed='$observed'"
    write_record "READY" "$health_at" "$model_at" "$observed" ""
    exit 0
fi

log "stalled: did not reach READY within ${TIMEOUT_SECS}s (health=$health_at)"
write_record "STALLED" "$health_at" "$model_at" "$observed" "timeout after ${TIMEOUT_SECS}s"
exit 1