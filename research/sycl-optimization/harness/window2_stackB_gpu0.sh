#!/usr/bin/env bash
# One GPU0 outage: candidate head-stackB (HEAD source + current oneDNN + OLD IGC/NEO pair), ESIMD=0, on Qwen3.6 and Coder-30B:
# bench pp512/2048/8192/32768 + tg128 (3 reps) and KL vs the saved CPU-truth logits (3 chunks). Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2; K=evidence/correctness
trap 'bash harness/restore_baseline.sh > '$O'/stackB-gpu0-restore.log 2>&1; echo RESTORED >> '$O'/stackB-gpu0.log' EXIT
: > $O/stackB-gpu0.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
IMG=localhost/sycl-research/llama:head-stackB
Q36=qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf; CO=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
for spec in "q36 $Q36 cpu-logits.bin" "co $CO cpu-logits-co.bin"; do
  set -- $spec; tag=$1; m=$2; logits=$3
  EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh bench sb 0 $IMG $m -ngl 99 -fa 1 -b 4096 -ub 2048 -p 512,2048,8192,32768 -n 128 -r 3 -o jsonl > $O/stackB-$tag.jsonl 2>/dev/null
  echo "$tag bench $(python3 -I -c "
import json
print([(d['n_prompt'],d['n_gen'],round(d['avg_ts'],1)) for d in map(json.loads,open('$O/stackB-$tag.jsonl'))])")" >> $O/stackB-gpu0.log
  EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" \
    harness/research_run.sh bench klb 0 $IMG $m -- -ngl 99 -fa on -b 2048 -ub 2048 -c 2048 --chunks 3 -f /research/kl-corpus.txt --kl-divergence-base /research/$logits --kl-divergence > $K/stackB-kl-$tag.txt 2>&1
  echo "$tag kl $(grep -E 'Mean +KLD|Same top p' $K/stackB-kl-$tag.txt | tr -s ' ' | tr '\n' ';')" >> $O/stackB-gpu0.log
done
