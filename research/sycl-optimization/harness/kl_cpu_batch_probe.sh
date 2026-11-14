#!/usr/bin/env bash
# Probe: score baseline and candidate at -b 4096 (n_seq=2) against CPU ground-truth logits. Usage: kl_cpu_batch_probe.sh <candidate-image>
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
M=qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf; O=evidence/correctness
export EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity
C="-fa on -b 4096 -ub 2048 -c 2048 --chunks 3 -f /research/kl-corpus.txt --kl-divergence-base /research/cpu-logits.bin --kl-divergence"
harness/research_run.sh bench p-base 0 "$BASE" "$M" -- -ngl 99 $C > $O/cpu-score-base-b4096.txt 2>&1
harness/research_run.sh bench p-head 0 "$1" "$M" -- -ngl 99 $C > $O/cpu-score-head-b4096.txt 2>&1
echo done > $O/cpu-probe.done
