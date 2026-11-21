#!/usr/bin/env bash
# SGLang ROCm smoke on the lab host. Usage: run_smoke_sglang_rocm.sh [probe|mid]
# Env: EVIDENCE_DIR (required), SGLANG_IMAGE (digest-pinned), CTX (default 8192),
#      EXTRA_PODMAN_ARGS (e.g. "-e SGLANG_USE_AITER=0"), MEM_FRAC (default 0.3), MAX_TOKENS (KV tokens, default 32768), SGLANG_EXTRA_ARGS.
# SGLang sizes its pool from ~115 GB (RAM+GTT) it sees on the APU, so an explicit
# --mem-fraction-static/--max-total-tokens is needed to stay inside the 61.35 GiB GTT pool.
# If the engine cannot run on gfx1151 / ROCm 7.2: writes UNAVAILABLE.md (commands +
# logs) and status "unavailable" (exit 2). Never reports fabricated throughput.
# No HSA_OVERRIDE_GFX_VERSION; host ROCm is not upgraded. Exit 0 pass / 1 fail / 2 unavailable.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=smoke_common.sh
source "$HERE/smoke_common.sh"

KIND="${1:-probe}"
PORT=8103
CONTAINER=rocm-bake-sglang
# lmsysorg publishes ROCm 7.2 images only for MI30x/MI35x (gfx942/gfx950); no gfx1151
# tag exists. We still try the rocm720 image to measure whether it starts.
IMAGE="${SGLANG_IMAGE:-docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170}"  # tag v0.5.23-rocm720-mi30x
CTX="${CTX:-8192}"
MEM_FRAC="${MEM_FRAC:-0.3}"
MAX_TOKENS="${MAX_TOKENS:-32768}"

case "$KIND" in
  probe) MODEL_DIR="$PROBE_HF"; MODEL_ID="qwen3-4b-instruct-2507"; TOOL_PARSER=qwen25 ;;
  mid)   MODEL_DIR="$MID_HF";   MODEL_ID="qwen3-coder-30b-a3b-fp8"; TOOL_PARSER=qwen3_coder ;;
  *) echo "kind must be probe|mid" >&2; exit 64 ;;
esac

mkdir -p "$MODELS_ROOT/hub"
smoke_init sglang "$KIND"
rc=0
# shellcheck disable=SC2086
smoke_start_container \
  -v "$MODELS_ROOT:/models:ro" -v "$MODELS_ROOT/hub:/hub" \
  -e HF_HOME=/hub -e TRITON_CACHE_DIR=/hub/triton \
  --ipc=host ${EXTRA_PODMAN_ARGS:-} \
  "$IMAGE" \
  python3 -m sglang.launch_server --model-path "/models/$MODEL_DIR" \
  --served-model-name "$MODEL_ID" --host 127.0.0.1 --port "$PORT" \
  --context-length "$CTX" --attention-backend triton --tool-call-parser "$TOOL_PARSER" \
  --mem-fraction-static "$MEM_FRAC" --max-total-tokens "$MAX_TOKENS" ${SGLANG_EXTRA_ARGS:-} \
  || rc=$?
if (( rc == 0 )); then smoke_finish || rc=$?; fi

if (( rc != 0 )); then
  # Never became ready => engine unavailable here; ready but request failed => plain fail.
  if [[ "$READY_SECONDS" == null ]]; then STATUS=unavailable; else STATUS=fail; fi
  "$RUNTIME" logs "$CONTAINER" >"$OUT/container.log" 2>&1 || true
  {
    echo "# SGLang UNAVAILABLE on gfx1151 / ROCm 7.2.0 ($KIND)"
    echo
    echo "- status: unavailable (not a zero-throughput result; no metrics exist)"
    echo "- image: \`$IMAGE\`"
    echo "- reason: ${REASON}"
    echo "- command: see run_cmd.txt; image details: image.txt"
    echo
    echo '## Last 60 log lines'
    echo '```'
    tail -n 60 "$OUT/container.log" 2>/dev/null || true
    echo '```'
  } >"$OUT/UNAVAILABLE.md"
  smoke_write_status
  [[ "$STATUS" == unavailable ]] && exit 2
  exit 1
fi
