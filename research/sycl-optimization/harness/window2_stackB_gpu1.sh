#!/usr/bin/env bash
# One GPU1 outage (worker 2): candidate head-stackB on Flash-Next IQ1_M: bench pp512/2048/8192 + tg128 (ESIMD default and off, 3 reps)
# and KL vs the saved CPU-truth logits (3 chunks, ESIMD=0). Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2; K=evidence/correctness
trap 'bash harness/restore_baseline.sh > '$O'/stackB-gpu1-restore.log 2>&1; echo RESTORED >> '$O'/stackB-gpu1.log' EXIT
: > $O/stackB-gpu1.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes 10.0.8.5 'cd /; sudo -n systemctl stop aihost-llama-worker2.service'
IMG=localhost/sycl-research/llama:head-stackB
FN=flashnext-gsq-coder/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
for e in "GGML_SYCL_X=1" "GGML_SYCL_ENABLE_XMX_ESIMD=0"; do
  EXTRA_ENV="$e" harness/research_run.sh bench sb 1 $IMG $FN -ngl 99 -fa 1 -b 4096 -ub 2048 -p 512,2048,8192 -n 128 -r 3 -o jsonl > $O/stackB-fn-$(echo $e | tr -c 'A-Za-z0-9\n' _).jsonl 2>/dev/null
  echo "fn bench [$e] $(python3 -I -c "
import json,sys
print([(d['n_prompt'],d['n_gen'],round(d['avg_ts'],1)) for d in map(json.loads,open(sys.argv[1]))])" $O/stackB-fn-$(echo $e | tr -c 'A-Za-z0-9\n' _).jsonl)" >> $O/stackB-gpu1.log
done
EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" \
  harness/research_run.sh bench klb 1 $IMG $FN -- -ngl 99 -fa on -b 2048 -ub 2048 -c 2048 --chunks 3 -f /research/kl-corpus.txt --kl-divergence-base /research/cpu-logits-fn.bin --kl-divergence > $K/stackB-kl-fn.txt 2>&1
echo "fn kl $(grep -E 'Mean +KLD|Same top p' $K/stackB-kl-fn.txt | tr -s ' ' | tr '\n' ';')" >> $O/stackB-gpu1.log
