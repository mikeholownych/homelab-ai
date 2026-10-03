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
# A sensor that publishes its own kernel limit (hwmon tempN_crit) is judged against
# min(configured threshold, limit - margin): the kernel limit can only make alerting stricter,
# never looser, so alerts keep firing below the benchmark abort guardrail.
WARN_MARGIN_C="${MONITORING_GPU_TEMP_WARN_MARGIN_C:-25}"
CRIT_MARGIN_C="${MONITORING_GPU_TEMP_CRIT_MARGIN_C:-15}"
STATE_FILE="$STATE_DIR/gpu-temp.state"
ALERT_ENV_FILE="/etc/local-ai/alert.env"
# Default hwmon tree; overridable so the script is exercisable without real
# GPU hardware (e.g. a chroot or harness exposing a stub hwmon tree).
HWMON_ROOT="${AIHOST_HWMON_ROOT:-/sys/class/hwmon}"

mkdir -p "$OUT_DIR" "$LOG_DIR" "$ALERT_LOG_DIR" "$STATE_DIR"
TMP="$OUT_FILE.$$"

PCI_ROOT="${AIHOST_PCI_ROOT:-/sys/bus/pci/devices}"

# Prometheus label values must be plain and stable: keep [A-Za-z0-9_./:-] only.
lbl() { printf '%s' "$1" | tr -c 'A-Za-z0-9_./:-' '_'; }

max_c=""
sev=0
trigger=""
limit_lines=""
temp_lines=""
gpu_max_lines=""
info_lines=""
energy_lines=""
cap_lines=""
fan_lines=""
idle_lines=""
freq_lines=""

# One entry per xe GPU, ordered by PCI address so the `gpu` ordinal is stable across reboots (hwmonN is not).
gpus="$(for d in "$HWMON_ROOT"/hwmon*; do
    [ -f "$d/name" ] || continue
    case "$(cat "$d/name")" in xe|i915)
        bdf="$(basename "$(readlink -f "$d/device" 2>/dev/null)" 2>/dev/null || true)"
        [ -n "$bdf" ] && printf '%s %s\n' "$bdf" "$d"
    ;; esac
done | sort)"

ord=0
while read -r bdf d; do
    [ -n "$bdf" ] || continue
    drv="$(cat "$d/name")"
    info_lines="$info_lines
