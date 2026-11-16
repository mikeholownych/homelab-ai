#!/usr/bin/env bash
# One short GPU0 outage: failure injection on a research server (head-stackB, ESIMD=0, Qwen3.6, production flags), NOT via the gateway:
# (1) client abort mid-stream then a follow-up request, (2) two concurrent requests with -np 1, (3) hard kill mid-request then restart.
# Restores production on exit.
set -u; cd "$(dirname "$0")/.."; O=evidence/window2; H=10.0.8.5
trap 'harness/research_run.sh stop fi >/dev/null 2>&1; bash harness/restore_baseline.sh > '$O'/fi-restore.log 2>&1; echo RESTORED >> '$O'/fi.log' EXIT
: > $O/fi.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
IMG=localhost/sycl-research/llama:head-stackB
start() { harness/research_run.sh stop fi >/dev/null 2>&1; EXTRA_ENV="GGML_SYCL_ENABLE_XMX_ESIMD=0" harness/research_run.sh server fi 0 18100 $IMG -- -m /models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf -c 65536 --reasoning-budget 8192 -ngl 99 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics --lazy-mode on >/dev/null
  for i in $(seq 1 120); do ssh -o BatchMode=yes $H 'curl -sf -m3 127.0.0.1:18100/health >/dev/null' && return 0; sleep 5; done; return 1; }
req() { echo "curl -s -m $2 127.0.0.1:18100/v1/chat/completions -H 'content-type: application/json' -d '{\"messages\":[{\"role\":\"user\",\"content\":\"$1\"}],\"max_tokens\":$3,\"stream\":${4:-false}}'"; }
ok() { ssh -o BatchMode=yes $H "$(req 'Say OK.' 120 16)" | grep -c '"choices"'; }
start && echo "start: healthy" >> $O/fi.log || { echo "start: FAILED" >> $O/fi.log; exit 1; }
echo "baseline request ok=$(ok)" >> $O/fi.log
# (1) client abort mid-stream
ssh -o BatchMode=yes $H "$(req 'Write a very long story about a lighthouse.' 6 2000 true)" >/dev/null 2>&1
sleep 5
echo "after client abort: health=$(ssh -o BatchMode=yes $H 'curl -s -m5 127.0.0.1:18100/health') follow-up ok=$(ok)" >> $O/fi.log
# (2) two concurrent requests, -np 1
ssh -o BatchMode=yes $H "( $(req 'Count from 1 to 40, one per line.' 300 300) | grep -c choices > /tmp/fi_a & $(req 'Name 30 fruits, one per line.' 300 300) | grep -c choices > /tmp/fi_b & wait ); echo a=\$(cat /tmp/fi_a) b=\$(cat /tmp/fi_b); rm -f /tmp/fi_a /tmp/fi_b" >> $O/fi.log 2>&1
sed -i '$ s/^/concurrent(2 req, np1): /' $O/fi.log
# (3) hard kill mid-request, then restart
ssh -o BatchMode=yes $H "$(req 'Write a very long story about a lighthouse.' 30 2000)" > /dev/null 2>&1 &
sleep 8; ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl kill -s SIGKILL sycl-research-fi.service 2>/dev/null; true'
wait; sleep 3
echo "after hard kill: unit=$(ssh -o BatchMode=yes $H 'systemctl is-active sycl-research-fi.service' 2>&1 | head -1)" >> $O/fi.log
start && echo "restart after kill: healthy, request ok=$(ok)" >> $O/fi.log || echo "restart after kill: FAILED" >> $O/fi.log
echo "kernel xe timeouts since test start: $(ssh -o BatchMode=yes $H 'cd /; sudo -n dmesg -T | grep -c "Timedout job"') (baseline 32)" >> $O/fi.log
