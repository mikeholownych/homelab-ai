"""The host textfile exporter must emit valid, unambiguous Prometheus exposition for a real-looking GPU tree."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.test_orchestrator_metrics_contract import validate_exposition

SCRIPT = Path(__file__).resolve().parents[1] / "roles/monitoring/files/write-textfile-metrics.sh"


def _gpu(root: Path, pci: Path, hwmon: str, bdf: str, temps: dict[str, int], energy_uj: int, idle_ms: int, mhz: int,
         limits: dict[str, int] | None = None):
    dev = pci / bdf
    (dev / "tile0/gt0/gtidle").mkdir(parents=True)
    (dev / "tile0/gt0/gtidle/idle_residency_ms").write_text(f"{idle_ms}\n")
    (dev / "tile0/gt0/freq0").mkdir(parents=True)
    (dev / "tile0/gt0/freq0/act_freq").write_text(f"{mhz}\n")
    h = root / hwmon
    h.mkdir(parents=True)
    (h / "name").write_text("xe\n")
    (h / "device").symlink_to(dev)
    for n, (label, milli) in enumerate(temps.items(), start=1):
        (h / f"temp{n}_input").write_text(f"{milli}\n")
        (h / f"temp{n}_label").write_text(f"{label}\n")
        if limits and label in limits:
            (h / f"temp{n}_crit").write_text(f"{limits[label]}\n")
    (h / "energy1_input").write_text(f"{energy_uj}\n")
    (h / "energy1_label").write_text("card\n")
    (h / "power1_cap").write_text("150000000\n")
    (h / "fan1_input").write_text("0\n")


def _run(tmp_path: Path, warn="75", crit="85", hot: dict[str, int] | None = None, limits: dict[str, int] | None = None) -> str:
    hw, pci = tmp_path / "hwmon", tmp_path / "pci"
    # hwmon numbering deliberately reversed relative to PCI order: the gpu ordinal must follow the PCI address.
    _gpu(hw, pci, "hwmon4", "0000:93:00.0", {"pkg": 38000, "vram": 40000, "vram_ch_0": 36000, **(hot or {})}, 2_000_000, 1000, 1200, limits)
    _gpu(hw, pci, "hwmon3", "0000:51:00.0", {"pkg": 30000, "vram": 32000, "vram_ch_0": 31000}, 12_345_678, 3504771, 2400, limits)
    out = tmp_path / "out"
    env_file = tmp_path / "monitoring.env"
    env_file.write_text(f"MONITORING_METRICS_TEXTFILE_DIR={out}\nMONITORING_LOG_DIR={tmp_path}/log\nMONITORING_ALERT_LOG_DIR={tmp_path}/alerts\n"
                        f"MONITORING_GPU_TEMP_STATE_DIR={tmp_path}/state\nMONITORING_GPU_TEMP_WARN_C={warn}\nMONITORING_GPU_TEMP_CRIT_C={crit}\n")
    env = {**os.environ, "AIHOST_MONITORING_ENV": str(env_file), "AIHOST_HWMON_ROOT": str(hw), "AIHOST_PCI_ROOT": str(pci)}
    subprocess.run(["sh", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
    return (out / "gpu.prom").read_text()


def test_output_is_valid_exposition_with_unique_unambiguous_series(tmp_path):
    types = validate_exposition(_run(tmp_path))
    assert types["aihost_gpu_energy_joules_total"] == "counter"
    assert types["aihost_gpu_gt_idle_residency_seconds_total"] == "counter"
    assert types["aihost_gpu_temperature_celsius"] == "gauge"


def test_gpu_ordinal_follows_pci_address_not_hwmon_number_and_sensors_are_distinct(tmp_path):
    text = _run(tmp_path)
    assert 'aihost_gpu_temperature_celsius{gpu="0",bdf="0000:51:00.0",sensor="pkg"} 30' in text
    assert 'aihost_gpu_temperature_celsius{gpu="1",bdf="0000:93:00.0",sensor="vram"} 40' in text
    assert 'aihost_gpu_info{gpu="0",bdf="0000:51:00.0",driver="xe"} 1' in text
    assert 'aihost_gpu_temperature_max_celsius{gpu="1",bdf="0000:93:00.0"} 40' in text
    assert "hwmon" not in text, "unstable hwmonN names must not leak into labels"


def test_counters_carry_exact_kernel_values_in_base_units(tmp_path):
    text = _run(tmp_path)
    assert 'aihost_gpu_energy_joules_total{gpu="0",bdf="0000:51:00.0",domain="card"} 12.345678' in text   # microjoules -> joules
    assert 'aihost_gpu_gt_idle_residency_seconds_total{gpu="0",bdf="0000:51:00.0",gt="gt0"} 3504.771' in text   # ms -> s
    assert 'aihost_gpu_actual_frequency_hertz{gpu="0",bdf="0000:51:00.0",gt="gt0"} 2400000000' in text
    assert 'aihost_gpu_power_cap_watts{gpu="0",bdf="0000:51:00.0"} 150' in text


def test_the_hottest_sensor_still_drives_the_thermal_severity(tmp_path):
    assert "aihost_gpu_thermal_severity 0" in _run(tmp_path)
    warm = tmp_path / "warm"
    warm.mkdir()
    assert "aihost_gpu_thermal_severity 1" in _run(warm, warn="39", crit="85")      # hottest sensor is 40 C


def test_freshness_timestamp_is_present_and_a_missing_gpu_tree_yields_valid_output(tmp_path):
    text = _run(tmp_path)
    assert "aihost_metrics_last_success_timestamp_seconds " in text
    empty = tmp_path / "none"
    empty.mkdir()
    out = tmp_path / "o2"
    env_file = tmp_path / "m2.env"
    env_file.write_text(f"MONITORING_METRICS_TEXTFILE_DIR={out}\nMONITORING_LOG_DIR={tmp_path}/l2\nMONITORING_ALERT_LOG_DIR={tmp_path}/a2\nMONITORING_GPU_TEMP_STATE_DIR={tmp_path}/s2\n")
    subprocess.run(["sh", str(SCRIPT)], check=True, capture_output=True, text=True,
                   env={**os.environ, "AIHOST_MONITORING_ENV": str(env_file), "AIHOST_HWMON_ROOT": str(empty), "AIHOST_PCI_ROOT": str(empty)})
    validate_exposition((out / "gpu.prom").read_text())


REAL_LIMITS = {"pkg": 100_000, "vram": 105_000, "vram_ch_0": 105_000}      # what the Xe hwmon reports on this host


def test_kernel_limits_are_exported_for_headroom_dashboards(tmp_path):
    text = _run(tmp_path, limits=REAL_LIMITS)
    validate_exposition(text)
    assert 'aihost_gpu_temperature_limit_celsius{gpu="0",bdf="0000:51:00.0",sensor="pkg"} 100' in text
    assert 'aihost_gpu_temperature_limit_celsius{gpu="1",bdf="0000:93:00.0",sensor="vram"} 105' in text


def test_a_kernel_limit_can_never_loosen_the_configured_thresholds(tmp_path):
    # vram limit 105 gives a derived 80/90, but the configured 75/85 is stricter and must win:
    # alerts keep firing below the 90 C benchmark abort guardrail.
    assert "aihost_gpu_thermal_severity 1" in _run(tmp_path / "a", hot={"vram": 78_000}, limits=REAL_LIMITS)
    assert "aihost_gpu_thermal_severity 2" in _run(tmp_path / "b", hot={"vram": 86_000}, limits=REAL_LIMITS)
    assert "aihost_gpu_thermal_severity 0" in _run(tmp_path / "c", hot={"vram": 70_000}, limits=REAL_LIMITS)


def test_a_lower_kernel_limit_tightens_the_alert_for_that_sensor_only(tmp_path):
    # Limit 60 C -> effective warn min(75, 35)=35 and critical min(85, 45)=45: 50 C is critical for this
    # sensor even though the global thresholds would call it fine.
    text = _run(tmp_path, hot={"pkg": 50_000}, limits={"pkg": 60_000})
    assert "aihost_gpu_thermal_severity 2" in text
    assert "aihost_gpu_thermal_severity 0" in _run(tmp_path / "other", hot={"pkg": 50_000})        # no limit -> global thresholds


def test_the_alert_log_names_the_sensor_that_set_the_severity(tmp_path):
    _run(tmp_path, hot={"vram": 90_000}, limits=REAL_LIMITS)
    log = (tmp_path / "alerts" / "alerts.log").read_text()
    assert "state=critical" in log and "sensor=gpu1/vram" in log, log


def _worker(proc: Path, pid: int, comm: str, port: str, majflt: int, rss_file_kb: int, model: bytes) -> None:
    p = proc / str(pid)
    (p / "root/models/m").mkdir(parents=True)
    (p / "root/models/m/weights-00001-of-00002.gguf").write_bytes(model)
    (p / "comm").write_text(f"{comm}\n")
    (p / "cmdline").write_bytes(b"\0".join([b"/app/llama-server", b"-m", b"/models/m/weights-00001-of-00002.gguf",
                                            b"--port", port.encode(), b"--metrics"]) + b"\0")
    # comm in parentheses may contain spaces; majflt is field 12 of the whole line.
    (p / "stat").write_text(f"{pid} ({comm}) S 1 1 1 0 -1 4194560 15224766 0 {majflt} 0 5 6 0 0 20 0 9 0 100 0 0\n")
    (p / "status").write_text(f"Name:\t{comm}\nVmRSS:\t{rss_file_kb * 3} kB\nRssAnon:\t{rss_file_kb * 2} kB\nRssFile:\t{rss_file_kb} kB\n")
    (p / "maps").write_text("7f00-7f10 r--s 00000000 00:2a 77 /models/m/weights-00001-of-00002.gguf\n"
                            "7f10-7f20 r--s 00001000 00:2a 77 /models/m/weights-00001-of-00002.gguf\n"
                            "7f20-7f30 r-xp 00000000 00:2a 78 /opt/intel/lib/libintlc.so.5\n")


def test_llama_workers_report_faults_residency_and_page_cache_of_mapped_weights(tmp_path):
    proc = tmp_path / "proc"
    # util-linux fincore prints "RES SIZE" in bytes for these flags; a stub keeps the test independent of whether the
    # controller ships util-linux-extra, and of what the page cache happens to hold.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "fincore").write_text('#!/bin/sh\n[ "$*" = "--bytes --noheadings --output RES,SIZE $5" ] || exit 2\n'
                                     'echo "  40960 $(wc -c <"$5")"\n')
    (bin_dir / "fincore").chmod(0o755)
    _worker(proc, 4242, "llama-server", "8003", 12, 4652460, b"\0" * 65536)
    _worker(proc, 4243, "python3", "9000", 99, 1, b"\0" * 4096)          # not a llama.cpp worker: ignored
    # A worker that exits mid-scan leaves only some of its /proc files; the writer must still succeed.
    (proc / "4244").mkdir()
    (proc / "4244/comm").write_text("llama-server\n")
    (proc / "4244/cmdline").write_bytes(b"llama-server\0--port\08001\0")
    out = tmp_path / "out"
    env_file = tmp_path / "monitoring.env"
    env_file.write_text(f"MONITORING_METRICS_TEXTFILE_DIR={out}\nMONITORING_LOG_DIR={tmp_path}/log\nMONITORING_ALERT_LOG_DIR={tmp_path}/a\n"
                        f"MONITORING_GPU_TEMP_STATE_DIR={tmp_path}/state\n")
    empty = tmp_path / "none"
    empty.mkdir()
    subprocess.run(["sh", str(SCRIPT)], check=True, capture_output=True, text=True,
                   env={**os.environ, "AIHOST_MONITORING_ENV": str(env_file), "AIHOST_HWMON_ROOT": str(empty),
                        "AIHOST_PCI_ROOT": str(empty), "AIHOST_PROC_ROOT": str(proc),
                        "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    text = (out / "gpu.prom").read_text()
    types = validate_exposition(text)
    assert types["aihost_llama_worker_major_faults_total"] == "counter"
    assert 'aihost_llama_worker_major_faults_total{port="8003"} 12' in text
    assert 'aihost_llama_worker_resident_file_bytes{port="8003"} 4764119040' in text
    # One series per mapped file, however many mappings it has; shared libraries are not model files.
    assert text.count("aihost_llama_model_file_size_bytes{") == 1
    assert 'aihost_llama_model_file_size_bytes{port="8003",file="weights-00001-of-00002.gguf"} 65536' in text
    assert 'aihost_llama_model_file_cached_bytes{port="8003",file="weights-00001-of-00002.gguf"} 40960' in text
    assert 'port="9000"' not in text
    assert 'aihost_llama_worker_resident_file_bytes{port="8001"}' not in text
