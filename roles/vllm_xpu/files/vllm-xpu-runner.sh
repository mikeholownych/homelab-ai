#!/bin/sh
# vLLM XPU service launcher. Installed by the vllm_xpu role; executed by
# systemd. Runs the pinned container image (digest-pinned, never a mutable
# tag) with the rendered configuration, GPU devices, and model cache.
#
# All inputs come from files rendered by Ansible under /etc/local-ai/vllm/.
# No shell interpolation of runtime data: every argument is fixed or argv.
set -eu

VLLM_CONFIG_DIR="/etc/local-ai/vllm"
IMAGE_REF_FILE="${VLLM_IMAGE_REF_FILE:-$VLLM_CONFIG_DIR/image-ref}"
CONFIG_FILE="${VLLM_CONFIG_FILE:-$VLLM_CONFIG_DIR/vllm-config.yaml}"
ENV_FILE="${VLLM_ENV_FILE:-$VLLM_CONFIG_DIR/vllm.env}"
MODEL_CACHE="${VLLM_MODEL_CACHE:-/var/lib/local-ai/models}"
CDI_DEVICE="${CDI_DEVICE:-local-ai.intel/gpu=all}"
BOOT_ID_FILE="/proc/sys/kernel/random/boot_id"
RECOVERY_RECORD="${RECOVERY_RECORD:-/var/lib/aihost/evidence/vllm_recovery.json}"
READINESS_RECORD="${READINESS_RECORD:-/var/lib/aihost/evidence/vllm_readiness.json}"
READINESS_PROBE="${READINESS_PROBE:-/usr/local/libexec/local-ai-vllm-readiness}"
# Captured at launch: readiness evidence anchors process_started_at here.
PROCESS_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Authoritative restart source: systemd tracks on-failure auto-restarts for the
# unit via its NRestarts property. This is the restart count for the CURRENT
# service lifecycle; it resets on an intentional stop/start (verified
# empirically). It is not a durable historical recovery-event counter.
SYSTEMD_UNIT="${VLLM_SYSTEMD_UNIT:-vllm.service}"

# Authoritative restart count for the current service lifecycle. Never returns a
# fabricated 0: failures are surfaced as an explicit "unavailable" marker.
read_restart_count() {
    restart_count="null"
    restart_count_source="unavailable"
    restart_count_obtained_at="null"
    if ! command -v systemctl >/dev/null 2>&1; then
        return 0
    fi
    nr="$(systemctl show "$SYSTEMD_UNIT" -p NRestarts --value 2>/dev/null || true)"
    case "$nr" in
        ''|*[!0-9]*) : ;;
        *)
            restart_count="$nr"
            restart_count_source="systemd:NRestarts"
            restart_count_obtained_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            ;;
    esac
}

log() {
    printf '%s vllm-xpu-runner: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

# Record a bounded recovery/startup event. Never overwrites without intent:
# each call replaces the previous record with the newest lifecycle event.
write_recovery_record() {
    stage="$1"; class="$2"; exit_code="$3"; terminal="${4:-false}"
    boot_id="unknown"
    if [ -r "$BOOT_ID_FILE" ]; then
        boot_id="$(cat "$BOOT_ID_FILE")"
    fi
    read_restart_count
    invocation_id="${INVOCATION_ID:-null}"
    record_dir="$(dirname "$RECOVERY_RECORD")"
    mkdir -p "$record_dir" 2>/dev/null || true
    # The record file is pre-created by the role owned by the service account,
    # so write-in-place works even though the evidence directory is not
    # writable by the service user (atomic tmp+rename would need dir write).
    {
        printf '{\n'
        printf '  "service": "vllm_xpu",\n'
        printf '  "event": "start",\n'
        printf '  "class": "%s",\n' "$class"
        printf '  "stage_reached": "%s",\n' "$stage"
        printf '  "exit_code": %s,\n' "$exit_code"
        printf '  "restart_count": %s,\n' "$restart_count"
        printf '  "restart_count_source": "%s",\n' "$restart_count_source"
        printf '  "restart_count_obtained_at": "%s",\n' "$restart_count_obtained_at"
        printf '  "service_invocation_id": "%s",\n' "$invocation_id"
        printf '  "terminal": %s,\n' "$terminal"
        printf '  "started_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '  "boot_id": "%s"\n' "$boot_id"
        printf '}\n'
    } > "$RECOVERY_RECORD" 2>/dev/null || true
}

for file in "$IMAGE_REF_FILE" "$CONFIG_FILE" "$ENV_FILE"; do
    if [ ! -f "$file" ]; then
        log "required input missing: $file"
        write_recovery_record "A:prerequisites_valid" "invalid_config" 78 true
        exit 78
    fi
done

IMAGE_REF="$(cat "$IMAGE_REF_FILE")"

if [ -n "${VLLM_RUNTIME_BIN:-}" ]; then
    RUNTIME_BIN="$VLLM_RUNTIME_BIN"
elif command -v docker >/dev/null 2>&1; then
    RUNTIME_BIN=docker
elif command -v podman >/dev/null 2>&1; then
    RUNTIME_BIN=podman
else
    log "no container runtime found (docker or podman required)"
    write_recovery_record "A:prerequisites_valid" "invalid_config" 78 true
    exit 78
fi

if ! echo "$IMAGE_REF" | grep -q '@sha256:[0-9a-f]\{64\}$'; then
    log "image ref is not digest-pinned: $IMAGE_REF"
    write_recovery_record "A:prerequisites_valid" "invalid_config" 78 true
    exit 78
fi

log "starting $IMAGE_REF"
write_recovery_record "A:prerequisites_valid" "normal_start" 0 false

# Export variables from ENV_FILE
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

export ONEAPI_DEVICE_SELECTOR="${ONEAPI_DEVICE_SELECTOR:-level_zero:0,1}"
export ZE_AFFINITY_MASK="${ZE_AFFINITY_MASK:-0,1}"
export CL_TARGET_OPENCL_DEVICE_ENTRY=1
export SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS=1
export OMP_PROC_BIND=true
export OMP_PLACES=cores

TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-2}"
CONTAINER_NAME="${VLLM_CONTAINER_NAME:-vllm-xpu}"

