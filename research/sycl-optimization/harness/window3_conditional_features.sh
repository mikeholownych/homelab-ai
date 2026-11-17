#!/usr/bin/env bash
# Backlog 614 (conditional features), validated on GPU0 with the production image: research servers on :18100, NOT via the gateway; one worker1 outage,
# idle gate, watchdog service and reconcile paused, EXIT trap restores production.
#   A  MoE experts on the CPU with a GPU expert cache (--moe-cache-mib, --moe-cache-cpu-share) vs all-GPU: what an MoE larger than VRAM would cost
#   B  slot-state persistence (--slot-save-path, private 0700 dir): save an ~18k-token conversation, restart the server, restore: TTFT cold vs restored
#   C  router with a model limit (--models-preset, --models-max): swap latency between two models that cannot both stay resident on one card
set -u; cd "$(dirname "$0")/.."; O=evidence/window3/conditional; H=10.0.8.5; mkdir -p $O; L=$O/conditional.log
IMG=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
Q36=/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf; CODER=/models/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
export EXTRA_MOUNTS="-v /var/lib/aihost-runtime/research:/research:rw"
cleanup() {
  harness/research_run.sh stop cf >/dev/null 2>&1
  bash harness/restore_baseline.sh > $O/restore.log 2>&1; echo "RESTORED rc=$?" >> $L
  systemctl --user start aihost-worker-watchdog.service; echo "watchdog: $(systemctl --user is-active aihost-worker-watchdog.service)" >> $L
}
trap cleanup EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
systemctl --user stop aihost-worker-watchdog.service
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 25
ssh -o BatchMode=yes $H 'sudo -n install -d -o aihost-runtime -g aihost-runtime -m 0700 /var/lib/aihost-runtime/research/slots; sudo -n rm -f /var/lib/aihost-runtime/research/slots/*; printf "[qwen36]\nmodel = '$Q36'\n\n[coder]\nmodel = '$CODER'\n" | sudo -n tee /var/lib/aihost-runtime/research/presets.ini >/dev/null; sudo -n chown aihost-runtime:aihost-runtime /var/lib/aihost-runtime/research/presets.ini'
start() { EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh server cf 0 18100 $IMG -- "$@" >/dev/null; }
wait_h() { local t0=$(date +%s); for i in $(seq 1 240); do ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:18100/health >/dev/null" && { echo $(( $(date +%s)-t0 )); return 0; }; sleep 5; done; echo FAIL; return 1; }
stop() { harness/research_run.sh stop cf >/dev/null 2>&1; sleep 20; }
common="-c 16384 --jinja -np 1 -fa on -b 4096 -ub 2048 --lazy-mode on -ngl 99"
# ---- A: MoE expert cache
for cfg in "allgpu|" "cmoe-nocache|-cmoe" "cmoe-cache8g|-cmoe --moe-cache-mib 8192" "cmoe-cache8g-cpu50|-cmoe --moe-cache-mib 8192 --moe-cache-cpu-share 0.5"; do
  name=${cfg%%|*}; extra=${cfg#*|}
  echo "== A $name $(date -u +%FT%TZ)" >> $L
  start -m $Q36 $common $extra; r=$(wait_h); echo "A $name ready_s=$r" >> $L
  if [ "$r" != FAIL ]; then
    ssh -o BatchMode=yes $H "python3 - batch 18100 q 1" < harness/engine_sweep_client.py >> $L 2>&1
    ssh -o BatchMode=yes $H "python3 - longctx 18100 q 4000" < harness/engine_sweep_client.py >> $L 2>&1
  fi
  stop
done
# ---- B: slot persistence across a restart
echo "== B slot persistence $(date -u +%FT%TZ)" >> $L
start -m $Q36 ${common/-c 16384/-c 32768} --slot-save-path /research/slots; r=$(wait_h); echo "B first start ready_s=$r" >> $L
[ "$r" != FAIL ] && ssh -o BatchMode=yes $H "python3 - slot1 18100" < harness/feature_probe_client.py >> $L 2>&1
echo "slots dir: $(ssh -o BatchMode=yes $H 'sudo -n ls -la /var/lib/aihost-runtime/research/slots | tail -2 | cut -c1-80' | tr '\n' ';')" >> $L
stop
start -m $Q36 ${common/-c 16384/-c 32768} --slot-save-path /research/slots; r=$(wait_h); echo "B restart ready_s=$r" >> $L
[ "$r" != FAIL ] && ssh -o BatchMode=yes $H "python3 - slot2 18100" < harness/feature_probe_client.py >> $L 2>&1
stop
# ---- C: router with a model limit
for max in 1 2; do
  echo "== C router models-max=$max $(date -u +%FT%TZ)" >> $L
  start --models-preset /research/presets.ini --models-max $max --models-memory-margin 2048 -c 8192 -np 1 -fa on --jinja --lazy-mode on -ngl 99; r=$(wait_h); echo "C max=$max router ready_s=$r" >> $L
  [ "$r" != FAIL ] && timeout 1500 ssh -o BatchMode=yes $H "python3 - router 18100 qwen36 coder qwen36 coder" < harness/feature_probe_client.py >> $L 2>&1
  ssh -o BatchMode=yes $H "sudo -n journalctl -u sycl-research-cf.service --no-pager -n 150" | sed 's/\x1b\[[0-9;]*m//g' | grep -i -E 'load|unload|evict|margin|model|fit|free|memory' | tail -40 > $O/router-max$max.logtail
  stop
done
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
