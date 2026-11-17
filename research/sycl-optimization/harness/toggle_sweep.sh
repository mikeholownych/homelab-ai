#!/usr/bin/env bash
# Sweep env toggles on a candidate image at one prompt size. Usage: toggle_sweep.sh <image> <model> <npp> <out> ENV1 ENV2 ...
set -u; cd "$(dirname "$0")/.."
IMG=$1; M=$2; N=$3; OUT=$4; shift 4; : > "$OUT"
for e in "$@"; do
  r=$(EXTRA_ENV="$e" harness/research_run.sh bench sw 0 "$IMG" "$M" -ngl 99 -fa 1 -b 4096 -ub 2048 -p $N -n 0 -r 3 -o jsonl 2>/dev/null | python3 -I -c "
import sys,json
for l in sys.stdin:
    d=json.loads(l); print(round(d['avg_ts'],1),round(d['stddev_ts'],1))")
  echo "$e $r" >> "$OUT"
done
echo DONE >> "$OUT"
