#!/usr/bin/env bash
# Window 3 / backlog "test-backend-ops on a research build with tests enabled (MUL_MAT_ID, flash attention)".
# The test binary is built from the same llama.cpp commit and the same (old-stack) Dockerfile as production with -DLLAMA_BUILD_TESTS=ON,
# copied to /var/lib/aihost-runtime/research/bin, and run INSIDE the deployed image (its libraries, its runtime stack) on GPU0.
# Run 2 excludes f8_e4m3 cases via harness/backend_ops_filter.sh (installed as /tb/run-ops.sh): run 1 aborted in convert.cpp on that type.
# One short worker1 outage; idle gate first; restore_baseline.sh on exit (trap). Not via the gateway (a kernel-level test has no HTTP path).
set -u; cd "$(dirname "$0")/.."; O=evidence/window3; H=10.0.8.5; L=$O/backend-ops.log
LDP=/app:/opt/intel/oneapi/compiler/2026.1/opt/compiler/lib:/opt/intel/oneapi/compiler/2026.1/lib:/opt/intel/oneapi/mkl/2026.1/lib:/opt/intel/oneapi/tcm/1.5/lib:/opt/intel/oneapi/umf/1.1/lib
IMG=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
trap 'bash harness/restore_baseline.sh > '$O'/backend-ops-restore.log 2>&1; echo "RESTORED rc=$?" >> '$L EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
for op in MUL_MAT_ID FLASH_ATTN_EXT MUL_MAT; do
  echo "== $op $(date -u +%FT%TZ)" >> $L
  ssh -o BatchMode=yes $H "cd /; sudo -n systemd-run --quiet --wait --pipe --collect --unit sycl-research-bops -p User=aihost-runtime -p Group=aihost-runtime -p SupplementaryGroups='render video' -p WorkingDirectory=/var/lib/aihost-runtime -p LimitMEMLOCK=infinity -p PrivateTmp=true -p RuntimeMaxSec=1500 /usr/bin/podman run --rm --name sycl-research-bops --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all --group-add keep-groups -e ONEAPI_DEVICE_SELECTOR=level_zero:0,1 -e ZE_AFFINITY_MASK=0 -e GGML_SYCL_ENABLE_XMX_ESIMD=0 -w /app -e LD_LIBRARY_PATH=$LDP -v /dev/dri/by-path:/dev/dri/by-path:ro -v /var/lib/aihost-runtime/research/bin:/tb:ro --entrypoint /bin/sh $IMG /tb/run-ops.sh $op" > $O/backend-ops-$op.txt 2>&1
  echo "rc=$? lines=$(wc -l < $O/backend-ops-$op.txt) ok=$(grep -c 'OK$' $O/backend-ops-$op.txt) fail=$(grep -c -i 'FAIL' $O/backend-ops-$op.txt)" >> $L
  sleep 5
done
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
