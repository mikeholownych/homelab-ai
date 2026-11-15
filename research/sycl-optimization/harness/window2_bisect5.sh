#!/usr/bin/env bash
# One GPU0 outage: Coder-30B pp32768 with XMX-ESIMD off on bisect images 1b6935b2 and 8766c027. Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2
trap 'bash harness/restore_baseline.sh > '$O'/bisect5-restore.log 2>&1; echo RESTORED >> '$O'/bisect5.log' EXIT
: > $O/bisect5.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
CO=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
for t in 1b6935b2 8766c027; do
  r=$(EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh bench t 0 localhost/sycl-research/llama:bisect-$t $CO -ngl 99 -fa 1 -b 4096 -ub 2048 -p 2048,32768 -n 0 -r 3 -o jsonl 2>/dev/null | python3 -I -c "
import sys,json
for l in sys.stdin:
    d=json.loads(l); print('pp%d'%d['n_prompt'],round(d['avg_ts'],1),round(d['stddev_ts'],1),end=' ')")
  echo "$t ESIMD0: $r" >> $O/bisect5.log
done
