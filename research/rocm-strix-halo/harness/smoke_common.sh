#!/usr/bin/env bash
# Shared helpers for run_smoke_*.sh (sourced, not executed). Runs ON the lab host.
#
# Per-engine scripts set: ENGINE, PORT, CONTAINER, IMAGE, OUT (evidence dir for
# this engine x model), MODEL_ID (served name), then call:
#   smoke_start_container <podman run args...>   # runs detached, logs captured
#   smoke_finish                                  # wait ready, chat+tools, status.json
# Status values written to $OUT/status.json: pass | fail | unavailable.
# Exit codes of the engine scripts: 0 pass, 1 fail, 2 unavailable.

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROMPTS_DIR="${PROMPTS_DIR:-$HARNESS_DIR/../prompts}"
MODELS_ROOT="${MODELS_ROOT:-/var/lib/local-ai/models}"
RUNTIME="${CONTAINER_RUNTIME:-podman}"

# Models by kind. Keep in sync with ../model-shortlist.md pins.
PROBE_GGUF="Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q8_0.gguf"
PROBE_HF="Qwen3-4B-Instruct-2507"
MID_GGUF="Qwen3-Coder-30B-A3B-Instruct-GGUF/Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf"
MID_HF="Qwen3-Coder-30B-A3B-Instruct-FP8"

# Devices + groups: rootless podman, host ROCm kernel driver, no HSA override.
GPU_ARGS=(--device=/dev/kfd --device=/dev/dri --group-add keep-groups --net=host)

smoke_init() { # ENGINE MODEL_KIND  (sets OUT, STARTED_AT)
  ENGINE="$1"; MODEL_KIND="${2:-probe}"
  : "${EVIDENCE_DIR:?set EVIDENCE_DIR to evidence/<ts>/smoke/<engine>}"
  OUT="$EVIDENCE_DIR/$MODEL_KIND"
  mkdir -p "$OUT"
  READY_TIMEOUT="${READY_TIMEOUT:-1200}"
  STATUS=fail; REASON="not finished"; READY_SECONDS=null; STARTED_AT="$(date -u +%FT%TZ)"
  trap smoke_cleanup EXIT
  "$HARNESS_DIR/stop_engine.sh" | tee -a "$OUT/stop_engine.log"
}

smoke_image_info() { # IMAGE -> $OUT/image.txt
  {
    echo "image_ref=$IMAGE"
    "$RUNTIME" image inspect "$IMAGE" --format 'image_id={{.Id}}
digest={{.Digest}}
repo_digests={{.RepoDigests}}
created={{.Created}}
size_bytes={{.Size}}' 2>&1
  } >"$OUT/image.txt"
}

smoke_start_container() { # podman run args after the common ones
  smoke_image_info
  printf '%q ' "$RUNTIME" run -d --name "$CONTAINER" "${GPU_ARGS[@]}" "$@" >"$OUT/run_cmd.txt"
  echo >>"$OUT/run_cmd.txt"
  if ! "$RUNTIME" run -d --name "$CONTAINER" "${GPU_ARGS[@]}" "$@" >"$OUT/container_id.txt" 2>"$OUT/run_error.txt"; then
    REASON="container failed to start: $(tr '\n' ' ' <"$OUT/run_error.txt" | cut -c1-300)"
    return 1
  fi
}

smoke_wait_ready() { # -> 0 ready, 1 not (REASON set)
  local t0 now
  t0="$(date +%s)"
  while :; do
    if ! "$RUNTIME" ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q .; then
      REASON="container exited before ready (exit $("$RUNTIME" inspect "$CONTAINER" --format '{{.State.ExitCode}}' 2>/dev/null))"
      return 1
    fi
    if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/v1/models" >"$OUT/models.json" 2>/dev/null; then
      now="$(date +%s)"; READY_SECONDS=$((now - t0)); return 0
    fi
    now="$(date +%s)"
    if (( now - t0 > READY_TIMEOUT )); then REASON="not ready after ${READY_TIMEOUT}s"; return 1; fi
    sleep 3
  done
}

smoke_mem_snapshot() { # label
  { echo "## $1 $(date -u +%FT%TZ)"; rocm-smi --showmeminfo gtt vram 2>&1 || true; } >>"$OUT/rocm_mem.txt"
}

smoke_finish() {
  smoke_mem_snapshot before-load
  if smoke_wait_ready; then
    smoke_mem_snapshot after-ready
    local base="http://127.0.0.1:${PORT}" chat_rc=0 tools_rc=0
    "$HARNESS_DIR/smoke_openai.sh" "$base" "$MODEL_ID" "$PROMPTS_DIR/smoke_chat.json" "$OUT/chat.json" || chat_rc=$?
    "$HARNESS_DIR/smoke_openai.sh" "$base" "$MODEL_ID" "$PROMPTS_DIR/smoke_tools.json" "$OUT/tools.json" || tools_rc=$?
    smoke_mem_snapshot after-requests
    if (( chat_rc == 0 )); then STATUS=pass; REASON="chat ok (tools_rc=$tools_rc)"; else REASON="chat request failed (rc=$chat_rc)"; fi
  fi
  smoke_write_status
  [[ "$STATUS" == pass ]]
}

smoke_write_status() {
  S_ENGINE="$ENGINE" S_KIND="$MODEL_KIND" S_MODEL="${MODEL_ID:-}" S_STATUS="$STATUS" \
  S_REASON="$REASON" S_IMAGE="${IMAGE:-}" S_PORT="${PORT:-0}" S_STARTED="$STARTED_AT" \
  S_READY="$READY_SECONDS" python3 - "$OUT" <<'PY'
import json, os, sys
out, env = sys.argv[1], os.environ
def load(name):
    p = os.path.join(out, name)
    return json.load(open(p)) if os.path.exists(p) else None
chat, tools = load("chat.json"), load("tools.json")
def text(r):
    try:
        return r["body"]["choices"][0]["message"].get("content")
    except Exception:
        return None
status = {
    "engine": env["S_ENGINE"], "model_kind": env["S_KIND"], "model_id": env["S_MODEL"],
    "status": env["S_STATUS"], "reason": env["S_REASON"], "image": env["S_IMAGE"],
    "port": int(env["S_PORT"]), "started_at": env["S_STARTED"],
    "ready_seconds": None if env["S_READY"] == "null" else int(env["S_READY"]),
    "chat_seconds": chat and chat["seconds"], "chat_content": chat and text(chat),
    "tools_seconds": tools and tools["seconds"],
    "tools_supported": tools and tools.get("tools_supported"),
}
with open(os.path.join(out, "status.json"), "w") as fh:
    json.dump(status, fh, indent=2)
    fh.write("\n")
PY
}

smoke_cleanup() {
  local rc=$?
  "$RUNTIME" logs "$CONTAINER" >"$OUT/container.log" 2>&1 || true
  "$RUNTIME" inspect "$CONTAINER" >"$OUT/container_inspect.json" 2>&1 || true
  [[ -f "$OUT/status.json" ]] || smoke_write_status
  "$HARNESS_DIR/stop_engine.sh" >>"$OUT/stop_engine.log" 2>&1
  echo "[$ENGINE/$MODEL_KIND] status=$STATUS reason=$REASON"
  trap - EXIT
  exit "$rc"
}
