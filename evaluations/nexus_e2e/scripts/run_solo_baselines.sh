#!/usr/bin/env bash
# Sequential Stage-1 solo baselines: deep → lead → rocm.
# Usage: run_solo_baselines.sh <stamp> [reps=3]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
STAMP="${1:?stamp required}"
REPS="${2:-3}"
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
LOG="$EVID/solo_baselines.run.log"
{
  echo "stamp=$STAMP reps=$REPS started=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for pin in deep lead rocm; do
    echo "=== starting solo-$pin $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    TOKEN | "$REPO/.venv/bin/python" "$REPO/evaluations/nexus_e2e/drivers/solo.py" \
      --pin "$pin" --base https://10.0.8.5:8443 --token-file - \
      --reps "$REPS" --max-attempts 3 --max-tokens 8192 \
      --stamp "$STAMP" --out "$EVID"
    echo "=== finished solo-$pin $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  done
  "$REPO/.venv/bin/python" "$REPO/evaluations/nexus_e2e/scripts/aggregate_solo_baselines.py" \
    --evidence-dir "$EVID"
  echo "done=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee -a "$LOG"
