#!/usr/bin/env bash
# One outage: engx A/B (deployed image vs head-stackB ESIMD=0) for one model on one GPU. Restores production on exit.
# Usage: window2_engx_ab.sh <gpu 0|1> <tag> <model path under models dir> <reasoning budget or empty> [extra server args...]
set -u; cd "$(dirname "$0")/.."; O=evidence/window2; K=evidence/correctness; H=10.0.8.5
GPU="$1"; TAG="$2"; MP="$3"; RB="$4"; shift 4
trap 'bash harness/restore_baseline.sh > '$O'/engx-'$TAG'-restore.log 2>&1; echo RESTORED >> '$O'/engx-'$TAG'.log' EXIT
: > $O/engx-$TAG.log
bash harness/pause_reconcile.sh >/dev/null && ssh -o BatchMode=yes $H "cd /; sudo -n systemctl stop aihost-llama-worker$((GPU+1)).service"
BASE=ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451
for v in deployed stackB; do
  if [ $v = deployed ]; then IMG=$BASE; EE=""; else IMG=localhost/sycl-research/llama:head-stackB; EE="GGML_SYCL_ENABLE_XMX_ESIMD=0"; fi
  L=$TAG-$v
  harness/research_run.sh stop "engx-$L" >/dev/null 2>&1 || true
  EXTRA_ENV="$EE" harness/research_run.sh server "engx-$L" $GPU 18100 "$IMG" -- -m /models/$MP -c 65536 -ngl 99 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics --lazy-mode on "$@"
  ok=0; for i in $(seq 1 120); do ssh -o BatchMode=yes $H 'curl -sf -m3 127.0.0.1:18100/health >/dev/null' && { ok=1; break; }; sleep 5; done
  [ $ok = 1 ] || { echo "$L never healthy" >> $O/engx-$TAG.log; harness/research_run.sh stop "engx-$L"; continue; }
  RBENV=""; [ -n "$RB" ] && RBENV="ENGX_REASONING_BUDGET=$RB"
  ssh -o BatchMode=yes $H "cd ~/sycl-research/engx && mkdir -p ~/sycl-research/evidence/engx-$L && ENGX_CORPUS=base ENGX_REPS=2 $RBENV ENGX_MAX_TOKENS=12288 ENGX_OUT=\$HOME/sycl-research/evidence/engx-$L python3 engx.py run $L http://127.0.0.1:18100 - $TAG 3" > $K/engx-$L.txt 2>&1 || true
  harness/research_run.sh stop "engx-$L"
  echo "$L $(grep '^RESULT' $K/engx-$L.txt | cut -c1-220)" >> $O/engx-$TAG.log
done
