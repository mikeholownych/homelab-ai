#!/usr/bin/env bash
# Live validation of the two rungs the first rehearsal did not exercise, on production worker2 (deep route, GPU1):
#   * forced kill: --stop-timeout 5 makes the graceful `systemctl stop` count as failed (it needs ~20 s), so the ladder must go KILL -> restart;
#   * rate limit:  --max-restarts-per-hour 2 and THREE consecutive stalls in one executor session: cycles 1 and 2 must restart and readmit, cycle 3 must
#                  produce an ALERT and leave the worker alone (abandoned) instead of a third restart.
# Same safety as window3_watchdog_rehearsal.sh: idle gate, SIGSTOP of the worker2 container while a long generation runs, admin token in a 0700 temp
# file shredded on exit, EXIT trap thaws, undrains and runs restore_baseline.sh.
set -u; cd "$(dirname "$0")/.."; ROOT=$(cd ../..; pwd); O=evidence/window3/watchdog-cycles; H=10.0.8.5; mkdir -p $O; L=$O/cycles.log
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
bash harness/pause_reconcile.sh >/dev/null
$PY $ROOT/scripts/worker_watchdog.py --base $BASE --ca $CA --token-file $TF --host $H --unit $WID=$UNIT --apply --stuck-after 40 --drain-wait 10 \
  --interval 5 --stop-timeout 5 --max-restarts-per-hour 2 --evidence $O/watchdog-evidence.jsonl > $O/watchdog.out 2>&1 &
WDPID=$!
HOLD=/home/mike/work/correctness-20261023/wd-hold-load-engineering-deep.json
count() { grep -c "\"action\": \"$1\"" $O/watchdog-evidence.jsonl 2>/dev/null || echo 0; }
for cycle in 1 2 3; do
  echo "== cycle $cycle $(date -u +%FT%TZ)" >> $L
  rm -f $HOLD
  ( cd $ROOT && /home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/controller_qualification_probe.yml \
    -e '{"probe_label":"wd-hold","probe_mode":"hold","probe_models":["engineering/deep"],"probe_repeats":1,"probe_concurrency":1}' \
    -e qualification_ansible=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook > /dev/null 2>&1 ) &
  sleep 15
  [ -f $HOLD ] && { echo "ABORT: hold finished early; worker idle" >> $L; exit 2; }
  echo "SIGSTOP $(date -u +%FT%TZ)" >> $L
  ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman kill --signal SIGSTOP $CONT" >> $L 2>&1
  want_undrain=$cycle; [ $cycle -ge 3 ] && want_undrain=2
  t0=$(date +%s)
  while [ $(( $(date +%s)-t0 )) -lt 600 ]; do
    echo "$(date -u +%T) gauge: $(wd --show 2>&1 | cut -c1-130)" >> $L
    [ "$(count undrain)" -ge "$want_undrain" ] && [ $cycle -lt 3 ] && break
    [ $cycle -ge 3 ] && [ "$(count alert)" -ge 1 ] && break
    sleep 15
  done
  echo "cycle $cycle done: drain=$(count drain) stop=$(count stop) kill=$(count kill) restart=$(count restart) undrain=$(count undrain) alert=$(count alert)" >> $L
  [ $cycle -lt 3 ] && sleep 20
done
kill $WDPID 2>/dev/null; WDPID=""
echo "units: $(ssh -o BatchMode=yes $H 'systemctl is-active aihost-llama-worker1 aihost-llama-worker2' | tr '\n' ' ')" >> $L
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
