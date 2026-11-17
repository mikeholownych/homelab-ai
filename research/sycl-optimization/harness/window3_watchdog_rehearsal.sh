#!/usr/bin/env bash
# Window 3 follow-up: LIVE rehearsal of the worker busy-watchdog on production worker2 (Flash-Next, deep route, GPU1).
# A long generation is started through the gateway, then the worker container is SIGSTOPped (a wedge: connection accepted, nothing answered).
# The executor (scripts/worker_watchdog.py --apply, shortened timings) must: see the stall in aihost_engine_stalled_seconds, drain the worker,
# stop it (the stopped process cannot exit on SIGTERM, so the stop times out or is killed), kill if needed, restart, wait for gateway readiness,
# undrain. Idle gate first; the EXIT trap SIGCONTs, undrains and runs restore_baseline.sh. The admin token (ansible-admin client) is read over
# SSH into a 0700 temp dir, never printed, and shredded on exit.
set -u; cd "$(dirname "$0")/.."; ROOT=$(cd ../..; pwd); O=evidence/window3/watchdog; H=10.0.8.5; mkdir -p $O; L=$O/rehearsal.log
PY=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/python
CA=/home/mike/.config/nexus/t5820-gateway-ca.crt; BASE=https://10.0.8.5:8443
WID=b0-live-llama-deep-worker2; UNIT=aihost-llama-worker2.service; CONT=llama-sycl-worker2
TD=$(mktemp -d); chmod 700 $TD; TF=$TD/admin.token
( umask 077; ssh -o BatchMode=yes $H 'sudo -n cat /etc/local-ai/orchestrator/clients/ansible-admin.token' > $TF )
wd() { $PY $ROOT/scripts/worker_watchdog.py --base $BASE --ca $CA --token-file $TF --host $H --unit $WID=$UNIT "$@"; }
cleanup() {
  [ -n "${WDPID:-}" ] && kill $WDPID 2>/dev/null
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman kill --signal SIGCONT $CONT >/dev/null 2>&1; true"
  $PY - "$ROOT" "$BASE" "$CA" "$TF" "$WID" >> $L 2>&1 <<'PYE'
import sys
root, base, ca, tf, wid = sys.argv[1:6]
sys.path.insert(0, root)
from scripts.worker_watchdog import Gateway
g = Gateway(base, ca, open(tf).read().strip())
print("trap undrain", wid, g.undrain(wid))
PYE
  bash harness/restore_baseline.sh > $O/restore.log 2>&1; echo "RESTORED rc=$?" >> $L
  shred -u $TF 2>/dev/null; rm -rf $TD
}
trap cleanup EXIT
WDPID=""
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
echo "gauge before: $(wd --show 2>&1)" >> $L
bash harness/pause_reconcile.sh >/dev/null
# 1. keep worker2 busy
S=$O/hold.out
( cd $ROOT && /home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/controller_qualification_probe.yml \
  -e '{"probe_label":"wd-hold","probe_mode":"hold","probe_models":["engineering/deep"],"probe_repeats":1,"probe_concurrency":1}' \
  -e qualification_ansible=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook > $ROOT/research/sycl-optimization/$S 2>&1 ) &
sleep 25
echo "gauge while busy: $(wd --show 2>&1)" >> $L
# 2. wedge it
echo "SIGSTOP $(date -u +%FT%TZ)" >> $L
ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman kill --signal SIGSTOP $CONT" >> $L 2>&1
# 3. watchdog with shortened timings (stuck after 40 s of silence, drain wait 10 s)
wd --apply --stuck-after 40 --drain-wait 10 --interval 5 --evidence $O/watchdog-evidence.jsonl > $O/watchdog.out 2>&1 &
WDPID=$!
t0=$(date +%s)
while [ $(( $(date +%s)-t0 )) -lt 900 ]; do
  echo "$(date -u +%T) gauge: $(wd --show 2>&1 | cut -c1-160)" >> $L
  grep -q '"action": "undrain".*"ok": true' $O/watchdog-evidence.jsonl 2>/dev/null && break
  grep -q '"action": "abandon"\|"action": "alert"' $O/watchdog-evidence.jsonl 2>/dev/null && break
  sleep 15
done
kill $WDPID 2>/dev/null; WDPID=""
echo "gauge after: $(wd --show 2>&1)" >> $L
echo "units: $(ssh -o BatchMode=yes $H 'systemctl is-active aihost-llama-worker1 aihost-llama-worker2' | tr '\n' ' ')" >> $L
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
