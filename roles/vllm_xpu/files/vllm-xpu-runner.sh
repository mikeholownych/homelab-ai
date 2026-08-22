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

exec "$RUNTIME_BIN" run \
    --rm \
    --name vllm-xpu \
    --network host \
    --security-opt no-new-privileges \
    --device "$CDI_DEVICE" \
    --env-file "$ENV_FILE" \
    -v "$CONFIG_FILE":/cfg/vllm-config.yaml:ro \
    -v "$MODEL_CACHE":/models:rw \
    "$IMAGE_REF" \
    serve --config /cfg/vllm-config.yaml
