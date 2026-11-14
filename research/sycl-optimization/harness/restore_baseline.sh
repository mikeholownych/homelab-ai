#!/usr/bin/env bash
# Restore the production inference baseline on ai-5820-01 and verify it. Idempotent.
# Usage: restore_baseline.sh [host]   (run from the workstation; default host 10.0.8.5)
# Steps: stop every research unit, start production workers, wait for gateway readiness with both workers healthy.
set -euo pipefail
HOST="${1:-10.0.8.5}"
# The workstation-side hourly reconcile timer is paused during research windows; re-enable it first.
systemctl --user start aihost-reconcile.timer 2>/dev/null || true
PIN="sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451"
ssh -o BatchMode=yes "$HOST" 'bash -s' -- "$PIN" <<'REMOTE'
set -euo pipefail
PIN="$1"
cd /
# 1. stop research units (never touches production units' files)
for u in $(systemctl list-units --no-legend --plain 'sycl-research-*' | awk '{print $1}'); do sudo -n systemctl stop "$u" || true; done
# 2. production unit files must still reference the pinned image
for n in 1 2; do
  grep -q "$PIN" "/etc/systemd/system/aihost-llama-worker$n.service" || { echo "FAIL: worker$n unit does not reference pinned image"; exit 2; }
done
# 3. start production workers
sudo -n systemctl start aihost-llama-worker1.service aihost-llama-worker2.service
# 4. wait for gateway readiness with 2/2 workers (model load can take minutes)
for i in $(seq 1 120); do
  h=$(curl -s -m 5 127.0.0.1:8010/health || true)
  if echo "$h" | python3 -c 'import sys,json; d=json.load(sys.stdin); s=d["scheduler"]; sys.exit(0 if d["ready"] and s["available_workers"]==2 else 1)' 2>/dev/null; then
    echo "OK: baseline restored, gateway ready, 2/2 workers available"; exit 0
  fi
  sleep 5
done
echo "FAIL: baseline not healthy after 10 min"; exit 1
REMOTE
