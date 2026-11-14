#!/usr/bin/env bash
# Pause the hourly aihost-reconcile timer (workstation user timer) so it does not restart stopped research workers.
# It re-asserts production state (starts workers). Undo with harness/restore_baseline.sh (re-enables the timer).
set -euo pipefail
systemctl --user stop aihost-reconcile.timer
systemctl --user is-active aihost-reconcile.timer || echo "reconcile timer paused"
