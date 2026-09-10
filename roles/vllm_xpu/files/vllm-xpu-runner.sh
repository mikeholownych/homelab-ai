#!/bin/sh
# vLLM XPU service launcher. Installed by the vllm_xpu role; executed by
# systemd. Runs the pinned container image (digest-pinned, never a mutable
# tag) with the rendered configuration, GPU devices, and model cache.
#
# All inputs come from files rendered by Ansible under /etc/local-ai/vllm/.
# No shell interpolation of runtime data: every argument is fixed or argv.
set -eu

VLLM_CONFIG_DIR="/etc/local-ai/vllm"
IMAGE_REF_FILE="$VLLM_CONFIG_DIR/image-ref"
CONFIG_FILE="$VLLM_CONFIG_DIR/vllm-config.yaml"
ENV_FILE="$VLLM_CONFIG_DIR/vllm.env"
MODEL_CACHE="/var/lib/local-ai/models"
CDI_DEVICE="${CDI_DEVICE:-local-ai.intel/gpu=all}"

log() {
    printf '%s vllm-xpu-runner: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

for file in "$IMAGE_REF_FILE" "$CONFIG_FILE" "$ENV_FILE"; do
    if [ ! -f "$file" ]; then
        log "required input missing: $file"
        exit 78
    fi
done

IMAGE_REF="$(cat "$IMAGE_REF_FILE")"

if command -v docker >/dev/null 2>&1; then
    RUNTIME_BIN=docker
elif command -v podman >/dev/null 2>&1; then
    RUNTIME_BIN=podman
else
    log "no container runtime found (docker or podman required)"
    exit 78
fi

if ! echo "$IMAGE_REF" | grep -q '@sha256:[0-9a-f]\{64\}$'; then
    log "image ref is not digest-pinned: $IMAGE_REF"
    exit 78
fi

log "starting $IMAGE_REF"

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
exec "$RUNTIME_BIN" run \
    --rm \
    --name vllm-xpu \
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
    serve --config /cfg/vllm-config.yaml --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" "$@"
