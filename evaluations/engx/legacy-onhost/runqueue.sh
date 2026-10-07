#!/bin/bash
# usage: runqueue.sh <gpu 0|1> <baseline-label-to-wait-for> <production unit for this gpu> <queue file>
# Waits for this GPU's baseline run to finish, stops the GPU's production worker, then pulls jobs from the shared
# queue (one line each: "label|model path|ENV=V ENV2=V2|extra llama-server args") until it is empty, waiting for each
# model file to finish downloading. Restarts the production worker at the end.
set -u
gpu=$1; baseline=$2; unit=$3; queue=$4
here=$(cd "$(dirname "$0")" && pwd)
log() { echo "== $(date -u +%FT%TZ) gpu$gpu $*"; }

while pgrep -f "engx.py run $baseline " >/dev/null; do sleep 60; done
log "baseline $baseline finished; stopping $unit"
sudo -n systemctl stop "$unit"

while true; do
  job=$(flock "$queue.lock" sh -c 'head -n 1 "$1" && sed -i 1d "$1"' _ "$queue")
  [ -z "$job" ] && break
  IFS='|' read -r label model envs extra <<<"$job"
  last=$model
  if [[ $model == *-00001-of-*.gguf ]]; then n=${model##*-of-}; n=${n%.gguf}; last=${model/-00001-of-/-$n-of-}; fi
  until [ -f "/var/lib/local-ai/models/gguf/$model" ] && [ -f "/var/lib/local-ai/models/gguf/$last" ]; do sleep 60; done
  log "start $label ($model) env=[$envs] extra=[$extra]"
  env ENGX_CORPUS=hard ENGX_REPS=3 ENGX_OUT="$here/results" $envs "$here/cand.sh" "$gpu" "$label" "$model" $extra \
    > "$here/logs/$label.log" 2>&1
  log "end $label: $(grep -h '^RESULT' "$here/logs/$label.log" | cut -c1-160)"
done

log "queue empty; restarting $unit"
sudo -n systemctl start "$unit"
