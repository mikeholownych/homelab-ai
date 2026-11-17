#!/usr/bin/env bash
# Window 3 / backlog "model load/reload under failure, default mmap vs --no-mmap". One GPU0 outage (worker1), research server on :18100,
# NOT via the gateway. Waits for an idle gateway first, restores production on exit (trap), writes evidence/window3/load.log.
# Cases per mode (load modes none and dio; run 1 covered default mmap): A clean load; B SIGKILL ~10 s into the load then reload; C second server on the busy GPU
# (collision) must fail cleanly, then the first stays healthy.
set -u; cd "$(dirname "$0")/.."; O=evidence/window3; H=10.0.8.5; L=$O/load.log
IMG=localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
MODEL=/models/qwen3.6-35b-a3b/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
trap 'harness/research_run.sh stop lf >/dev/null 2>&1; harness/research_run.sh stop lf2 >/dev/null 2>&1; bash harness/restore_baseline.sh > '$O'/load-restore.log 2>&1; echo "RESTORED rc=$?" >> '$L EXIT
: > $L
for i in $(seq 1 120); do
  n=$(ssh -o BatchMode=yes $H 'journalctl -u aihost-llama-worker1 -u aihost-llama-worker2 --since "-6 min" --no-pager | grep -cE "print_timing|launch_slot|slot update"')
  [ "$n" = 0 ] && break; sleep 60
done
[ "$n" = 0 ] || { echo "never idle" >> $L; exit 1; }
echo "idle confirmed $(date -u +%FT%TZ)" >> $L
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl stop aihost-llama-worker1.service'
sleep 20
ENVV="GGML_SYCL_ENABLE_XMX_ESIMD=0"
common="-m $MODEL -c 65536 --reasoning-budget 8192 -ngl 99 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics --lazy-mode on"
start() { # tag port extra-args...
  local tag=$1 port=$2; shift 2
  EXTRA_ENV="$ENVV" harness/research_run.sh server $tag 0 $port $IMG -- $common "$@" >/dev/null; }
wait_h() { local port=$1 t0=$(date +%s); for i in $(seq 1 150); do ssh -o BatchMode=yes $H "curl -sf -m3 127.0.0.1:$port/health >/dev/null" && { echo $(( $(date +%s)-t0 )); return 0; }; sleep 4; done; echo FAIL; return 1; }
req_ok() { ssh -o BatchMode=yes $H "curl -s -m 120 127.0.0.1:$1/v1/chat/completions -H 'content-type: application/json' -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Say OK.\"}],\"max_tokens\":16}'" | grep -c '"choices"'; }
rss() { ssh -o BatchMode=yes $H 'free -m | awk "/Mem:/{print \"used_mb=\"\$3\" avail_mb=\"\$7}"'; }
for mode in none dio; do
  extra="-lm $mode"
  harness/research_run.sh stop lf >/dev/null 2>&1; sleep 5
  echo "== $mode A clean load" >> $L
  start lf 18100 $extra; r=$(wait_h 18100); echo "A $mode load_s=$r request_ok=$(req_ok 18100) $(rss)" >> $L
  echo "== $mode C collision: second server on same GPU" >> $L
  start lf2 18101 $extra; r2=$(wait_h 18101)
  echo "C $mode second_load=$r2 first_health=$(ssh -o BatchMode=yes $H 'curl -s -m5 127.0.0.1:18100/health') first_request_ok=$(req_ok 18100) second_unit=$(ssh -o BatchMode=yes $H 'systemctl is-active sycl-research-lf2.service' 2>&1|head -1)" >> $L
  harness/research_run.sh stop lf2 >/dev/null 2>&1; harness/research_run.sh stop lf >/dev/null 2>&1; sleep 8
  echo "== $mode B SIGKILL mid-load then reload" >> $L
  start lf 18100 $extra; sleep 10
  ssh -o BatchMode=yes $H 'cd /; sudo -n systemctl kill -s SIGKILL sycl-research-lf.service 2>/dev/null; true'; sleep 5
  echo "B $mode after_kill_unit=$(ssh -o BatchMode=yes $H 'systemctl is-active sycl-research-lf.service' 2>&1|head -1) $(rss)" >> $L
  harness/research_run.sh stop lf >/dev/null 2>&1; sleep 5
  start lf 18100 $extra; r=$(wait_h 18100); echo "B $mode reload_s=$r request_ok=$(req_ok 18100) $(rss)" >> $L
  echo "kernel xe timeouts: $(ssh -o BatchMode=yes $H 'cd /; sudo -n dmesg -T | grep -c "Timedout job"') (baseline 32)" >> $L
done
