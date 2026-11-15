#!/bin/sh
# Run each phase's tests in its own interpreter with an import path that puts that phase's own sources first:
#   [phaseN/src, phaseN-1/src, ... phase0/src, repo root]
# The phase*/src/autonomous_engineering packages are merged with pkgutil.extend_path and many modules exist in
# several phases, so on a single shared path the first entry wins for every phase. Isolating them means a phase's
# tests always exercise that phase's own copy. Sealed phase sources are not edited.
#
# Usage: scripts/run-phase-tests.sh [phase-number ...]     (default: every phase)
#        PHASE_TEST_PYTHON=/path/to/python scripts/run-phase-tests.sh 12 13
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PHASE_TEST_PYTHON:-$ROOT/.venv/bin/python}
if [ "$#" -gt 0 ]; then
  phases="$*"
else
  phases=$(find "$ROOT" -maxdepth 1 -type d -name 'phase[0-9]*' | sed 's|.*/phase||' | sort -n | tr '\n' ' ')
fi
cd "$ROOT" || exit 2
failed=""
for n in $phases; do
  [ -d "$ROOT/phase$n" ] || { echo "no such phase: $n" >&2; exit 2; }
  path=""
  i=$n
  while [ "$i" -ge 0 ]; do
    [ -d "$ROOT/phase$i/src" ] && path="$path:$ROOT/phase$i/src"
    i=$((i - 1))
  done
  echo "== phase$n (import path: phase$n/src first) =="
  # The path goes through pytest's own pythonpath option, NOT the PYTHONPATH environment variable: several phase
  # tests copy the repo into a sandbox and run a child interpreter, which must not inherit this process's path.
  pythonpath=$(printf '%s' "${path#:}" | tr ':' ' ')
  PYTHONHASHSEED=0 PY_COLORS=0 \
    "$PY" -m pytest -q -o "pythonpath=$pythonpath $ROOT" -p no:cacheprovider "phase$n" || failed="$failed phase$n"
done
if [ -n "$failed" ]; then
  echo "FAILED:$failed" >&2
  exit 1
fi
echo "all phases passed"
