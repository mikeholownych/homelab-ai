#!/usr/bin/env bash
# (Run 2026-11-18: the first version used paths relative to a directory it had cd'd out of, so its re-pin and logging silently did nothing; the
# steps were then run by hand and the paths fixed here.)
# Live validation of the Ansible PLANNED-restart slot save/restore path (roles/llama_cpp_container/tasks/start_worker.yml) on both production workers.
# A real unit change (the --cache-ram pin, main merge of chore/pin-cache-ram) makes the reconcile restart each worker the normal way: drain, wait idle,
# SAVE slot state, stop, start, healthy, RESTORE, undrain. Around it:
#   1. idle gate; one fixed ~16k-token conversation through the gateway to each route (cold TTFT);
#   2. re-pin the controller snapshot to the merged main and run aihost-reconcile.service;
#   3. the same conversation again on each route: if save and restore worked, TTFT is a cache hit instead of a cold prefill;
#   4. the gateway evidence chain's worker_slot_save / worker_slot_restore records for both workers.
set -u; cd "$(dirname "$0")/.."; ROOT=$(cd ../..; pwd); O=$ROOT/research/sycl-optimization/evidence/window3/planned-restart; H=10.0.8.5; mkdir -p $O; L=$O/planned-restart.log
PY=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/python; ANS=/home/mike/.local/share/aihost/reconcile/snapshot/.venv/bin/ansible-playbook; OUT=/home/mike/work/correctness-20261023
: > $L
probe() { # label
  ( cd $ROOT && $ANS -i inventory/production/hosts.yml playbooks/controller_qualification_probe.yml \
    -e "{\"probe_label\":\"$1\",\"probe_mode\":\"conv\",\"probe_models\":[\"engineering/lead\",\"engineering/deep\"],\"probe_repeats\":1,\"probe_concurrency\":1}" \
    -e qualification_ansible=$ANS > /dev/null 2>&1 ); }
show() { for m in lead deep; do echo "$1 $m: $($PY -c "import json;d=json.load(open('$OUT/$2-load-engineering-$m.json'))['conv'];print({k:d.get(k) for k in ('ttft_seconds','prompt_tokens','cached_prompt_tokens')})" 2>&1)" >> $L; cp $OUT/$2-load-engineering-$m.json $O/$2-$m.json 2>/dev/null; done; }
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
slots_before=$(ssh -o BatchMode=yes $H 'sudo -n grep -c worker_slot /var/lib/aihost-gateway/evidence-chain.jsonl' 2>/dev/null || echo 0)
probe plan-conv-1; show "before (cold)" plan-conv-1
echo "re-pin + reconcile $(date -u +%FT%TZ)" >> $L
( cd $ROOT && git fetch -q && git merge -q --ff-only origin/main && $ANS playbooks/reconcile-controller.yml -e reconcile_controller_snapshot_ref=$(git rev-parse HEAD) ) > $O/repin.out 2>&1; echo "repin rc=$?" >> $L
systemctl --user start aihost-reconcile.service; echo "reconcile result: $(systemctl --user show aihost-reconcile.service -p Result --value)" >> $L
echo "workers restarted: $(ssh -o BatchMode=yes $H 'systemctl show aihost-llama-worker1 aihost-llama-worker2 -p ActiveEnterTimestamp --value | tr "\n" " "')" >> $L
sleep 20
probe plan-conv-2; show "after (restored?)" plan-conv-2
ssh -o BatchMode=yes $H 'sudo -n grep worker_slot /var/lib/aihost-gateway/evidence-chain.jsonl | tail -8' 2>/dev/null | python3 -c "
import sys,json
for l in sys.stdin:
    d=json.loads(l); print({k:d.get(k) for k in ('event','worker_id','actor','outcome','tokens','bytes')})" >> $L 2>&1
echo "units: $(ssh -o BatchMode=yes $H 'systemctl is-active aihost-llama-worker1 aihost-llama-worker2 aihost-orchestrator-gateway' | tr '\n' ' ')" >> $L
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
echo "DONE" >> $L
