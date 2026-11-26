#!/usr/bin/env bash
# Budget-shaped compare: solo (max_attempts=1) vs Bon n=3 (max_attempts=1 each, early exit).
# Usage: run_bon_vs_solo.sh <stamp> [pin=lead] [reps=1]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
STAMP="${1:?stamp}"
PIN="${2:-lead}"
REPS="${3:-1}"
EVID="$REPO/evaluations/nexus_e2e/evidence/$STAMP"
mkdir -p "$EVID"
export ENGX_PYTHON="$REPO/.venv/bin/python"
TOKEN() {
  python3 - <<'PY'
from pathlib import Path
env = {}
for line in Path("/home/mike/.config/nexus/config.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
print(env["LOCAL_LLM_API_KEY"], end="")
PY
}
LOG="$EVID/bon_vs_solo.run.log"
{
  echo "stamp=$STAMP pin=$PIN reps=$REPS started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "=== solo-$PIN max_attempts=1 ==="
  TOKEN | "$REPO/.venv/bin/python" "$REPO/evaluations/nexus_e2e/drivers/solo.py" \
    --pin "$PIN" --base https://10.0.8.5:8443 --token-file - \
    --reps "$REPS" --max-attempts 1 --max-tokens 8192 \
    --stamp "$STAMP" --out "$EVID"
  # Rewrite arm label note: solo.py writes solo-$PIN; keep as matched baseline
  echo "=== bon3-$PIN n=3 temp=0.2 max_attempts=1 ==="
  TOKEN | "$REPO/.venv/bin/python" "$REPO/evaluations/nexus_e2e/drivers/best_of_n.py" \
    --pin "$PIN" --n 3 --temperature 0.2 --base https://10.0.8.5:8443 --token-file - \
    --reps "$REPS" --max-attempts 1 --max-tokens 8192 \
    --stamp "$STAMP" --out "$EVID"
  "$REPO/.venv/bin/python" "$REPO/evaluations/nexus_e2e/scripts/compare_bon_vs_solo.py" \
    --evidence-dir "$EVID" --solo-arm "solo-$PIN" --bon-arm "bon3-$PIN"
  echo "done=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee -a "$LOG"
