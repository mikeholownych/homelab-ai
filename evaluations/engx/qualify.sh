#!/usr/bin/env bash
# Q-TOOLS, Q-LONGCTX and Q-MMAP for one candidate at its production reasoning budget (docs/closeout, todo.md).
#
#   evaluations/engx/qualify.sh <candidate-profile> <budget>
#
# Runs on the controller (a remote client of the gateway); nothing is initiated on the inference host. The candidate is
# deployed through playbooks/candidate.yml, the gateway must report the budget, and the qualification token is piped
# from the host's root-only file. The host's own page-cache/fault metrics (read, not generated, over ssh) bracket the
# long-context run as Q-MMAP evidence.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
host=10.0.8.5
base=https://10.0.8.5:8443
token_file=/etc/local-ai/orchestrator/clients/qualification.token
profile=${1:?candidate profile}
budget=${2:?reasoning budget}
alias=$(cd "$repo" && .venv/bin/python - "$profile" <<'EOF'
import sys, yaml
profiles = yaml.safe_load(open("inventory/production/host_vars/ai-5820-01.yml"))["llama_cpp_container_candidate_profiles"]
print(profiles[sys.argv[1]]["gateway_worker"]["public_model_id"])
EOF
)
out="$repo/evaluations/engx/results/qualify-$(date -u +%Y%m%d)"
label="${profile}-bounded-${budget}"
mkdir -p "$out"

token() { ssh -o BatchMode=yes "$host" "sudo -n cat $token_file"; }
snapshot() {  # the host textfile metrics plus node_exporter's host-wide fault and memory series
  ssh -o BatchMode=yes "$host" 'date -u +%FT%TZ; grep -E "^aihost_llama" /var/lib/local-ai/metrics/gpu.prom;
    curl -s http://127.0.0.1:9100/metrics | grep -E "^node_vmstat_pgmajfault|^node_memory_(Cached|MemAvailable|MemTotal)_bytes"' > "$out/$label.mmap-$1.prom"
}

echo "== $(date -u +%FT%TZ) deploy $profile budget=$budget"
(cd "$repo" && .venv/bin/ansible-playbook -i inventory/production -l ai-5820-01 playbooks/candidate.yml \
    -e "candidate=$profile" -e "candidate_reasoning_budget=$budget") > "$out/$label.deploy.log" 2>&1 \
  || { echo "deploy failed; see $out/$label.deploy.log"; exit 1; }

for kind in tools longctx; do
  if [ "$kind" = longctx ]; then snapshot before; fi
  echo "== $(date -u +%FT%TZ) $kind $label"
  token | (cd "$repo/evaluations/engx" && ENGX_OUT="$out" QUALIFY_EXPECT_BUDGET="$budget" ENGX_PYTHON="$repo/.venv/bin/python" \
      "$repo/.venv/bin/python" qualify.py "$kind" "$label" "$base" - "$alias") 2>&1 | tee "$out/$label.$kind.log" \
    | grep --line-buffered -E "RESULT|FAIL|Error"
  if [ "$kind" = longctx ]; then snapshot after; fi
done
echo "== $(date -u +%FT%TZ) done"
