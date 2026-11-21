#!/usr/bin/env bash
# Phase 2c deep bake-off on the lab host (rootless podman, one engine on the APU at a time).
#
# Usage: run_deep_bakeoff.sh ENGINE MODEL      one pair; ENGINE = llamacpp|vllm
#        run_deep_bakeoff.sh all "ENGINE:MODEL ..."   sequential pairs (each in its own process)
# MODEL keys: coder30b (Qwen3-Coder-30B-A3B), q36_35b (Qwen3.6-35B-A3B)
# Env: EVIDENCE_DIR (required, evidence/<ts>), LLAMA_HIP_IMAGE / VLLM_IMAGE (default: digests
#      pinned in run_smoke_*.sh), GPU_MEM_UTIL (vLLM override).
# SGLang is intentionally absent: it was UNAVAILABLE in smoke (no fake deep scores).
# No HSA_OVERRIDE_GFX_VERSION (gfx1151 native); vLLM forced to TRITON_ATTN.
#
# Per pair (output: $EVIDENCE_DIR/deep/<engine>/<model>/metrics.jsonl):
#   stop_engine -> start pinned image -> warmup (kernels JIT, results discarded)
#   -> cold TTFT (engine_sweep_client longctx 2048 8192, unique prefix)
#   -> batch c=1,2,4 (engine_sweep_client batch)
#   -> warm TTFT (fixed ~2k prefix twice, 2nd recorded; deep_probe.py warm)
#   -> quality (tool-call contract probes; deep_probe.py quality)
#   -> ops checklist JSON
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == all ]]; then
  : "${EVIDENCE_DIR:?set EVIDENCE_DIR to evidence/<ts>}"
  rc=0
  for pair in ${2:?pairs like "llamacpp:coder30b vllm:coder30b"}; do
    "$0" "${pair%%:*}" "${pair##*:}" || rc=$?
  done
  exit "$rc"
fi

# shellcheck source=smoke_common.sh
source "$HERE/smoke_common.sh"
set +e  # measurement steps record failures as data instead of aborting the pair

ENGINE_NAME="${1:?engine llamacpp|vllm}"; MODEL_KEY="${2:?model coder30b|q36_35b}"
: "${EVIDENCE_DIR:?set EVIDENCE_DIR to evidence/<ts>}"
CLIENT="${SWEEP_CLIENT:-$HERE/../../sycl-optimization/harness/engine_sweep_client.py}"
CTX_TOKENS="${CTX_TOKENS:-16384}"   # per-request context: covers the 8192-token cold prefill

case "$ENGINE_NAME" in
  llamacpp)
    PORT=8101; CONTAINER=rocm-bake-llamacpp
    IMAGE="${LLAMA_HIP_IMAGE:-ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184}"
    case "$MODEL_KEY" in
      coder30b) MODEL_FILE="$MID_GGUF"; MODEL_ID="qwen3-coder-30b-a3b-q8_0" ;;
      q36_35b)  MODEL_FILE="Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q6_K.gguf"; MODEL_ID="qwen3.6-35b-a3b-ud-q6_k" ;;
      *) echo "unknown model $MODEL_KEY" >&2; exit 64 ;;
    esac
    START_ARGS=(-v "$MODELS_ROOT:/models:ro" "$IMAGE"
      -m "/models/$MODEL_FILE" --alias "$MODEL_ID" -ngl 99 -fa on --jinja
      --host 127.0.0.1 --port "$PORT" -c $((CTX_TOKENS * 4)) -np 4)  # 4 slots x CTX_TOKENS for c=4
    ;;
  vllm)
    PORT=8102; CONTAINER=rocm-bake-vllm
    IMAGE="${VLLM_IMAGE:-docker.io/kyuz0/vllm-therock-gfx1151@sha256:f8a7433d662b37b200ca19996d4013288071341ad514e66de69ea4871cfa3966}"
    case "$MODEL_KEY" in
      coder30b) MODEL_DIR="$MID_HF"; MODEL_ID="qwen3-coder-30b-a3b-fp8"; PARSER=qwen3_coder; UTIL=0.7; EXTRA=() ;;
      # No --reasoning-parser: with it vLLM streams thinking under a "reasoning" delta key that
      # engine_sweep_client.py does not read, so TTFT came back null (attempt1 evidence).
      q36_35b)  MODEL_DIR="Qwen3.6-35B-A3B-FP8"; MODEL_ID="qwen3.6-35b-a3b-fp8"; PARSER=qwen3_coder; UTIL=0.8
                EXTRA=() ;;
      *) echo "unknown model $MODEL_KEY" >&2; exit 64 ;;
    esac
    mkdir -p "$MODELS_ROOT/hub"
    START_ARGS=(-v "$MODELS_ROOT:/models:ro" -v "$MODELS_ROOT/hub:/hub"
      -e HF_HOME=/hub -e TRITON_CACHE_DIR=/hub/triton -e VLLM_ATTENTION_BACKEND=TRITON_ATTN --ipc=host "$IMAGE"
      vllm serve "/models/$MODEL_DIR" --served-model-name "$MODEL_ID"
      --host 127.0.0.1 --port "$PORT" --max-model-len "$CTX_TOKENS"
      --gpu-memory-utilization "${GPU_MEM_UTIL:-$UTIL}" --attention-backend TRITON_ATTN --enable-prefix-caching
      --enable-auto-tool-choice --tool-call-parser "$PARSER" "${EXTRA[@]}")
    ;;
  *) echo "unknown engine $ENGINE_NAME (sglang is skipped: UNAVAILABLE in smoke)" >&2; exit 64 ;;
