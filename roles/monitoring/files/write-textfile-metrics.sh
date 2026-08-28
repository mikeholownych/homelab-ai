#!/bin/sh
# Node-exporter textfile bridge: per-device GPU thermals from hwmon plus
# reconciliation health, and a debounced thermal severity state machine
# (ok/warning/critical) that alerts operators below the benchmark abort
# guardrail. Runs via aihost-metrics.timer.
set -eu

# Installed via copy, so no Jinja markers here: runtime values come from the
# role-templated config file with safe defaults when it is absent.
ENV_FILE="${AIHOST_MONITORING_ENV:-/etc/local-ai/monitoring.env}"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

OUT_DIR="${MONITORING_METRICS_TEXTFILE_DIR:-/var/lib/local-ai/metrics}"
OUT_FILE="$OUT_DIR/gpu.prom"
LOG_DIR="${MONITORING_LOG_DIR:-/var/log/local-ai/monitoring}"
ALERT_LOG_DIR="${MONITORING_ALERT_LOG_DIR:-/var/log/local-ai/alerts}"
STATE_DIR="${MONITORING_GPU_TEMP_STATE_DIR:-/var/lib/local-ai/monitoring}"
WARN_C="${MONITORING_GPU_TEMP_WARN_C:-75}"
CRIT_C="${MONITORING_GPU_TEMP_CRIT_C:-85}"
STATE_FILE="$STATE_DIR/gpu-temp.state"
ALERT_ENV_FILE="/etc/local-ai/alert.env"
# Default hwmon tree; overridable so the script is exercisable without real
# GPU hardware (e.g. a chroot or harness exposing a stub hwmon tree).
HWMON_ROOT="${AIHOST_HWMON_ROOT:-/sys/class/hwmon}"

mkdir -p "$OUT_DIR" "$LOG_DIR" "$ALERT_LOG_DIR" "$STATE_DIR"
TMP="$OUT_FILE.$$"

max_c=""
dev_lines=""

for d in "$HWMON_ROOT"/hwmon*; do
    [ -f "$d/name" ] || continue
    name="$(cat "$d/name")"
    case "$name" in *xe*|*i915*|*gpu*|*drm*)
        for t in "$d"/temp*_input; do
            [ -f "$t" ] || continue
            mv="$(cat "$t")"
            c="$(awk "BEGIN{print $mv/1000}")"
            label="$(printf '%s/%s' "$(basename "$d")" "$name" | tr -c 'A-Za-z0-9_./-' '_')"
            dev_lines="$dev_lines
aihost_gpu_temperature_celsius{device=\"$label\"} $c"
            if [ -z "$max_c" ]; then
                max_c=$c
            else
                max_c="$(awk "BEGIN{print ($c>$max_c)?$c:$max_c}")"
            fi
        done
    ;; esac
done

severity="ok"
if [ -n "$max_c" ] && [ "$(awk "BEGIN{print ($max_c>=$CRIT_C)?1:0}")" = 1 ]; then
    severity="critical"
elif [ -n "$max_c" ] && [ "$(awk "BEGIN{print ($max_c>=$WARN_C)?1:0}")" = 1 ]; then
    severity="warning"
fi

prev=""
if [ -f "$STATE_FILE" ]; then
    prev="$(cat "$STATE_FILE")"
fi
if [ "$severity" != "$prev" ]; then
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ "$severity" = "critical" ]; then
        printf '%s unit=aihost-gpu-thermal state=critical temperature_c=%s\n' "$ts" "$max_c" >>"$ALERT_LOG_DIR/alerts.log"
        if [ -f "$ALERT_ENV_FILE" ]; then
            # shellcheck disable=SC1090
            . "$ALERT_ENV_FILE"
            if [ -n "${AIHOST_ALERT_COMMAND:-}" ]; then
                # Deliberate exec-by-name: no shell interpolation of content.
                # Context carries severity + peak temperature to the operator hook.
                "$AIHOST_ALERT_COMMAND" "aihost-gpu-thermal" "$ts" "state=critical temperature_c=$max_c"
            fi
        fi
    elif [ "$severity" = "warning" ]; then
        printf '%s unit=aihost-gpu-thermal state=warning temperature_c=%s\n' "$ts" "$max_c" >>"$ALERT_LOG_DIR/alerts.log"
    fi
    if [ "$severity" = "ok" ] && [ "$prev" = "critical" ]; then
        printf '%s unit=aihost-gpu-thermal state=recovered temperature_c=%s\n' "$ts" "$max_c" >>"$ALERT_LOG_DIR/alerts.log"
    fi
    printf '%s\n' "$severity" >"$STATE_FILE"
fi

{
    echo "# HELP aihost_gpu_temperature_celsius Per-device GPU temperature in celsius sampled this interval."
    echo "# TYPE aihost_gpu_temperature_celsius gauge"
    if [ -n "$max_c" ]; then
        printf '%s\n' "$dev_lines"
        # Keep the unlabeled aggregate peak for backwards compatibility.
        echo "aihost_gpu_temperature_celsius $max_c"
    fi

    echo "# HELP aihost_gpu_thermal_severity Cross-device peak severity (0=ok, 1=warning, 2=critical) vs monitoring thresholds."
    echo "# TYPE aihost_gpu_thermal_severity gauge"
    case "$severity" in
        ok)       echo "aihost_gpu_thermal_severity 0" ;;
        warning)  echo "aihost_gpu_thermal_severity 1" ;;
        critical) echo "aihost_gpu_thermal_severity 2" ;;
    esac

    echo "# HELP aihost_reconciliation_timer_active Whether aihost-reconcile.timer is enabled+active."
    echo "# TYPE aihost_reconciliation_timer_active gauge"
    if systemctl is-active --quiet aihost-reconcile.timer 2>/dev/null; then
        echo "aihost_reconciliation_timer_active 1"
    else
        echo "aihost_reconciliation_timer_active 0"
    fi
} >"$TMP"

mv "$TMP" "$OUT_FILE"