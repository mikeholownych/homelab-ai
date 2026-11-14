#!/usr/bin/env bash
# Score an image against previously saved baseline logits. Usage: kl_score.sh <image> <logits-tag> <out-name> <batch> [extra env KEY=VAL ...]
set -euo pipefail
cd "$(dirname "$0")/.."
IMG="$1"; LT="$2"; OUTN="$3"; B="$4"; shift 4
export EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity EXTRA_ENV="$*"
harness/research_run.sh bench "kls-$OUTN" 0 "$IMG" qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf -- -ngl 99 -fa on -b $B -ub 2048 -c 2048 --chunks 20 -f /research/kl-corpus.txt --kl-divergence-base /research/base-logits-$LT.bin --kl-divergence > evidence/correctness/kls-$OUTN.txt 2>&1
echo done > evidence/correctness/kls-$OUTN.done
