#!/usr/bin/env bash
# One GPU0 outage: Coder-30B pp32768 isolating #30156 (18c5a95e) switches. ESIMD=0 throughout. Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2
trap 'bash harness/restore_baseline.sh > '$O'/bisect6-restore.log 2>&1; echo RESTORED >> '$O'/bisect6.log' EXIT
: > $O/bisect6.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
CO=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
for cfg in "bisect-18c5a95e GGML_SYCL_MMID_SCHED=0" "bisect-18c5a95e GGML_SYCL_MMVQ_WIDE=0" "bisect-18c5a95e GGML_SYCL_MMID_SCHED=0 GGML_SYCL_MMVQ_WIDE=0" "head-a956a852 GGML_SYCL_MMVQ_WIDE=0" "head-a956a852 GGML_SYCL_MMID_SCHED=0 GGML_SYCL_MMVQ_WIDE=0"; do
  set -- $cfg; tag=$1; shift
  r=$(EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0 $*" harness/research_run.sh bench t 0 localhost/sycl-research/llama:$tag $CO -ngl 99 -fa 1 -b 4096 -ub 2048 -p 32768 -n 0 -r 3 -o jsonl 2>/dev/null | python3 -I -c "
import sys,json
for l in sys.stdin:
    d=json.loads(l); print(round(d['avg_ts'],1),round(d['stddev_ts'],1))")
  echo "$tag ESIMD0 $* : $r" >> $O/bisect6.log
done
