#!/usr/bin/env bash
# Run a research container on ai-5820-01 as a transient systemd unit under aihost-runtime (same uid/hardening class as prod).
# Production unit files are never modified. Servers use ports 18100-18199 (outside the policed worker port sets).
#
#   research_run.sh bench  <tag> <gpu> <image> <model-relpath> [llama-bench args...]   -> JSONL on stdout, one-shot
#   research_run.sh server <tag> <gpu> <port>  <image> -- <llama-server args...>        -> starts sycl-research-<tag>.service
#   research_run.sh stop   <tag>
# Env: HOST (default 10.0.8.5), EXTRA_ENV (space-separated KEY=VAL passed to the container),
#      ENTRY (default /app/llama-bench or /app/llama-server), MODEL_DIR (default /var/lib/local-ai/models/gguf)
set -euo pipefail
HOST="${HOST:-10.0.8.5}"; MODE="$1"; TAG="$2"; shift 2
UNIT="sycl-research-$TAG"
case "$MODE" in
  stop) ssh -o BatchMode=yes "$HOST" "cd /; sudo -n systemctl stop $UNIT.service 2>&1 || true"; exit 0;;
esac
GPU="$1"; shift
if [ "$MODE" = server ]; then PORT="$1"; shift; fi
IMAGE="$1"; shift
if [ "$MODE" = bench ]; then MODEL="$1"; shift; fi
[ "${1:-}" = "--" ] && shift
ENVS="-e ONEAPI_DEVICE_SELECTOR=level_zero:0,1 -e ZE_AFFINITY_MASK=$GPU -e SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS=1"
for kv in ${EXTRA_ENV:-}; do ENVS="$ENVS -e $kv"; done
MODEL_DIR="${MODEL_DIR:-/var/lib/local-ai/models/gguf}"
COMMON="podman run --rm --name $UNIT --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all --group-add keep-groups $ENVS -v /dev/dri/by-path:/dev/dri/by-path:ro -v $MODEL_DIR:/models:ro ${EXTRA_MOUNTS:-}"
PROPS="-p User=aihost-runtime -p Group=aihost-runtime -p SupplementaryGroups=render\ video -p WorkingDirectory=/var/lib/aihost-runtime -p LimitMEMLOCK=infinity -p LimitNOFILE=65536 -p Delegate=yes -p ProtectControlGroups=no -p PrivateTmp=true"
if [ "$MODE" = bench ]; then
  CMD="$COMMON --entrypoint /app/llama $IMAGE ${SUBCMD:-bench} -m /models/$MODEL $*"
  ssh -o BatchMode=yes "$HOST" "cd /; sudo -n systemd-run --quiet --wait --pipe --collect --unit $UNIT $PROPS /usr/bin/$CMD"
else
  CMD="$COMMON $IMAGE --host 127.0.0.1 --port $PORT $*"
  ssh -o BatchMode=yes "$HOST" "cd /; sudo -n systemd-run --quiet --collect --unit $UNIT $PROPS -p StandardOutput=append:/var/log/local-ai/llama/$UNIT.log -p StandardError=append:/var/log/local-ai/llama/$UNIT.log /usr/bin/$CMD && echo started $UNIT"
fi
