#!/usr/bin/env bash
# One GPU0 outage: Coder-30B pp32768 on HEAD with XMX-ESIMD off plus one more toggle per run. Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2
trap 'bash harness/restore_baseline.sh > '$O'/t32k-restore.log 2>&1; echo RESTORED >> '$O'/t32k.log' EXIT
: > $O/t32k.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
H=localhost/sycl-research/llama:head-a956a852; CO=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
for extra in "GGML_SYCL_X=1" "GGML_SYCL_FA_DPAS=0" "GGML_SYCL_FA_ONEDNN=0" "GGML_SYCL_FA_ONEDNN=1" "GGML_SYCL_ENABLE_MKL_FA=0" "GGML_SYCL_MMID_SCHED=0" "GGML_SYCL_ENABLE_GRAPH=1" "GGML_SYCL_ENABLE_FUSION=0" "GGML_SYCL_ENABLE_OPT=0"; do
  r=$(EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0 $extra" harness/research_run.sh bench t 0 $H $CO -ngl 99 -fa 1 -b 4096 -ub 2048 -p 32768 -n 0 -r 3 -o jsonl 2>/dev/null | python3 -I -c "
import sys,json
for l in sys.stdin:
    d=json.loads(l); print(round(d['avg_ts'],1),round(d['stddev_ts'],1))")
  echo "ESIMD0 + $extra : $r" >> $O/t32k.log
done
