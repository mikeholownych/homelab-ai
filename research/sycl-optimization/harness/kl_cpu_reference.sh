#!/usr/bin/env bash
# CPU ground-truth: write logits on CPU (no device), then score baseline and candidate GPU builds against them.
# Usage: [GPU=0] [M=<model-relpath>] [TAG=] [BATCH=2048] kl_cpu_reference.sh <candidate-image> [chunks]
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
CAND="$1"; CH="${2:-3}"; GPU="${GPU:-0}"; M="${M:-qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf}"; T="${TAG:-}"; B="${BATCH:-2048}"
O="${OUT:-evidence/correctness}"; mkdir -p "$O"
export EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity
C="-fa on -b $B -ub 2048 -c 2048 --chunks $CH -f /research/kl-corpus.txt"
L=/research/cpu-logits$T.bin
harness/research_run.sh bench cpu-ref$T "$GPU" "$BASE" "$M" -- -dev none -ngl 0 $C --kl-divergence-base $L > $O/cpu-ref$T.txt 2>&1
echo cpu-ref-done > $O/cpu-ref$T.done
harness/research_run.sh bench cpu-s-base$T "$GPU" "$BASE" "$M" -- -ngl 99 $C --kl-divergence-base $L --kl-divergence > $O/cpu-score-base$T.txt 2>&1
harness/research_run.sh bench cpu-s-head$T "$GPU" "$CAND" "$M" -- -ngl 99 $C --kl-divergence-base $L --kl-divergence > $O/cpu-score-head$T.txt 2>&1
echo done > $O/cpu-gate$T.done
