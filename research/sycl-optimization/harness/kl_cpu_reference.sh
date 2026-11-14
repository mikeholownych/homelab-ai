#!/usr/bin/env bash
# CPU ground-truth: write logits on CPU (no device), then score baseline and candidate GPU builds against them.
# Usage: kl_cpu_reference.sh <candidate-image> [chunks]
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
CAND="$1"; CH="${2:-3}"; M=qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf; O=evidence/correctness
export EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity
C="-fa on -b 2048 -ub 2048 -c 2048 --chunks $CH -f /research/kl-corpus.txt"
harness/research_run.sh bench cpu-ref 0 "$BASE" "$M" -- -dev none -ngl 0 $C --kl-divergence-base /research/cpu-logits.bin > $O/cpu-ref.txt 2>&1
echo cpu-ref-done > $O/cpu-ref.done
harness/research_run.sh bench cpu-s-base 0 "$BASE" "$M" -- -ngl 99 $C --kl-divergence-base /research/cpu-logits.bin --kl-divergence > $O/cpu-score-base.txt 2>&1
harness/research_run.sh bench cpu-s-head 0 "$CAND" "$M" -- -ngl 99 $C --kl-divergence-base /research/cpu-logits.bin --kl-divergence > $O/cpu-score-head.txt 2>&1
echo done > $O/cpu-gate.done
