"""The host textfile exporter must emit valid, unambiguous Prometheus exposition for a real-looking GPU tree."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.test_orchestrator_metrics_contract import validate_exposition

SCRIPT = Path(__file__).resolve().parents[1] / "roles/monitoring/files/write-textfile-metrics.sh"


def _gpu(root: Path, pci: Path, hwmon: str, bdf: str, temps: dict[str, int], energy_uj: int, idle_ms: int, mhz: int):
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
    (h / "energy1_input").write_text(f"{energy_uj}\n")
    (h / "energy1_label").write_text("card\n")
    (h / "power1_cap").write_text("150000000\n")
    (h / "fan1_input").write_text("0\n")


def _run(tmp_path: Path, warn="75", crit="85") -> str:
    hw, pci = tmp_path / "hwmon", tmp_path / "pci"
    # hwmon numbering deliberately reversed relative to PCI order: the gpu ordinal must follow the PCI address.
    _gpu(hw, pci, "hwmon4", "0000:93:00.0", {"pkg": 38000, "vram": 40000, "vram_ch_0": 36000}, 2_000_000, 1000, 1200)
    _gpu(hw, pci, "hwmon3", "0000:51:00.0", {"pkg": 30000, "vram": 32000, "vram_ch_0": 31000}, 12_345_678, 3504771, 2400)
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
