#!/usr/bin/env bash
# One short GPU0 outage: dense-model sanity (upstream #30892: F16 NaN on dense Qwen3.8-27B). Perplexity (3 chunks) + bench on the
# deployed image and head-stackB (ESIMD=0). Pass = finite PPL on both and no large gap. Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2; K=evidence/correctness
trap 'bash harness/restore_baseline.sh > '$O'/dense-restore.log 2>&1; echo RESTORED >> '$O'/dense.log' EXIT
: > $O/dense.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
M=qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf
BASE=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
for v in deployed stackB; do
  if [ $v = deployed ]; then IMG=$BASE; EE="GGML_X=1"; else IMG=localhost/sycl-research/llama:head-stackB; EE="GGML_SYCL_ENABLE_XMX_ESIMD=0"; fi
  EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity EXTRA_ENV="$EE" \
    harness/research_run.sh bench dn 0 $IMG $M -- -ngl 99 -fa on -b 2048 -ub 2048 -c 2048 --chunks 3 -f /research/kl-corpus.txt > $K/dense-ppl-$v.txt 2>&1
  echo "$v ppl: $(grep -E 'Final estimate|PPL' $K/dense-ppl-$v.txt | tail -1 | cut -c1-160); nan: $(grep -ciE 'nan' $K/dense-ppl-$v.txt)" >> $O/dense.log
  EXTRA_ENV="$EE" harness/research_run.sh bench dn 0 $IMG $M -ngl 99 -fa 1 -b 4096 -ub 2048 -p 512,2048 -n 64 -r 2 -o jsonl > $O/dense-bench-$v.jsonl 2>/dev/null
  echo "$v bench: $(python3 -I -c "
import json,sys
print([(d['n_prompt'],d['n_gen'],round(d['avg_ts'],1)) for d in map(json.loads,open(sys.argv[1]))])" $O/dense-bench-$v.jsonl 2>&1 | tail -1)" >> $O/dense.log
done
