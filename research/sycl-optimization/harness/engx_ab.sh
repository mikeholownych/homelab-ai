#!/usr/bin/env bash
# Task-level accuracy A/B: launch a research llama-server (production flags) on GPU0:18100, run engx on the host against it, stop it.
# Usage: engx_ab.sh <label> <image> [attempts] [corpus]
set -euo pipefail
cd "$(dirname "$0")/.."
LABEL="$1"; IMG="$2"; ATT="${3:-3}"; CORPUS="${4:-base}"; HOST=10.0.8.5
harness/research_run.sh stop "engx-$LABEL" >/dev/null 2>&1 || true
harness/research_run.sh server "engx-$LABEL" 0 18100 "$IMG" -- -m /models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf -c 65536 --reasoning-budget 8192 -ngl 99 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics --lazy-mode on
for i in $(seq 1 120); do ssh -o BatchMode=yes $HOST 'curl -sf -m3 127.0.0.1:18100/health >/dev/null' && break; sleep 5; done
ssh -o BatchMode=yes $HOST 'curl -sf -m3 127.0.0.1:18100/health' >/dev/null || { echo "server never became healthy"; exit 1; }
ssh -o BatchMode=yes $HOST "cd ~/sycl-research/engx && mkdir -p ~/sycl-research/evidence/engx-$LABEL && ENGX_CORPUS=$CORPUS ENGX_REPS=2 ENGX_REASONING_BUDGET=8192 ENGX_MAX_TOKENS=12288 ENGX_OUT=\$HOME/sycl-research/evidence/engx-$LABEL python3 engx.py run $LABEL http://127.0.0.1:18100 - qwen3.6 $ATT" > evidence/correctness/engx-$LABEL.txt 2>&1 || true
harness/research_run.sh stop "engx-$LABEL"
echo done > evidence/correctness/engx-$LABEL.done
