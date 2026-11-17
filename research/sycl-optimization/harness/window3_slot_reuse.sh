#!/usr/bin/env bash
# Window 3 / backlog 627: slot-reuse split test, Coder-30B (full attention) vs Qwen3.6-35B-A3B (hybrid) on GPU0 with the production image
# and flags, research server on :18100 (NOT via the gateway), same client for both. Idle gate, one worker1 outage, restore trap.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3; H=10.0.8.5; L=$O/slot-reuse.log
IMG=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
trap 'harness/research_run.sh stop sr >/dev/null 2>&1; bash harness/restore_baseline.sh > '$O'/slot-reuse-restore.log 2>&1; echo "RESTORED rc=$?" >> '$L EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
common="-c 65536 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics --lazy-mode on -ngl 99"
for m in "coder30b qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" "qwen36 qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"; do
  set -- $m; tag=$1; rel=$2
  [ "$tag" = coder30b ] && rel=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
  echo "== $tag $(date -u +%FT%TZ)" >> $L
  EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh server sr 0 18100 $IMG -- -m /models/$rel $common >/dev/null
  ok=0; for i in $(seq 1 150); do ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:18100/health >/dev/null" && { ok=1; break; }; sleep 4; done
  [ $ok = 1 ] || { echo "$tag never healthy" >> $L; harness/research_run.sh stop sr >/dev/null 2>&1; continue; }
  ssh -o BatchMode=yes $H "python3 - 18100" < harness/slot_reuse_client.py >> $L 2>&1
  harness/research_run.sh stop sr >/dev/null 2>&1; sleep 8
done
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
