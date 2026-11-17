#!/usr/bin/env bash
# Live validation of slot-state persistence on a watchdog restart (production worker2, deep route). The scheduled watchdog service (apply mode,
# --slot-save-interval 300) is the system under test; this script only creates the situation and reads the results:
#   1. one fixed ~16k-token conversation through the gateway (cold TTFT);
#   2. wait until the service has saved worker2's state after that conversation (slot_save record with tokens > 0);
#   3. start a different long generation and SIGSTOP the worker container (a wedge); the service drains, stops, restarts, RESTORES the saved
#      state (slot_restore record) and readmits;
#   4. the same conversation again: if the restore worked, TTFT is a cache hit instead of a cold prefill.
# Idle gate first; EXIT trap thaws, undrains and runs restore_baseline.sh.
set -u; cd "$(dirname "$0")/.."; ROOT=$(cd ../..; pwd); O=evidence/window3/slot-restore; H=10.0.8.5; mkdir -p $O; L=$O/slot-restore.log
EV=/home/mike/.local/share/aihost/reconcile/evidence/worker-watchdog.jsonl
PY=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/python; ANS=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook
CA=/home/mike/.config/nexus/t5820-gateway-ca.crt; BASE=https://10.0.8.5:8443; TF=/home/mike/.config/aihost/watchdog.token
WID=b0-live-llama-deep-worker2; CONT=llama-sycl-worker2; OUT=/home/mike/work/correctness-20261023
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
probe() { # label mode
  ( cd $ROOT && $ANS -i inventory/production/hosts.yml playbooks/controller_qualification_probe.yml \
    -e "{\"probe_label\":\"$1\",\"probe_mode\":\"$2\",\"probe_models\":[\"engineering/deep\"],\"probe_repeats\":1,\"probe_concurrency\":1}" \
    -e qualification_ansible=$ANS > /dev/null 2>&1 ); }
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ); watchdog service: $(systemctl --user is-active aihost-worker-watchdog.service)" >> $L
bash harness/pause_reconcile.sh >/dev/null
before=$(wc -l < $EV 2>/dev/null || echo 0)
probe slot-conv-1 conv; cp $OUT/slot-conv-1-load-engineering-deep.json $O/conv-1.json 2>/dev/null
echo "conv 1 (cold): $($PY -c "import json;d=json.load(open('$O/conv-1.json'))['conv'];print({k:d.get(k) for k in ('ttft_seconds','prompt_tokens','cached_prompt_tokens')})" 2>&1)" >> $L
# wait for the service's save of that conversation
t0=$(date +%s); got=0
while [ $(( $(date +%s)-t0 )) -lt 480 ]; do
  tail -n +$((before+1)) $EV 2>/dev/null | grep '"worker": "'$WID'"' | grep -q '"action": "slot_save".*"outcome": "saved"' && { got=1; break; }
  sleep 15
done
echo "service saved worker2 state: $got after $(( $(date +%s)-t0 )) s" >> $L
[ $got = 1 ] || { echo "ABORT: no save observed" >> $L; tail -n +$((before+1)) $EV > $O/service-evidence.jsonl 2>/dev/null; exit 2; }
# wedge worker2 while it serves a DIFFERENT long generation
HOLD=$OUT/wd-hold-load-engineering-deep.json; rm -f $HOLD
( probe wd-hold hold ) &
sleep 15
[ -f $HOLD ] && { echo "ABORT: hold finished early" >> $L; exit 2; }
echo "SIGSTOP $(date -u +%FT%TZ)" >> $L
ssh -o BatchMode=yes $H "cd /; sudo -n -u aihost-runtime podman kill --signal SIGSTOP $CONT" >> $L 2>&1
t0=$(date +%s)
while [ $(( $(date +%s)-t0 )) -lt 900 ]; do
  tail -n +$((before+1)) $EV 2>/dev/null | grep -q '"action": "undrain".*"ok": true' && break
  tail -n +$((before+1)) $EV 2>/dev/null | grep -q '"action": "alert"\|"action": "abandon"' && break
  sleep 15
done
tail -n +$((before+1)) $EV 2>/dev/null > $O/service-evidence.jsonl
sleep 20
probe slot-conv-2 conv; cp $OUT/slot-conv-2-load-engineering-deep.json $O/conv-2.json 2>/dev/null
echo "conv 2 (after restart + restore): $($PY -c "import json;d=json.load(open('$O/conv-2.json'))['conv'];print({k:d.get(k) for k in ('ttft_seconds','prompt_tokens','cached_prompt_tokens')})" 2>&1)" >> $L
echo "units: $(ssh -o BatchMode=yes $H 'systemctl is-active aihost-llama-worker1 aihost-llama-worker2' | tr '\n' ' ')" >> $L
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