# Spawn the readiness observer before starting the container. The launcher stays
# as the systemd main process so it can reap the observer and stop it if the
# container exits. It is NOT in the systemd supervision path, so a slow/cold
# start can never cause a restart loop from a probe failure.
READINESS_PID=""
REAPING_READINESS=false
reap_readiness() {
    if [ "$REAPING_READINESS" = true ]; then
        return 0
    fi
    if [ -z "$READINESS_PID" ]; then
        return 0
    fi
    REAPING_READINESS=true
    trap - CHLD
    readiness_state="$(ps -o stat= -p "$READINESS_PID" 2>/dev/null | tr -d ' ' || true)"
    case "$readiness_state" in
        ''|Z*)
            wait "$READINESS_PID" 2>/dev/null || true
            READINESS_PID=""
            ;;
    esac
    REAPING_READINESS=false
    trap reap_readiness CHLD
    return 0
}
trap reap_readiness CHLD

CONTAINER_PID=""
cleanup() {
    status="$?"
    trap - EXIT INT TERM CHLD
    if [ -n "$CONTAINER_PID" ] && kill -0 "$CONTAINER_PID" 2>/dev/null; then
        kill "$CONTAINER_PID" 2>/dev/null || true
        wait "$CONTAINER_PID" 2>/dev/null || true
    fi
    if [ -n "$READINESS_PID" ]; then
        kill "$READINESS_PID" 2>/dev/null || true
        wait "$READINESS_PID" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

if [ -x "$READINESS_PROBE" ]; then
    export VLLM_XPU_EXPECTED_MODEL="${VLLM_XPU_EXPECTED_MODEL:-}"
    export VLLM_READINESS_POLL_SECS="${VLLM_READINESS_POLL_SECS:-10}"
    export VLLM_READINESS_TIMEOUT_SECS="${VLLM_READINESS_TIMEOUT_SECS:-1200}"
    # shellcheck disable=SC2086
    "$READINESS_PROBE" "$PROCESS_STARTED_AT" >/dev/null 2>&1 &
    READINESS_PID="$!"
fi

# Strip redundant 'serve' or 'serve --config <path>' from $@ if passed from systemd ExecStart
if [ "$#" -gt 0 ] && [ "$1" = "serve" ]; then
    shift
    if [ "$#" -gt 1 ] && [ "$1" = "--config" ]; then
        shift 2
    fi
fi

EXTRA_MOUNTS=""
if [ -d /dev/dri/by-path ]; then
    EXTRA_MOUNTS="-v /dev/dri/by-path:/dev/dri/by-path:ro"
fi

GROUP_FLAGS=""
if [ "$RUNTIME_BIN" = "podman" ]; then
    GROUP_FLAGS="--group-add keep-groups"
fi

# shellcheck disable=SC2086
"$RUNTIME_BIN" run \
    --rm \
    --name "$CONTAINER_NAME" \
    --network host \
    --ipc host \
    --security-opt no-new-privileges \
    --device "$CDI_DEVICE" \
    $GROUP_FLAGS \
    --env-file "$ENV_FILE" \
    -e ONEAPI_DEVICE_SELECTOR="$ONEAPI_DEVICE_SELECTOR" \
    -e ZE_AFFINITY_MASK="$ZE_AFFINITY_MASK" \
    -e CL_TARGET_OPENCL_DEVICE_ENTRY="$CL_TARGET_OPENCL_DEVICE_ENTRY" \
    -e SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS="$SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS" \
    -e OMP_PROC_BIND="$OMP_PROC_BIND" \
    -e OMP_PLACES="$OMP_PLACES" \
    $EXTRA_MOUNTS \
    -v "$CONFIG_FILE":/cfg/vllm-config.yaml:ro \
    -v "$MODEL_CACHE":/models:rw \
    --entrypoint vllm \
    "$IMAGE_REF" \
    serve --config /cfg/vllm-config.yaml --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" "$@" &
CONTAINER_PID="$!"
CONTAINER_STATUS=0
while :; do
    if wait "$CONTAINER_PID"; then
        CONTAINER_STATUS=0
        # A SIGCHLD trap may make wait return the readiness child's status.
        # Only finish when the container process itself has disappeared.
        if kill -0 "$CONTAINER_PID" 2>/dev/null; then
            continue
        fi
        break
    fi
    CONTAINER_STATUS="$?"
    # SIGCHLD from the readiness observer can interrupt wait(2). Retry while
    # the container is still alive so observer completion cannot stop serving.
    if kill -0 "$CONTAINER_PID" 2>/dev/null; then
        continue
    fi
    break
done
exit "$CONTAINER_STATUS"
