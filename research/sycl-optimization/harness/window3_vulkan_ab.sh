#!/usr/bin/env bash
# Window 3 / backlog 624: Vulkan vs SYCL llama-bench A/B on one B65 (GPU0), same llama.cpp commit (a956a852), the three models.
# SYCL = production image digest; Vulkan = localhost/sycl-research/llama:vulkan-a956a852 (official vulkan.Dockerfile, `full` target).
# Idle gate, worker1 outage, restore trap. Each bench is capped at 20 minutes. Performance only: no accuracy gate for Vulkan here.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3/vulkan; H=10.0.8.5; mkdir -p $O; L=$O/vulkan-ab.log
SYCL=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
VK=localhost/sycl-research/llama:vulkan-a956a852
trap 'bash harness/restore_baseline.sh > '$O'/restore.log 2>&1; echo "RESTORED rc=$?" >> '$L EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
B="-ngl 99 -fa 1 -b 4096 -ub 2048 -p 512,8192 -n 128 -r 2 -o jsonl"
for m in "qwen36 qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf" "coder Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" "flashnext flashnext-gsq-coder/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf"; do
  set -- $m; name=$1; rel=$2
  for eng in sycl vulkan; do
    echo "== $name $eng $(date -u +%FT%TZ)" >> $L
    if [ $eng = sycl ]; then img=$SYCL; envv="GGML_SYCL_ENABLE_XMX_ESIMD=0"; else img=$VK; envv="GGML_VK_VISIBLE_DEVICES=0"; fi
    EXTRA_ENV="$envv" timeout 1200 harness/research_run.sh bench vk-$name-$eng 0 $img $rel -- $B > $O/$name-$eng.jsonl 2> $O/$name-$eng.err
    echo "rc=$? lines=$(wc -l < $O/$name-$eng.jsonl)" >> $L
    sleep 10
  done
done
echo "dmesg timedout: $(ssh -o BatchMode=yes $H 'sudo -n dmesg | grep -ci "timedout job"')" >> $L
