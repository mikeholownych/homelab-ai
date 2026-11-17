#!/usr/bin/env bash
# Follow-up to the MoE engine comparison: (1) vLLM XPU and SGLang XPU at 8/16/32 concurrent streams, (2) the append-only agent pattern (prefix cache per step) on
# llama.cpp (one card, -np 1), vLLM and SGLang (FP8, TP=2). Same shape as window3_moe_full.sh: both production workers stopped after an idle check, watchdog and
# reconcile paused, EXIT trap restores both workers and restarts the watchdog.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3/engine-scale; H=10.0.8.5; mkdir -p $O; L=$O/engine-scale.log
VLLM=docker.io/vllm/vllm-openai-xpu:v0.29.0; SGL=docker.io/lmsysorg/sglang:v0.5.23-xpu
SYCL=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
FP8=/models/gguf/hf-qwen3-coder-30b-fp8
cleanup() {
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1; true"
  harness/research_run.sh stop moe >/dev/null 2>&1
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
wait_health() { local port=$1 tmo=$2 t0=$(date +%s); while [ $(( $(date +%s)-t0 )) -lt $tmo ]; do ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:$port/health >/dev/null" && { echo $(( $(date +%s)-t0 )); return 0; }; sleep 10; done; echo FAIL; return 1; }
echo "== llamacpp $(date -u +%FT%TZ)" >> $L
EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh server moe 0 18100 $SYCL -- -m /models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf -c 32768 --jinja -np 1 -fa on -b 4096 -ub 2048 --lazy-mode on -ngl 99 >/dev/null
r=$(wait_health 18100 900); echo "llamacpp ready_s=$r" >> $L
[ "$r" != FAIL ] && { echo "-- llamacpp prefix" >> $L; ssh -o BatchMode=yes $H "python3 - 18100 coder" < harness/engine_prefix_client.py >> $L 2>&1; }
harness/research_run.sh stop moe >/dev/null 2>&1; sleep 20
run_engine() { # tag img -- args
  local tag=$1 img=$2; shift 3
  echo "== $tag $(date -u +%FT%TZ)" >> $L
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1; sudo -n -u aihost-runtime podman run -d --log-driver k8s-file --name sycl-research-moe --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all --group-add keep-groups -e HF_HOME=/models -e HF_HUB_OFFLINE=1 -v /var/lib/local-ai/models:/models:ro $img $*" >> $L 2>&1
  r=$(wait_health 18200 1800); echo "$tag ready_s=$r" >> $L
  if [ "$r" != FAIL ]; then
    echo "-- $tag batch" >> $L; ssh -o BatchMode=yes $H "python3 - batch 18200 coderfp8 8 16 32" < harness/engine_sweep_client.py >> $L 2>&1
    echo "-- $tag prefix" >> $L; ssh -o BatchMode=yes $H "python3 - 18200 coderfp8" < harness/engine_prefix_client.py >> $L 2>&1
  fi
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman logs --tail 40 sycl-research-moe 2>&1" | sed 's/\x1b\[[0-9;]*m//g' > $O/$tag.logtail
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1"; sleep 20
}
run_engine vllm-fp8-tp2 $VLLM -- --host 127.0.0.1 --port 18200 --served-model-name coderfp8 --model $FP8 --tensor-parallel-size 2 --max-model-len 32768 --gpu-memory-utilization 0.9
run_engine sglang-fp8-tp2 $SGL -- python3 -m sglang.launch_server --host 127.0.0.1 --port 18200 --served-model-name coderfp8 --model-path $FP8 --tp-size 2 --device xpu --attention-backend intel_xpu --context-length 32768 --mem-fraction-static 0.8
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
