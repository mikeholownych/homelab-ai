#!/usr/bin/env bash
# Window 3 / backlog 628: vllm-openai-xpu v0.29.0 feasibility on one B65 (GPU0), research server :18200, NOT via the gateway.
# Attempt A: cached Qwen2.5-7B-Instruct-AWQ (does the engine run on this hardware at all). Attempt B: our Qwen3-Coder-30B-A3B Q4_K_M GGUF
# (tokenizer files from the HF repo). Each attempt is time-boxed. Idle gate, worker1 outage, restore trap.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3; H=10.0.8.5; L=$O/vllm-xpu${ONLY:+-$ONLY}.log
IMG=docker.io/vllm/vllm-openai-xpu:v0.29.0
trap 'ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-vllm >/dev/null 2>&1" ; bash harness/restore_baseline.sh > '$O'/vllm-xpu-restore.log 2>&1; echo "RESTORED rc=$?" >> '$L EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
attempt() { # tag servedname timeout_s -- vllm args
  local tag=$1 served=$2 tmo=$3; shift 4
  echo "== $tag $(date -u +%FT%TZ)" >> $L
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-vllm >/dev/null 2>&1; sudo -n -u aihost-runtime podman run -d --log-driver k8s-file --name sycl-research-vllm --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all --group-add keep-groups -e ZE_AFFINITY_MASK=0 -e HF_HOME=/models -e HF_HUB_OFFLINE=1 -v /var/lib/local-ai/models:/models:ro -v /var/lib/aihost-runtime/research/qwen3-coder-tok:/tok:ro $IMG --host 127.0.0.1 --port 18200 --served-model-name $served $*" >> $L 2>&1
  local ok=0 t0=$(date +%s)
  while [ $(( $(date +%s)-t0 )) -lt $tmo ]; do
    ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:18200/health >/dev/null" && { ok=1; break; }
    ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman ps -q --filter name=sycl-research-vllm" | grep -q . || break
    sleep 10
  done
  echo "$tag healthy=$ok after_s=$(( $(date +%s)-t0 ))" >> $L
  [ $ok = 1 ] && ssh -o BatchMode=yes $H "python3 - 18200 $served" < harness/engine_probe_client.py >> $L 2>&1
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman logs --tail 80 sycl-research-vllm 2>&1" | sed 's/\x1b\[[0-9;]*m//g' > $O/vllm-xpu-$tag.logtail
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-vllm >/dev/null 2>&1"; sleep 10
}
[ "${ONLY:-}" = coder ] || attempt awq7b qwen25-7b-awq 900 -- --model Qwen/Qwen2.5-7B-Instruct-AWQ --quantization awq --max-model-len 8192 --gpu-memory-utilization 0.85
attempt coder-gguf coder30b-gguf 1500 -- --model /models/gguf/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf --tokenizer /tok --hf-config-path /tok --max-model-len 8192 --gpu-memory-utilization 0.9
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
