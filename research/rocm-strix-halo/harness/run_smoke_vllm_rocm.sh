#!/usr/bin/env bash
# vLLM ROCm smoke on the lab host. Usage: run_smoke_vllm_rocm.sh [probe|mid]
# Env: EVIDENCE_DIR (required), VLLM_IMAGE (digest-pinned), MAX_LEN (default 8192),
#      VLLM_EXTRA_ARGS (extra `vllm serve` flags), GPU_MEM_UTIL (default 0.5).
# Attention backend is forced to TRITON_ATTN (never FLASH_ATTN on gfx1151).
# No HSA_OVERRIDE_GFX_VERSION. Exit 0 pass / 1 fail.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=smoke_common.sh
source "$HERE/smoke_common.sh"

KIND="${1:-probe}"
PORT=8102
CONTAINER=rocm-bake-vllm
# Community gfx1151 image (kyuz0), tag latest == rocm10.0.0-torch2.11.0-vllm0.33.0.
# Userspace ROCm lives inside the image; the host ROCm 7.2.0 pin is untouched.
IMAGE="${VLLM_IMAGE:-docker.io/kyuz0/vllm-therock-gfx1151@sha256:f8a7433d662b37b200ca19996d4013288071341ad514e66de69ea4871cfa3966}"
MAX_LEN="${MAX_LEN:-8192}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.5}"

case "$KIND" in
  probe) MODEL_DIR="$PROBE_HF"; MODEL_ID="qwen3-4b-instruct-2507"; TOOL_PARSER=hermes ;;
  mid)   MODEL_DIR="$MID_HF";   MODEL_ID="qwen3-coder-30b-a3b-fp8"; TOOL_PARSER=qwen3_coder ;;
  *) echo "kind must be probe|mid" >&2; exit 64 ;;
esac

mkdir -p "$MODELS_ROOT/hub"
smoke_init vllm "$KIND"
# shellcheck disable=SC2086
smoke_start_container \
  -v "$MODELS_ROOT:/models:ro" -v "$MODELS_ROOT/hub:/hub" \
  -e HF_HOME=/hub -e TRITON_CACHE_DIR=/hub/triton -e VLLM_ATTENTION_BACKEND=TRITON_ATTN \
  --ipc=host \
  "$IMAGE" \
  vllm serve "/models/$MODEL_DIR" --served-model-name "$MODEL_ID" \
  --host 127.0.0.1 --port "$PORT" --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" --attention-backend TRITON_ATTN \
  --enable-auto-tool-choice --tool-call-parser "$TOOL_PARSER" ${VLLM_EXTRA_ARGS:-}
smoke_finish
