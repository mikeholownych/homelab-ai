#!/usr/bin/env bash
# Q-BUDGET: choose the production reasoning budget from bounded evidence (docs/closeout, todo.md).
#
#   evaluations/engx/qbudget.sh <candidate-profile> <budget> [<budget> ...]
#
# Runs on the controller (a remote client of the gateway); nothing is initiated on the inference host. For each budget
# the candidate is redeployed through playbooks/candidate.yml with that server-side --reasoning-budget, the gateway
# alias is checked to report the same budget, and the hard corpus runs 3 reps through the TLS gateway with the
# qualification-scoped token piped from the host's root-only file (never written here, never in argv).
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
host=10.0.8.5
base=https://10.0.8.5:8443
token_file=/etc/local-ai/orchestrator/clients/qualification.token
profile=${1:?candidate profile}; shift
alias=$(cd "$repo" && .venv/bin/python - "$profile" <<'EOF'
import sys, yaml
profiles = yaml.safe_load(open("inventory/production/host_vars/ai-5820-01.yml"))["llama_cpp_container_candidate_profiles"]
print(profiles[sys.argv[1]]["gateway_worker"]["public_model_id"])
EOF
)
out="$repo/evaluations/engx/results/qbudget-$(date -u +%Y%m%d)"
message=$(cd "$repo" && .venv/bin/python -c 'import yaml; print(yaml.safe_load(open("roles/llama_cpp_container/defaults/main.yml"))["llama_cpp_container_reasoning_budget_message"].strip())')
mkdir -p "$out"

token() { ssh -o BatchMode=yes "$host" "sudo -n cat $token_file"; }

for budget in "$@"; do
  label="${profile}-bounded-${budget}"
  echo "== $(date -u +%FT%TZ) deploy $profile budget=$budget"
  (cd "$repo" && .venv/bin/ansible-playbook -i inventory/production -l ai-5820-01 playbooks/candidate.yml \
      -e "candidate=$profile" -e "candidate_reasoning_budget=$budget") > "$out/$label.deploy.log" 2>&1 \
    || { echo "deploy failed; see $out/$label.deploy.log"; exit 1; }

  # The gateway is the authority on what it will apply; refuse to measure a budget it does not report.
  reported=$(token | "$repo/.venv/bin/python" -c '
import json, sys, urllib.request
key, alias = sys.stdin.read().strip(), sys.argv[1]
req = urllib.request.Request(sys.argv[2] + "/v1/models", headers={"Authorization": "Bearer " + key})
for m in json.load(urllib.request.urlopen(req, timeout=30))["data"]:
    if m["id"] == alias:
        print(json.dumps(m.get("reasoning")))
' "$alias" "$base")
  echo "   gateway reports for $alias: $reported"
  case "$reported" in *"\"budget\": $budget"*|*"\"budget\":$budget"*) ;; *) echo "budget $budget not reported by the gateway"; exit 1;; esac

  echo "== $(date -u +%FT%TZ) run $label"
  token | (cd "$repo/evaluations/engx" && ENGX_CORPUS=hard ENGX_REPS=3 ENGX_OUT="$out" \
      ENGX_MAX_TOKENS=$((budget + 8192)) ENGX_REASONING_BUDGET="$budget" ENGX_REASONING_BUDGET_MESSAGE="$message" \
      ENGX_CONDITION="THINKING_ON_BOUNDED_${budget}_VIA_GATEWAY" ENGX_PYTHON="$repo/.venv/bin/python" \
      python3 engx.py run "$label" "$base" - "$alias" 3) 2>&1 | tee "$out/$label.log" | grep --line-buffered -E "RESULT|FAIL|PASS"
done
echo "== $(date -u +%FT%TZ) done"
