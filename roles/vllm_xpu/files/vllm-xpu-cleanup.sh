#!/bin/sh
# Remove only the container owned by vllm.service after every activation.
# systemd owns the process cgroup; this is an idempotent runtime-level safety net
# for containers left behind by an abnormal launcher or runtime exit.
set -u

RUNTIME_BIN="${VLLM_RUNTIME_BIN:-podman}"
CONTAINER_NAME="${VLLM_CONTAINER_NAME:-vllm-xpu}"

if ! command -v "$RUNTIME_BIN" >/dev/null 2>&1; then
    exit 0
fi

"$RUNTIME_BIN" rm --force --ignore --time 30 "$CONTAINER_NAME" >/dev/null 2>&1 || true
exit 0
