#!/usr/bin/env bash
# llama.cpp HIP (ROCm) smoke on the lab host. Usage: run_smoke_llamacpp_hip.sh [probe|mid]
# Env: EVIDENCE_DIR (required), LLAMA_HIP_IMAGE (digest-pinned), CTX (default 8192).
# No HSA_OVERRIDE_GFX_VERSION: gfx1151 is native. Exit 0 pass / 1 fail.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=smoke_common.sh
source "$HERE/smoke_common.sh"

KIND="${1:-probe}"
PORT=8101
CONTAINER=rocm-bake-llamacpp
# Official ggml-org ROCm server image; multi-arch index digest of tag server-rocm
# (created 2026-11-17), pulled 2026-11-21.
IMAGE="${LLAMA_HIP_IMAGE:-ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184}"
CTX="${CTX:-8192}"

case "$KIND" in
  probe) MODEL_FILE="$PROBE_GGUF"; MODEL_ID="qwen3-4b-instruct-2507-q8_0" ;;
  mid)   MODEL_FILE="$MID_GGUF";   MODEL_ID="qwen3-coder-30b-a3b-q8_0" ;;
  *) echo "kind must be probe|mid" >&2; exit 64 ;;
esac

smoke_init llamacpp "$KIND"
# --jinja is required for OpenAI tool_calls with GGUF chat templates.
smoke_start_container \
  -v "$MODELS_ROOT:/models:ro" \
  "$IMAGE" \
  -m "/models/$MODEL_FILE" --alias "$MODEL_ID" -ngl 99 -fa on --jinja \
  --host 127.0.0.1 --port "$PORT" -c "$CTX" -np 1
smoke_finish
