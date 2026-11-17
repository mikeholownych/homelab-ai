#!/usr/bin/env bash
# KL-divergence correctness gate: baseline image writes logits, candidate image is scored against them.
# Usage: kl_gate.sh <candidate-image> <tag> [model-relpath] [chunks]
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
CAND="$1"; TAG="$2"; MODEL="${3:-qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf}"; CH="${4:-20}"
OUT=evidence/correctness; export EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw" SUBCMD=perplexity
COMMON="-ngl 99 -fa on -b 4096 -ub 2048 -c 2048 --chunks $CH -f /research/kl-corpus.txt"
harness/research_run.sh bench "kl-base-$TAG" 0 "$BASE" "$MODEL" -- $COMMON --kl-divergence-base /research/base-logits-$TAG.bin > "$OUT/kl-base-$TAG.txt" 2>&1
harness/research_run.sh bench "kl-cand-$TAG" 0 "$CAND" "$MODEL" -- $COMMON --kl-divergence-base /research/base-logits-$TAG.bin --kl-divergence > "$OUT/kl-cand-$TAG.txt" 2>&1
echo done > "$OUT/kl-$TAG.done"
