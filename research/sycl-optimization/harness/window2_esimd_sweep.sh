#!/usr/bin/env bash
# One GPU0 outage: (1) where does the residual 32K gap enter, with XMX-ESIMD off? (2) Qwen3.6 on HEAD, ESIMD default vs off.
# Restores production on exit (trap), even on failure.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2
trap 'bash harness/restore_baseline.sh > '$O'/esimd-sweep-restore.log 2>&1; echo RESTORED >> '$O'/esimd-sweep.log' EXIT
: > $O/esimd-sweep.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
run(){ # tag image model env pp
  local tag=$1 img=$2 m=$3 env=$4 pp=$5
  EXTRA_ENV="$env" harness/research_run.sh bench sw 0 "$img" "$m" -ngl 99 -fa 1 -b 4096 -ub 2048 -p $pp -n 128 -r 3 -o jsonl > "$O/esimd-$tag.jsonl" 2>/dev/null
  echo "$tag $(python3 -I -c "
import json
print([round(json.loads(l)['avg_ts'],1) for l in open('$O/esimd-$tag.jsonl')])")" >> $O/esimd-sweep.log
}
CO=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf; Q36=qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
for t in 493253fe 39febd2a 2c93f0b6 18c5a95e; do
  run co-$t-esimd0 localhost/sycl-research/llama:bisect-$t $CO GGML_SYCL_ENABLE_XMX_ESIMD=0 32768
done
H=localhost/sycl-research/llama:head-a956a852
run q36-head-default $H $Q36 GGML_SYCL_X=1 512,2048,8192
run q36-head-esimd0 $H $Q36 GGML_SYCL_ENABLE_XMX_ESIMD=0 512,2048,8192
