#!/bin/sh
# Node-exporter textfile bridge: GPU thermals/power from hwmon plus
# reconciliation health. Runs via aihost-metrics.timer.
set -eu

OUT_DIR="{{ monitoring_metrics_textfile_dir }}"
OUT_FILE="$OUT_DIR/gpu.prom"
LOG_DIR="{{ monitoring_log_dir }}"

mkdir -p "$OUT_DIR" "$(dirname "$LOG_DIR")"
TMP="$OUT_FILE.$$"

{
    echo "# HELP aihost_gpu_temperature_celsius Peak GPU temperature sampled this interval."
    echo "# TYPE aihost_gpu_temperature_celsius gauge"
    peak=""
    for d in /sys/class/hwmon/hwmon*; do
        [ -f "$d/name" ] || continue
        name="$(cat "$d/name")"
        case "$name" in *xe*|*i915*|*gpu*|*drm*)
            for t in "$d"/temp*_input; do
                [ -f "$t" ] || continue
                mv=$(cat "$t")
                c="$(awk "BEGIN{print $mv/1000}")"
                [ -z "$peak" ] && peak=$c || peak="$(awk "BEGIN{print ($c>$peak)?$c:$peak}")"
            done
        ;; esac
    done
    if [ -n "$peak" ]; then echo "aihost_gpu_temperature_celsius $peak"; fi

    echo "# HELP aihost_reconciliation_timer_active Whether aihost-reconcile.timer is enabled+active."
    echo "# TYPE aihost_reconciliation_timer_active gauge"
    if systemctl is-active --quiet aihost-reconcile.timer 2>/dev/null; then
        echo "aihost_reconciliation_timer_active 1"
    else
        echo "aihost_reconciliation_timer_active 0"
    fi
} >"$TMP"

mv "$TMP" "$OUT_FILE"