esac

EVIDENCE_DIR="$EVIDENCE_DIR/deep/$ENGINE_NAME"
smoke_init "$ENGINE_NAME" "$MODEL_KEY"   # sets OUT=$EVIDENCE_DIR/$MODEL_KEY, stops any engine
METRICS="$OUT/metrics.jsonl"; : >"$METRICS"
emit() { python3 -c 'import json,sys; print(json.dumps({"kind": sys.argv[1], **json.loads(sys.stdin.readline() or "{}")}))' "$1" >>"$METRICS"; }
# JSON line -> metrics row; the tag is the default kind (a row's own "kind" wins, e.g. quality/warm_ttft)
tag() { while IFS= read -r l; do [[ "$l" == \{* ]] && echo "$l" | emit "$1"; done; }
step() { local name="$1"; shift; echo "[$ENGINE_NAME/$MODEL_KEY] $name"; timeout "${STEP_TIMEOUT:-2400}" "$@" 2>>"$OUT/$name.err"; }

smoke_start_container "${START_ARGS[@]}" || { smoke_write_status; echo '{"status":"fail"}' | emit run; exit 1; }
smoke_mem_snapshot before-load
if ! smoke_wait_ready; then
  echo "{\"status\":\"fail\",\"reason\":\"$REASON\"}" | emit run
  exit 1   # EXIT trap saves logs + status.json
fi
smoke_mem_snapshot after-ready

# 2. Warmup: JIT kernels at the shapes measured below; output discarded.
step warmup python3 "$CLIENT" longctx "$PORT" "$MODEL_ID" 512 2048 8192 >"$OUT/warmup.jsonl"

# 3. Cold TTFT (unique prefix per request => no prefix-cache hit)
step cold python3 "$CLIENT" longctx "$PORT" "$MODEL_ID" 2048 8192 | tee "$OUT/cold.jsonl" | tag cold_ttft

# 4. Batch decode throughput (aggregate tok/s, c=1/2/4)
step batch python3 "$CLIENT" batch "$PORT" "$MODEL_ID" 1 2 4 | tee "$OUT/batch.jsonl" | tag batch
smoke_mem_snapshot after-batch

# 5. Warm-prefix TTFT
step warm python3 "$HARNESS_DIR/deep_probe.py" warm "$PORT" "$MODEL_ID" | tee "$OUT/warm.jsonl" | tag warm_ttft

# 6. Quality: tool-call contract probes
step quality python3 "$HARNESS_DIR/deep_probe.py" quality "$PORT" "$MODEL_ID" | tee "$OUT/quality.jsonl" | tag quality
smoke_mem_snapshot after-quality

# 7. Ops checklist (facts gathered from this run's own evidence)
"$RUNTIME" logs "$CONTAINER" >"$OUT/container.log" 2>&1
RUNNING=0; "$RUNTIME" ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q . && RUNNING=1
python3 - "$OUT" "$METRICS" "$IMAGE" "$READY_SECONDS" "$RUNNING" >"$OUT/ops.json" <<'PY'
import json, re, sys
out, metrics, image, ready, running = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5] == "1"
rows = [json.loads(l) for l in open(metrics) if l.strip()]
kinds = lambda k: [r for r in rows if r["kind"] == k]
log = open(f"{out}/container.log", errors="replace").read()
cmd = open(f"{out}/run_cmd.txt").read()
mem = open(f"{out}/rocm_mem.txt").read()
gtt_total = int(re.findall(r"GTT Total Memory \(B\): (\d+)", mem)[0])
gtt_used = max(int(x) for x in re.findall(r"GTT Total Used Memory \(B\): (\d+)", mem))
warm = (kinds("warm_ttft") or [{}])[0]
checks = {
    "ready_within_300s": ready <= 300,
    "tool_calls_supported": any(r.get("tool_calls") for r in kinds("quality")),
    "stream_usage_reported": bool(kinds("batch")) and all(r.get("completion_tokens") for r in kinds("batch")),
    "prefix_cache_effective": bool(warm.get("cached_tokens")) or (warm.get("speedup") or 0) >= 1.5,
    "stable_no_oom_or_crash": running and not re.search(r"out of memory|segmentation fault|core dumped|Killed", log, re.I),
    "gtt_headroom_ge_8GiB": gtt_total - gtt_used >= 8 * 2**30,
    "digest_pinned_no_hsa_override": "@sha256:" in image and "HSA_OVERRIDE" not in cmd,
}
print(json.dumps({"checklist": checks, "items_pass": sum(checks.values()), "items_total": len(checks),
                  "ready_seconds": ready, "gtt_used_peak_gib": round(gtt_used / 2**30, 2),
                  "gtt_total_gib": round(gtt_total / 2**30, 2)}, indent=2))
PY
python3 -c 'import json,sys; print(json.dumps({"kind":"ops", **json.load(open(sys.argv[1]))}))' "$OUT/ops.json" >>"$METRICS"

# shellcheck disable=SC2034  # STATUS/REASON are read by smoke_write_status (sourced)
STATUS=pass; REASON="deep measurements recorded"
smoke_write_status
