#!/usr/bin/env bash
# Validate the UNATTENDED path: the scheduled aihost-worker-watchdog.service (apply mode, role defaults: stuck after 120 s) must handle a real stall
# on production worker2 by itself. This script does NOT run the executor; it only creates the stall (long generation + SIGSTOP of the worker2
# container) and watches the service's evidence file and the worker. Idle gate first; the EXIT trap thaws the container, undrains worker2 if the
# service left it drained, and runs restore_baseline.sh.
set -u; cd "$(dirname "$0")/.."; ROOT=$(cd ../..; pwd); O=evidence/window3/watchdog-service; H=10.0.8.5; mkdir -p $O; L=$O/service-check.log
EV=/home/mike/.local/share/aihost/reconcile/evidence/worker-watchdog.jsonl
PY=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/python
CA=/home/mike/.config/nexus/t5820-gateway-ca.crt; BASE=https://10.0.8.5:8443; TF=/home/mike/.config/aihost/watchdog.token
WID=b0-live-llama-deep-worker2; CONT=llama-sycl-worker2
cleanup() {
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
}
trap cleanup EXIT
: > $L
echo "service: $(systemctl --user is-active aihost-worker-watchdog.service)" >> $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
bash harness/pause_reconcile.sh >/dev/null
before=$(wc -l < $EV 2>/dev/null || echo 0); echo "evidence lines before: $before" >> $L
HOLD=/home/mike/work/correctness-20261023/wd-hold-load-engineering-deep.json; rm -f $HOLD
( cd $ROOT && /home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/controller_qualification_probe.yml \
  -e '{"probe_label":"wd-hold","probe_mode":"hold","probe_models":["engineering/deep"],"probe_repeats":1,"probe_concurrency":1}' \
  -e qualification_ansible=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook > /dev/null 2>&1 ) &
sleep 15
[ -f $HOLD ] && { echo "ABORT: hold finished early; worker idle" >> $L; exit 2; }
echo "SIGSTOP $(date -u +%FT%TZ)" >> $L
ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman kill --signal SIGSTOP $CONT" >> $L 2>&1
t0=$(date +%s)
while [ $(( $(date +%s)-t0 )) -lt 900 ]; do
  lines=$(wc -l < $EV 2>/dev/null || echo 0)
  echo "$(date -u +%T) evidence_lines=$lines worker2=$(ssh -o BatchMode=yes $H 'systemctl is-active aihost-llama-worker2')" >> $L
  tail -n +$((before+1)) $EV 2>/dev/null | grep -q '"action": "undrain".*"ok": true' && break
  tail -n +$((before+1)) $EV 2>/dev/null | grep -q '"action": "alert"\|"action": "abandon"' && break
  sleep 15
done
tail -n +$((before+1)) $EV 2>/dev/null > $O/service-evidence.jsonl
echo "units: $(ssh -o BatchMode=yes $H 'systemctl is-active aihost-llama-worker1 aihost-llama-worker2' | tr '\n' ' ')" >> $L
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
