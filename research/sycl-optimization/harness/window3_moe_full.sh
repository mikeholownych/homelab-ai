#!/usr/bin/env bash
# Items 628/633, the part the first TP=2 window did not cover: batched throughput, long-context prefill and an engx task-accuracy subset for the
# MoE Qwen3-Coder-30B-A3B on vLLM XPU (FP8, TP=2), SGLang XPU (FP8, TP=2) and, as the baseline in the SAME window, llama.cpp SYCL Q4_K_M on ONE card with
# -np 4 (so it can batch too). Research servers (NOT via the gateway). Both production workers are stopped for the whole window after an idle check, the
# watchdog service is paused, reconcile paused; the EXIT trap removes containers, restores both workers (restore_baseline.sh) and restarts the watchdog.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3/moe-full; H=10.0.8.5; mkdir -p $O; L=$O/moe-full.log
VLLM=docker.io/vllm/vllm-openai-xpu:v0.29.0; SGL=docker.io/lmsysorg/sglang:v0.5.23-xpu
SYCL=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
FP8=/models/gguf/hf-qwen3-coder-30b-fp8; ENGXTASKS=T01,T02,T03,T04,T05,T07
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
measure() { # tag port served levels longsizes
  local tag=$1 port=$2 served=$3 levels=$4 sizes=$5
  echo "-- $tag sweeps $(date -u +%T)" >> $L
  ssh -o BatchMode=yes $H "python3 - batch $port $served $levels" < harness/engine_sweep_client.py >> $L 2>&1
  ssh -o BatchMode=yes $H "python3 - longctx $port $served $sizes" < harness/engine_sweep_client.py >> $L 2>&1
}
engx() { # tag port served
  echo "-- $1 engx $(date -u +%T)" >> $L
  ssh -o BatchMode=yes $H "cd ~/sycl-research/engx && mkdir -p ~/sycl-research/evidence/engx-$1 && ENGX_CORPUS=base ENGX_REPS=1 ENGX_MAX_TOKENS=12288 ENGX_OUT=\$HOME/sycl-research/evidence/engx-$1 timeout 3000 python3 engx.py run $1 http://127.0.0.1:$2 - $3 3 $ENGXTASKS < /dev/null" > $O/engx-$1.txt 2>&1
  echo "engx $1: $(grep '^RESULT' $O/engx-$1.txt | cut -c1-260)" >> $L
}
wait_health() { local port=$1 tmo=$2 t0=$(date +%s); while [ $(( $(date +%s)-t0 )) -lt $tmo ]; do ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:$port/health >/dev/null" && { echo $(( $(date +%s)-t0 )); return 0; }; sleep 10; done; echo FAIL; return 1; }
# --- llama.cpp SYCL on GPU0, one card, -np 4
echo "== llamacpp $(date -u +%FT%TZ)" >> $L
EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh server moe 0 18100 $SYCL -- -m /models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf -c 65536 --jinja -np 4 -fa on -b 4096 -ub 2048 --lazy-mode on -ngl 99 >/dev/null
r=$(wait_health 18100 900); echo "llamacpp ready_s=$r" >> $L
if [ "$r" != FAIL ]; then measure llamacpp 18100 coder "1 2 4" "4000 12000"; engx llamacpp-np4 18100 coder; fi
harness/research_run.sh stop moe >/dev/null 2>&1; sleep 20
# --- vLLM and SGLang, FP8, TP=2
run_engine() { # tag img served -- args...
  local tag=$1 img=$2 served=$3; shift 4
  echo "== $tag $(date -u +%FT%TZ)" >> $L
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1; sudo -n -u aihost-runtime podman run -d --log-driver k8s-file --name sycl-research-moe --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all --group-add keep-groups -e HF_HOME=/models -e HF_HUB_OFFLINE=1 -v /var/lib/local-ai/models:/models:ro $img $*" >> $L 2>&1
  r=$(wait_health 18200 1800); echo "$tag ready_s=$r" >> $L
  if [ "$r" != FAIL ]; then measure $tag 18200 $served "1 2 4 8" "4000 12000 28000"; engx $tag 18200 $served; fi
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman logs --tail 60 sycl-research-moe 2>&1" | sed 's/\x1b\[[0-9;]*m//g' > $O/$tag.logtail
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman rm -f sycl-research-moe >/dev/null 2>&1"; sleep 20
}
run_engine vllm-fp8-tp2 $VLLM coderfp8 -- --host 127.0.0.1 --port 18200 --served-model-name coderfp8 --model $FP8 --tensor-parallel-size 2 --max-model-len 32768 --gpu-memory-utilization 0.9
run_engine sglang-fp8-tp2 $SGL coderfp8 -- python3 -m sglang.launch_server --host 127.0.0.1 --port 18200 --served-model-name coderfp8 --model-path $FP8 --tp-size 2 --device xpu --attention-backend intel_xpu --context-length 32768 --mem-fraction-static 0.8
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
