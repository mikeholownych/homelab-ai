#!/usr/bin/env bash
# Backlog 628/633 second attempt: serve the MoE model Qwen3-Coder-30B-A3B (official FP8 checkpoint, 31 GB) with tensor parallelism across BOTH B65s,
# on vLLM XPU 0.29.0 and SGLang XPU 0.5.23. The earlier single-GPU AWQ attempts failed in the engines' MoE kernels; FP8 is the format both engines
# document for MoE on XPU, and TP=2 leaves about 15.5 GB of weights per card. Research servers on :18200 (NOT via the gateway).
# Needs BOTH production workers stopped: idle gate first, the watchdog service is stopped for the window (a deliberate stop is not a stall, but it
# must not race a restart), reconcile paused; the EXIT trap removes the containers, restarts the watchdog and runs restore_baseline.sh (2/2 workers).
set -u; cd "$(dirname "$0")/.."; O=evidence/window3/moe-tp2; H=10.0.8.5; mkdir -p $O; L=$O/moe-tp2.log
VLLM=docker.io/vllm/vllm-openai-xpu:v0.29.0; SGL=docker.io/lmsysorg/sglang:v0.5.23-xpu
MODEL=/models/gguf/hf-qwen3-coder-30b-fp8
cleanup() {
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1; true"
  bash harness/restore_baseline.sh > $O/restore.log 2>&1; echo "RESTORED rc=$?" >> $L
  systemctl --user start aihost-worker-watchdog.service; echo "watchdog: $(systemctl --user is-active aihost-worker-watchdog.service)" >> $L
}
trap cleanup EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
systemctl --user stop aihost-worker-watchdog.service
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service aihost-llama-worker2.service'
sleep 30
attempt() { # tag served timeout_s image -- engine args
  local tag=$1 served=$2 tmo=$3 img=$4; shift 5
  echo "== $tag $(date -u +%FT%TZ)" >> $L
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1; sudo -n -u aihost-runtime podman run -d --log-driver k8s-file --name sycl-research-moe --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all --group-add keep-groups -e HF_HOME=/models -e HF_HUB_OFFLINE=1 -v /var/lib/local-ai/models:/models:ro $img $*" >> $L 2>&1
  local ok=0 t0=$(date +%s)
  while [ $(( $(date +%s)-t0 )) -lt $tmo ]; do
    ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:18200/health >/dev/null" && { ok=1; break; }
    ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman ps -q --filter name=sycl-research-moe" | grep -q . || break
    sleep 10
  done
  echo "$tag healthy=$ok after_s=$(( $(date +%s)-t0 ))" >> $L
  [ $ok = 1 ] && ssh -o BatchMode=yes $H "python3 - 18200 $served" < harness/engine_probe_client.py >> $L 2>&1
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman logs --tail 120 sycl-research-moe 2>&1" | sed 's/\x1b\[[0-9;]*m//g' > $O/$tag.logtail
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1"; sleep 15
}
attempt vllm-fp8-tp2 coderfp8 1800 $VLLM -- --host 127.0.0.1 --port 18200 --served-model-name coderfp8 --model $MODEL --tensor-parallel-size 2 --max-model-len 8192 --gpu-memory-utilization 0.9
attempt sglang-fp8-tp2 coderfp8 1800 $SGL -- python3 -m sglang.launch_server --host 127.0.0.1 --port 18200 --served-model-name coderfp8 --model-path $MODEL --tp-size 2 --device xpu --attention-backend intel_xpu --context-length 8192 --mem-fraction-static 0.8
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
