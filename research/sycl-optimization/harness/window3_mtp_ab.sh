#!/usr/bin/env bash
# Window 3 / backlog 617: MTP speculative decoding A/B on GPU0 with the production image/flags, research server :18100 (NOT the gateway).
#   base     deployed Qwen3.6 UD-Q4_K_M, no speculation
#   mtp-off  unsloth MTP GGUF, --spec-type none (control: same weights as the MTP run)
#   mtp-on   unsloth MTP GGUF, --spec-type draft-mtp --spec-draft-n-max 3
# Greedy-equality is checked by comparing per-prompt output hashes. Idle gate, worker1 outage, restore trap.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3; H=10.0.8.5; L=$O/mtp-ab.log
IMG=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
trap 'harness/research_run.sh stop mtp >/dev/null 2>&1; bash harness/restore_baseline.sh > '$O'/mtp-ab-restore.log 2>&1; echo "RESTORED rc=$?" >> '$L EXIT
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
run() { # label model-relpath extra...
  local label=$1 rel=$2; shift 2
  echo "== $label $(date -u +%FT%TZ)" >> $L
  EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh server mtp 0 18100 $IMG -- -m /models/$rel $common "$@" >/dev/null
  local ok=0; for i in $(seq 1 150); do ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:18100/health >/dev/null" && { ok=1; break; }; sleep 4; done
  [ $ok = 1 ] || { echo "$label never healthy" >> $L; harness/research_run.sh stop mtp >/dev/null 2>&1; return; }
  ssh -o BatchMode=yes $H "python3 - 18100" < harness/mtp_ab_client.py >> $L 2>&1
  harness/research_run.sh stop mtp >/dev/null 2>&1; sleep 8
}
run base qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
run mtp-off qwen3.6-35b-a3b-mtp/Qwen3.6-35B-A3B-MTP-UD-Q4_K_M.gguf --spec-type none
run mtp-on qwen3.6-35b-a3b-mtp/Qwen3.6-35B-A3B-MTP-UD-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 3
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