aihost_gpu_info{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\",driver=\"$drv\"} 1"
    gpu_max=""
    for t in "$d"/temp*_input; do
        [ -f "$t" ] || continue
        base="${t%_input}"
        sensor="temp$(basename "$base" | sed 's/^temp//')"
        [ -f "${base}_label" ] && sensor="$(cat "${base}_label")"
        c="$(awk "BEGIN{print $(cat "$t")/1000}")"
        temp_lines="$temp_lines
aihost_gpu_temperature_celsius{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\",sensor=\"$(lbl "$sensor")\"} $c"
        gpu_max="$(awk -v a="${gpu_max:-$c}" -v b="$c" 'BEGIN{print (b>a)?b:a}')"
        w="$WARN_C"; k="$CRIT_C"
        if [ -f "${base}_crit" ]; then
            lim="$(awk "BEGIN{print $(cat "${base}_crit")/1000}")"
            limit_lines="$limit_lines
aihost_gpu_temperature_limit_celsius{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\",sensor=\"$(lbl "$sensor")\"} $lim"
            w="$(awk -v a="$WARN_C" -v l="$lim" -v m="$WARN_MARGIN_C" 'BEGIN{x=l-m; print (x<a)?x:a}')"
            k="$(awk -v a="$CRIT_C" -v l="$lim" -v m="$CRIT_MARGIN_C" 'BEGIN{x=l-m; print (x<a)?x:a}')"
        fi
        level="$(awk -v c="$c" -v w="$w" -v k="$k" 'BEGIN{print (c>=k)?2:((c>=w)?1:0)}')"
        if [ "$level" -gt "$sev" ]; then
            sev="$level"
            trigger="gpu$ord/$(lbl "$sensor")"
        fi
    done
    if [ -n "$gpu_max" ]; then
        gpu_max_lines="$gpu_max_lines
aihost_gpu_temperature_max_celsius{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\"} $gpu_max"
        max_c="$(awk -v a="${max_c:-$gpu_max}" -v b="$gpu_max" 'BEGIN{print (b>a)?b:a}')"
    fi
    # Cumulative energy (microjoules -> joules): rate() of it is the real average power.
    for e in "$d"/energy*_input; do
        [ -f "$e" ] || continue
        base="${e%_input}"; dom="$(basename "$base")"
        [ -f "${base}_label" ] && dom="$(cat "${base}_label")"
        energy_lines="$energy_lines
aihost_gpu_energy_joules_total{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\",domain=\"$(lbl "$dom")\"} $(awk "BEGIN{printf \"%.6f\", $(cat "$e")/1000000}")"
    done
    if [ -f "$d/power1_cap" ]; then
        cap_lines="$cap_lines
aihost_gpu_power_cap_watts{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\"} $(awk "BEGIN{print $(cat "$d/power1_cap")/1000000}")"
    fi
    if [ -f "$d/fan1_input" ]; then
        fan_lines="$fan_lines
aihost_gpu_fan_speed_rpm{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\"} $(cat "$d/fan1_input")"
    fi
    # Xe GT activity: time spent in RC6 idle (ms -> s) is a counter, so 1 - rate(idle_seconds) is utilisation.
    for gt in "$PCI_ROOT/$bdf"/tile0/gt*; do
        [ -f "$gt/gtidle/idle_residency_ms" ] || continue
        gtn="$(basename "$gt")"
        idle_lines="$idle_lines
aihost_gpu_gt_idle_residency_seconds_total{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\",gt=\"$(lbl "$gtn")\"} $(awk "BEGIN{printf \"%.3f\", $(cat "$gt/gtidle/idle_residency_ms")/1000}")"
        if [ -f "$gt/freq0/act_freq" ]; then
            freq_lines="$freq_lines
aihost_gpu_actual_frequency_hertz{gpu=\"$ord\",bdf=\"$(lbl "$bdf")\",gt=\"$(lbl "$gtn")\"} $(awk "BEGIN{print $(cat "$gt/freq0/act_freq")*1000000}")"
        fi
    done
    ord=$((ord + 1))
done <<EOF_GPUS
$gpus
EOF_GPUS

case "$sev" in
    2) severity="critical" ;;
    1) severity="warning" ;;
    *) severity="ok" ;;
esac

prev=""
if [ -f "$STATE_FILE" ]; then
    prev="$(cat "$STATE_FILE")"
fi
if [ "$severity" != "$prev" ]; then
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ "$severity" = "critical" ]; then
        printf '%s unit=aihost-gpu-thermal state=critical temperature_c=%s sensor=%s\n' "$ts" "$max_c" "$trigger" >>"$ALERT_LOG_DIR/alerts.log"
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
        printf '%s unit=aihost-gpu-thermal state=warning temperature_c=%s sensor=%s\n' "$ts" "$max_c" "$trigger" >>"$ALERT_LOG_DIR/alerts.log"
    fi
    if [ "$severity" = "ok" ] && [ "$prev" = "critical" ]; then
        printf '%s unit=aihost-gpu-thermal state=recovered temperature_c=%s\n' "$ts" "$max_c" >>"$ALERT_LOG_DIR/alerts.log"
    fi
    printf '%s\n' "$severity" >"$STATE_FILE"
fi

family() { # family <name> <type> <help> <lines>: a family is emitted only when it has samples
    [ -n "$4" ] || return 0
    echo "# HELP $1 $3"
    echo "# TYPE $1 $2"
    printf '%s\n' "$4" | sed '/^$/d'
}

{
    family aihost_gpu_info gauge "GPU identity; gpu is the ordinal by PCI address, bdf the stable PCI address." "$info_lines"
    family aihost_gpu_temperature_celsius gauge "Temperature of one GPU sensor (pkg, vram, per-channel vram, ...) in celsius." "$temp_lines"
    family aihost_gpu_temperature_limit_celsius gauge "Kernel-reported critical limit of one GPU sensor in celsius; limit minus temperature is the headroom." "$limit_lines"
    family aihost_gpu_temperature_max_celsius gauge "Hottest sensor on each GPU in celsius; the thermal alert thresholds apply to this." "$gpu_max_lines"
    family aihost_gpu_energy_joules_total counter "Cumulative energy drawn by a GPU power domain in joules; rate() gives watts." "$energy_lines"
    family aihost_gpu_power_cap_watts gauge "Configured GPU power cap in watts." "$cap_lines"
    family aihost_gpu_fan_speed_rpm gauge "GPU fan speed in revolutions per minute." "$fan_lines"
    family aihost_gpu_gt_idle_residency_seconds_total counter "Cumulative seconds a GPU graphics tile spent in RC6 idle; 1 - rate() is utilisation." "$idle_lines"
    family aihost_gpu_actual_frequency_hertz gauge "Actual graphics tile frequency in hertz." "$freq_lines"

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

    echo "# HELP aihost_metrics_last_success_timestamp_seconds Unix time this file was last written; alert when it stops advancing."
    echo "# TYPE aihost_metrics_last_success_timestamp_seconds gauge"
    echo "aihost_metrics_last_success_timestamp_seconds $(date +%s)"
} >"$TMP"

mv "$TMP" "$OUT_FILE"