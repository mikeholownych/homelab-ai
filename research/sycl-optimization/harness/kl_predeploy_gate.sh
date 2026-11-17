#!/usr/bin/env bash
# Pre-deploy accuracy gate: compare a candidate image's KL divergence (vs CPU ground-truth logits) with the deployed image's.
#   kl_predeploy_gate.sh compare <deployed-score.txt> <candidate-score.txt>   # parse + verdict only (no GPU, safe anywhere)
#   kl_predeploy_gate.sh run <deployed-image> <candidate-image> [chunks]      # needs a free GPU: follow the research window rules
# Verdict: FAIL on any NaN/inf, mean KLD > deployed*(1+TOL) + ABS, or "Same top p" lower by more than TOP_P_DROP points.
# Defaults: TOL=0.25 (relative), ABS=0.0005, TOP_P_DROP=0.5. Exit 0 = pass, 1 = fail, 2 = unparsable input.
set -euo pipefail
TOL="${TOL:-0.25}"; ABS="${ABS:-0.0005}"; TOP_P_DROP="${TOP_P_DROP:-0.5}"
field() { sed -n "s/^$2[^:]*:[[:space:]]*\([-0-9.]*\).*/\1/p" "$1" | head -1; }
compare() {
  local d="$1" c="$2" dk ck dp cp
  if grep -qiE '\b(nan|inf)\b' "$c"; then echo "FAIL: NaN/inf in candidate output"; return 1; fi
  dk=$(field "$d" 'Mean    KLD'); ck=$(field "$c" 'Mean    KLD')
  dp=$(sed -n 's/^Same top p: *\([0-9.]*\).*/\1/p' "$d" | head -1); cp=$(sed -n 's/^Same top p: *\([0-9.]*\).*/\1/p' "$c" | head -1)
  [ -n "$dk" ] && [ -n "$ck" ] && [ -n "$dp" ] && [ -n "$cp" ] || { echo "unparsable score files"; return 2; }
  echo "mean KLD deployed=$dk candidate=$ck ; same-top-p deployed=$dp candidate=$cp"
  awk -v dk="$dk" -v ck="$ck" -v dp="$dp" -v cp="$cp" -v t="$TOL" -v a="$ABS" -v p="$TOP_P_DROP" 'BEGIN{
    ok=1; if (ck > dk*(1+t)+a) {print "FAIL: mean KLD regressed"; ok=0}
    if (cp < dp-p) {print "FAIL: same-top-p dropped"; ok=0}
    if (ok) print "PASS"; exit ok?0:1 }'
}
case "${1:-}" in
  compare) compare "$2" "$3";;
  run)
    DEP="$2"; CAND="$3"; CH="${4:-3}"; cd "$(dirname "$0")/.."
    TAG="-gate$(date -u +%Y%m%d%H%M)"; O="evidence/correctness/gate$TAG"
    # kl_cpu_reference.sh scores BASE (hardcoded original) and the candidate; here the deployed image is scored as the candidate-1 run.
    sed "s#^BASE=.*#BASE=$DEP#" harness/kl_cpu_reference.sh > "/tmp/kl_ref_$$.sh"
    cp "/tmp/kl_ref_$$.sh" harness/.kl_ref_tmp.sh; chmod +x harness/.kl_ref_tmp.sh
    OUT="$O" TAG="$TAG" harness/.kl_ref_tmp.sh "$CAND" "$CH"; rm -f harness/.kl_ref_tmp.sh "/tmp/kl_ref_$$.sh"
    compare "$O/cpu-score-base$TAG.txt" "$O/cpu-score-head$TAG.txt";;
  *) sed -n 2,6p "$0"; exit 2;;
esac
