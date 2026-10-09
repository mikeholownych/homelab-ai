#!/usr/bin/env bash
# Q-CONTRACT on the promoted production aliases, from the controller through the TLS gateway.
set -euo pipefail
repo=/home/mike/Projects/aihost
out=$repo/evaluations/engx/results/contract-20261009
for pair in "engineering/deep:deep-flashnext-4096" "engineering/b0:b0-qwen36-8192" "engineering/lead:lead-qwen36-off"; do
  alias=${pair%%:*}; label=${pair#*:}
  echo "== $(date -u +%FT%TZ) contract $alias"
  ssh -o BatchMode=yes 10.0.8.5 "sudo -n cat /etc/local-ai/orchestrator/clients/qualification.token" \
    | (cd $repo/evaluations/engx && ENGX_OUT=$out $repo/.venv/bin/python qualify.py contract "$label" https://10.0.8.5:8443 - "$alias") 2>&1 \
    | tee "$out/$label.log"
done
echo "== $(date -u +%FT%TZ) done"
