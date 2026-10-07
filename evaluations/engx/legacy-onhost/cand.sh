#!/bin/bash
# usage: cand.sh <gpu 0|1> <label> <model path under /var/lib/local-ai/models/gguf> [extra llama-server args...]
# Serves a candidate on its own GPU with the production worker image, flags and device setup, runs engx, tears down.
# Protocol comes from the environment (ENGX_CORPUS, ENGX_REPS, NOTHINK, ENGX_MAX_TOKENS, CTX). The GPU's production
# worker must be stopped first.
set -u
gpu=$1; label=$2; model=$3; shift 3
port=$((8002 + gpu)); name=llama-cand$gpu
IMG=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
# Run podman as the worker user from the units' WorkingDirectory: once a worker unit (PrivateTmp=true) has restarted, the
# user's rootless podman namespace has a private /tmp and /var/tmp, and conmon fails to resolve any cwd under them.
P() { sudo -n -u aihost-runtime env XDG_RUNTIME_DIR=/run/user/999 HOME=/var/lib/aihost-runtime \
        sh -c 'cd /var/lib/aihost-runtime && exec podman "$@"' podman "$@"; }
here=$(cd "$(dirname "$0")" && pwd)
# Server-side reasoning controls (the experimental variable), passed as properly quoted llama-server args.
#   SERVER_REASONING_BUDGET=N  -> --reasoning-budget N with a fixed end-of-budget instruction
#   SERVER_REASONING=on|off    -> --reasoning on|off (forces the template's thinking mode regardless of the client request)
export ENGX_REASONING_BUDGET_MESSAGE="Reasoning budget exhausted. Stop reasoning now and write the final answer in the required format."
reason_args=()
[ -n "${SERVER_REASONING_BUDGET:-}" ] && reason_args+=(--reasoning-budget "$SERVER_REASONING_BUDGET" --reasoning-budget-message "$ENGX_REASONING_BUDGET_MESSAGE")
[ -n "${SERVER_REASONING:-}" ] && reason_args+=(--reasoning "$SERVER_REASONING")
P rm -f $name >/dev/null 2>&1
P run -d --name $name --log-driver k8s-file --network host --ipc host --security-opt no-new-privileges \
  --device local-ai.intel/gpu=all --group-add keep-groups \
  -e ONEAPI_DEVICE_SELECTOR=level_zero:0,1 -e ZE_AFFINITY_MASK=$gpu -e SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS=1 \
  -v /dev/dri/by-path:/dev/dri/by-path:ro -v /var/lib/local-ai/models/gguf:/models:ro \
  $IMG -m /models/$model -c ${CTX:-65536} --host 127.0.0.1 --port $port --alias $label \
  -ngl 99 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics "${reason_args[@]}" "$@" >/dev/null || { echo "!! $label: podman run failed"; exit 1; }
ok=0
for i in $(seq 1 180); do
  curl -s -m 3 http://127.0.0.1:$port/health | grep -q ok && { ok=1; break; }
  P inspect -f "{{.State.Running}}" $name 2>/dev/null | grep -q true || { echo "!! $label: container exited during load"; break; }
  sleep 5
done
P logs $name > "$here/logs/server-$label.log" 2>&1
if [ $ok = 1 ]; then
  echo "== $(date -u +%FT%TZ) $label up on gpu$gpu reason_args=[${reason_args[*]}]"
  curl -s -m 10 http://127.0.0.1:$port/props > "$here/logs/props-$label.json"
  P inspect -f "{{.Config.Cmd}}" $name > "$here/logs/cmd-$label.txt" 2>&1
  (cd "$here" && python3 -I engx.py run $label http://127.0.0.1:$port - $label 3 ${ENGX_ONLY:-})
else
  echo "!! $label failed to become healthy (see logs/server-$label.log)"
fi
P logs $name > "$here/logs/server-$label.log" 2>&1
P rm -f $name >/dev/null 2>&1
echo "== $(date -u +%FT%TZ) $label done"
