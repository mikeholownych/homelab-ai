#!/usr/bin/env python3
"""Inference Benchmark Runner and Evidence Generator.

Remediated harness (B0). Guarantees for physical (`real`) runs:

- Fail-closed, immutable, run-addressed evidence under
  ``benchmarks/<benchmark_run_id>/``; a run id is never overwritten.
- Telemetry is classified MEASURED / DERIVED / UNAVAILABLE / UNSUPPORTED and a
  real run that requires a sensor that is missing or lost is INVALID, never PASS.
- Identity is bound (boot id, systemd invocation, container, image digest,
  served model, GPU topology) before any physical result can be VALID.
- TTFT / ITL / e2e / decode throughput come from raw streaming timestamps;
  prefill throughput is never invented (``prompt_tokens / generation_seconds``
  is gone).
- Every raw request and telemetry sample is preserved; failed/incomplete runs
  remain evidence and are never discarded.
- Simulated evidence lives under ``benchmarks/simulated/`` only and is marked
  ``authoritative: false`` so site.yml convergence can never overwrite a
  physical run.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

# The old sanity test greps the source for a few hard-coded values it never
# wants to see fabricated again; keep this module free of invented identities.
HARNESS_VERSION = "2.0.0"

FAILURE_TAXONOMY = {
    "CLIENT_ERROR": "client-side request construction or transport error",
    "HTTP_ERROR": "server returned a non-2xx HTTP response",
    "TIMEOUT": "request exceeded the configured timeout window",
    "INVALID_RESPONSE": "response was received but could not be parsed or did not form a token stream",
    "OOM": "server reported an out-of-memory condition",
    "DEVICE_LOST": "XPU device was lost during the run",
    "SERVICE_RESTART": "service restarted between identity snapshots",
    "SERVICE_INVOCATION_CHANGED": "systemd invocation id changed between identity snapshots",
    "MODEL_IDENTITY_CHANGED": "served model id changed between identity snapshots",
    "TP_TOPOLOGY_CHANGED": "gpu topology / tensor-parallel wiring changed between identity snapshots",
    "TELEMETRY_LOST": "required fail-closed telemetry became unavailable",
    "SAFETY_ABORT": "run aborted by an active safety guardrail",
    "THERMAL_ABORT": "run aborted by the thermal guardrail",
    "HARNESS_ERROR": "harness-internal error",
    "WORKLOAD_TOKEN_DEVIATION": "observed workload token count deviated beyond the permitted bound",
    "CORRECTNESS_FAILURE": "received output failed the deterministic correctness check",
    "SERVICE_UNREACHABLE": "inference service could not be reached",
    "REQUEST_CONNECTION_FAILED": "a request could not be established",
    "POWER_BUDGET_EXCEEDED": "declared platform draw exceeds the PSU capacity headroom",
}

PROMPT_CLASSES = {
    "short": 1024,
    "medium": 4096,
    "large": 16384,
    "very_large": 32768,
    "max_near_window": 61440,
}
OUTPUT_CLASSES = {"tiny": 128, "short": 512, "medium": 2048, "large": 4096}

CORRECTNESS_STATUSES = ("RESPONSE_RECEIVED", "RESPONSE_VALID", "RESPONSE_INVALID", "REQUEST_FAILED")

__SOURCE_HASH__ = "unset"

# ---------------------------------------------------------------- sysfs utils

def _read_sysfs(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _bracketed(content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    match = re.search(r"\[([A-Za-z+]+)\]", content)
    return match.group(1) if match else None


def _sysctl_int(name: str) -> Optional[int]:
    try:
        output = subprocess.run(
            ["/usr/sbin/sysctl", "-n", name], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return int(output)
    except ValueError:
        return None


def _run_capture(*argv: str) -> Optional[str]:
    try:
        return subprocess.run(
            list(argv), check=False, capture_output=True, text=True, timeout=20
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _first_line_of(path: str) -> Optional[str]:
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        return content.splitlines()[0] if content else None
    except OSError:
        return None


def _dpkg_first_version(packages: List[str]) -> Optional[str]:
    try:
        output = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}=${Version}\\n", *packages],
            check=True, capture_output=True, text=True, timeout=20,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    lines = [ln for ln in output.splitlines() if ln]
    return lines[0] if lines else None


def _sha256(paths: List[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def source_sha256() -> str:
    if __SOURCE_HASH__ != "unset":
        return __SOURCE_HASH__
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "0" * 64


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_run_id(now: Optional[str] = None) -> str:
    """Unique run id: UTC datetime + random 8-hex suffix; never overwritten."""
    stamp = (now or utc_now()).replace("-", "").replace(":", "").replace("+00:00", "")
    return f"{stamp}-{secrets.token_hex(4)}"


# ------------------------------------------------------------- guardrail math

def evaluate_power_budget(
    gpu_count: int,
    gpu_tdp_watts: float,
    psu_capacity_watts: float,
    base_power_watts: float,
    headroom_pct: float,
) -> Dict[str, Any]:
    estimated = gpu_count * gpu_tdp_watts + base_power_watts
    limit = psu_capacity_watts * (100.0 - headroom_pct) / 100.0
    return {
        "estimated_watts": round(estimated, 1),
        "limit_watts": round(limit, 1),
        "status": "ok" if estimated <= limit else "refused",
    }


# ------------------------------------------------------------- GPU topology

def discover_gpu_hwmons() -> List[Path]:
    """hwmon devices bound to GPU drivers (xe/i915 class platforms)."""
    found: List[Path] = []
    base = Path("/sys/class/hwmon")
    try:
        for entry in sorted(base.iterdir()):
            name = (entry / "name").read_text(errors="replace").strip().lower()
            if any(token in name for token in ("xe", "i915", "drm", "gpu")):
                found.append(entry)
    except OSError:
        pass
    return found


def _resolve_hwmon_for_card(card: Path) -> Optional[Path]:
    """Map a drm card to its device hwmon (xe exposes one hwmon per card)."""
    try:
        hwmon_link = card / "device" / "hwmon"
        if not hwmon_link.is_dir():
            return None
        entries = sorted(hwmon_link.iterdir())
        for entry in entries:
            if entry.name.startswith("hwmon"):
                return entry
    except OSError:
        return None
    return None


def discover_gpu_topology() -> List[Dict[str, Any]]:
    """Per-GPU identity: card, PCI BDF, driver, hwmon, vendor/device ids."""
    topology: List[Dict[str, Any]] = []
    drm = Path("/sys/class/drm")
    try:
        cards = sorted(
            (d for d in drm.glob("card[0-9]*") if (d / "device").exists()),
            key=lambda d: d.name,
        )
    except OSError:
        return topology

    for index, card in enumerate(cards):
        device_dir = card / "device"
        try:
            uevent = (device_dir / "uevent").read_text(errors="replace")
        except OSError:
            uevent = ""
        pci_match = re.search(r"PCI_SLOT_NAME=(.*)", uevent)
        vendor_match = re.search(r"PCI_ID=([0-9A-Fa-f]{4}):", uevent)
        device_match = re.search(r"PCI_ID=[0-9A-Fa-f]{4}:([0-9A-Fa-f]{4})", uevent)
        driver = None
        drv_link = device_dir / "driver"
        try:
            if drv_link.is_symlink():
                driver = drv_link.resolve().name
        except OSError:
            pass
        hwmon = _resolve_hwmon_for_card(card)
        topology.append({
            "gpu_index": index,
            "card": card.name,
            "pci_address": pci_match.group(1) if pci_match else None,
            "driver": driver,
            "vendor": vendor_match.group(1) if vendor_match else None,
            "device": device_match.group(1) if device_match else None,
            "hwmon": hwmon.name if hwmon else None,
        })
    return topology


def _gpu_max_temp_c(hwmon: Optional[Path]) -> Optional[float]:
    if hwmon is None:
        return None
    temps: List[float] = []
    try:
        for temp_file in sorted(hwmon.glob("temp*_input")):
            try:
                temps.append(float(temp_file.read_text(errors="replace").strip()) / 1000.0)
            except (OSError, ValueError):
                continue
    except OSError:
        return None
    return max(temps) if temps else None


# ---------------------------------------------------------------- telemetry

class TelemetrySampler(threading.Thread):
    """Sampler for GPU temperature (MEASURED where present), power (UNSUPPORTED
    on this xe class unless a power input exists), host CPU/RAM.

    Fail-closed semantics: ``required_sensor_present`` becomes False when a GPU
    that should expose temperature does not, and the run must be invalidated.
    """

    def __init__(self, interval_sec: float = 1.0, abort_threshold_c: Optional[float] = None):
        super().__init__(daemon=True)
        self.interval_sec = interval_sec
        self.abort_threshold_c = abort_threshold_c
        self.stop_event = threading.Event()
        self.gpu_temps_c: List[float] = []
        self.gpu_powers_w: List[float] = []
        self.mem_available_gib: List[float] = []
        self.cpu_util_percent: List[float] = []
        self.telemetry_source = "unavailable"
        self.aborted = False
        self.required_sensor_present = False
        self.gpu_topology: List[Dict[str, Any]] = []
        self.per_gpu_last_temp: Dict[str, Optional[float]] = {}
        self._last_cpu_stat: Optional[Dict[str, int]] = None

    @staticmethod
    def _first_float(path: Optional[Path]) -> Optional[float]:
        if path is None:
            return None
        try:
            return float(path.read_text(errors="replace").strip())
        except (OSError, ValueError):
            return None

    def _cpu_util(self) -> Optional[float]:
        stat = _read_sysfs("/proc/stat")
        if not stat:
            return None
        first = stat.splitlines()[0]
        parts = first.split()[1:]
        idle = sum(int(value) for value in parts[3:5] if value.isdigit())
        total = sum(int(value) for value in parts if value.isdigit())
        if total <= 0:
            return None
        if self._last_cpu_stat is None:
            self._last_cpu_stat = {"total": total, "idle": idle}
            return None
        delta_total = total - self._last_cpu_stat["total"]
        delta_idle = idle - self._last_cpu_stat["idle"]
        self._last_cpu_stat = {"total": total, "idle": idle}
        if delta_total <= 0:
            return None
        return 100.0 * (1.0 - delta_idle / delta_total)

    def sample_once(self) -> None:
        topology = discover_gpu_topology()
        self.gpu_topology = topology
        self.gpu_temps_c.clear()
        self.gpu_powers_w.clear()
        self.telemetry_source = "unavailable"
        for gpu in topology:
            hwmon_name = gpu.get("hwmon")
            hwmon = Path("/sys/class/hwmon") / hwmon_name if hwmon_name else None
            temp = _gpu_max_temp_c(hwmon)
            self.per_gpu_last_temp[gpu["card"]] = temp
            if temp is not None:
                self.gpu_temps_c.append(temp)
                self.required_sensor_present = True
                self.telemetry_source = "hwmon"
            for power_name in ("power1_input", "power2_input"):
                power = self._first_float(hwmon / power_name) if hwmon else None
                if power is not None:
                    self.gpu_powers_w.append(power / 1_000_000.0)
        meminfo = _read_sysfs("/proc/meminfo")
        if meminfo:
            match = re.search(r"MemAvailable:\s+(\d+) kB", meminfo)
            if match:
                self.mem_available_gib.append(int(match.group(1)) / 1024 / 1024)
        cpu = self._cpu_util()
        if cpu is not None:
            self.cpu_util_percent.append(round(cpu, 3))

    def max_temperature(self) -> Optional[float]:
        return max(self.gpu_temps_c) if self.gpu_temps_c else None

    def peak_gpu_temperature_c(self) -> Optional[float]:
        return self.max_temperature()

    def summarize(self, values: List[float]) -> Dict[str, Any]:
        if not values:
            return {"status": "unavailable", "reason": "no telemetry samples collected"}
        rounded = [round(v, 3) for v in values]
        return {
            "samples": len(values),
            "min": min(rounded),
            "max": max(rounded),
            "mean": round(statistics.fmean(rounded), 3),
        }

    def run(self) -> None:
        while not self.stop_event.is_set():
            self.sample_once()
            peak = self.max_temperature()
            if peak is not None and self.abort_threshold_c is not None and peak >= self.abort_threshold_c:
                self.aborted = True
                return
            self.stop_event.wait(self.interval_sec)


# ------------------------------------------------------------- HTTP inference

def load_api_key_from_env_file(env_file: str, key_name: str) -> Optional[str]:
    try:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key_name}="):
                value = line.split("=", 1)[1].strip()
                return value or None
    except OSError:
        return None
    return None


def _request_headers(api_key: Optional[str]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def tokenize_prompt(
    base_url: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
    timeout_sec: float = 30.0,
) -> Dict[str, Any]:
    """Authoritative server-side token count via vLLM /tokenize (200)."""
    body = json.dumps({"model": model, "prompt": prompt}).encode("utf-8")
    for endpoint in ("/tokenize", "/v1/tokenize"):
        url = f"{base_url.rstrip('/')}{endpoint}"
        request = urllib.request.Request(url, data=body, headers=_request_headers(api_key))
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
            count = payload.get("count") if isinstance(payload, dict) else None
            if isinstance(count, int) and count > 0:
                return {"ok": True, "count": count, "endpoint": endpoint}
        except urllib.error.HTTPError:
            continue
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
            continue
    return {"ok": False, "count": None, "endpoint": None}


def query_served_models(base_url: str, api_key: Optional[str], timeout_sec: float = 30.0) -> List[str]:
    url = f"{base_url.rstrip('/')}/v1/models"
    request = urllib.request.Request(url, headers=_request_headers(api_key))
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            return [item.get("id") for item in data if isinstance(item, dict) and item.get("id")]
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, urllib.error.HTTPError):
        pass
    return []


def _chunk_tokens(text: str) -> int:
    """Per-SSE-chunk token estimate used only to weight inter-arrival timing."""
    if not text:
        return 0
    parts = [part for part in text.split() if part]
    if not parts:
        return 0
    return max(len(parts), 1)


def stream_vllm_completion(
    base_url: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
    max_new_tokens: int,
    timeout_sec: float,
    sentinel: Optional[str] = None,
    request_id: Optional[str] = None,
    sample_class: str = "measured",
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1/completions"
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "max_tokens": max_new_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_request_headers(api_key))

    started = time.perf_counter()
    ttft_ms: Optional[float] = None
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    text_chunks: List[str] = []
    arrival_times_ms: List[float] = []
    http_status: Optional[int] = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            http_status = response.status
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(event.get("usage"), dict):
                    completion_tokens = event["usage"].get("completion_tokens")
                    prompt_tokens = event["usage"].get("prompt_tokens")
                choices = event.get("choices") or []
                if choices:
                    reason = choices[0].get("finish_reason")
                    if reason:
                        finish_reason = reason
                    text = choices[0].get("text") or (choices[0].get("delta") or {}).get("content") or ""
                    if ttft_ms is None and text:
                        ttft_ms = (time.perf_counter() - started) * 1000.0
                    if text:
                        local = time.perf_counter()
                        arrival_times_ms.append((local - started) * 1000.0)
                        text_chunks.append(text)
    except urllib.error.HTTPError as error:
        return {
            "status": "error", "reason": f"http {error.code}: {error.reason}",
            "failure_code": "HTTP_ERROR", "request_id": request_id,
            "sample_class": sample_class, "http_status": error.code,
        }
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return {
            "status": "error", "reason": f"connection failure: {error}",
            "failure_code": "REQUEST_CONNECTION_FAILED", "request_id": request_id,
            "sample_class": sample_class,
            "http_status": http_status or 0,
        }

    elapsed_s = time.perf_counter() - started
    content = "".join(text_chunks)
    if ttft_ms is None or not content:
        reason = "no token stream observed"
        if sentinel is not None:
            return {
                "status": "error", "reason": reason, "failure_code": "INVALID_RESPONSE",
                "request_id": request_id, "sample_class": sample_class,
                "http_status": http_status or 0, "text": content, "sentinel": sentinel,
                "correctness": "REQUEST_FAILED",
            }
        return {
            "status": "error", "reason": reason, "failure_code": "INVALID_RESPONSE",
            "request_id": request_id, "sample_class": sample_class,
            "http_status": http_status or 0, "text": content,
        }

    completion_tokens = int(completion_tokens or 0)
    if completion_tokens <= 0:
        completion_tokens = sum(_chunk_tokens(chunk) for chunk in text_chunks) or 1
    prompt_tokens = int(prompt_tokens or 0)

    generation_elapsed_s = max(elapsed_s - (ttft_ms / 1000.0), 1e-6)
    inter_token_latency_ms: List[float] = []
    for i in range(1, len(arrival_times_ms)):
        inter_token_latency_ms.append(arrival_times_ms[i] - arrival_times_ms[i - 1])

    result = {
        "status": "ok",
        "ttft_ms": ttft_ms,
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "generation_seconds": generation_elapsed_s,
        "elapsed_seconds": elapsed_s,
        "generation_tokens_per_second": completion_tokens / generation_elapsed_s,
        "finish_reason": finish_reason,
        "request_id": request_id,
        "sample_class": sample_class,
        "http_status": http_status or 200,
        "inter_token_latency_ms": inter_token_latency_ms,
        "token_arrival_count": len(arrival_times_ms),
    }
    if sentinel is not None:
        valid = sentinel in content
        result["correctness"] = "RESPONSE_VALID" if valid else "RESPONSE_INVALID"
        result["text"] = content[:600]
        result["sentinel"] = sentinel
        result["text_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not valid:
            result["failure_code"] = "CORRECTNESS_FAILURE"
    return result


def probe_llama_completion(
    base_url: str,
    api_key: Optional[str],
    prompt: str,
    max_new_tokens: int,
    timeout_sec: float,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/completion"
    body = json.dumps({"prompt": prompt, "n_predict": max_new_tokens, "stream": False}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_request_headers(api_key))
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return {"status": "error", "reason": f"http {error.code}: {error.reason}", "failure_code": "HTTP_ERROR"}
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as error:
        return {"status": "error", "reason": f"request failure: {error}", "failure_code": "REQUEST_CONNECTION_FAILED"}
    elapsed_s = time.perf_counter() - started
    timings = payload.get("timings") or {}
    predicted_per_second = timings.get("predicted_per_second")
    predicted_ms = timings.get("predicted_ms")
    tokens = payload.get("tokens_predicted")
    if predicted_per_second is None and predicted_ms and tokens:
        predicted_per_second = tokens / (predicted_ms / 1000.0)
    if predicted_per_second is None or not tokens:
        return {"status": "error", "reason": "server did not report token timings", "failure_code": "INVALID_RESPONSE"}
    ttft_ms = elapsed_s * 1000.0 - (timings.get("prompt_ms") or 0.0)
    return {
        "status": "ok",
        "ttft_ms": ttft_ms,
        "completion_tokens": int(tokens),
        "generation_seconds": (predicted_ms or 0.0) / 1000.0,
        "generation_tokens_per_second": predicted_per_second,
        "elapsed_seconds": elapsed_s,
    }


# ------------------------------------------------------------ live identity

def collect_os_tuning(tuning_profile: str, tuning_revision: str) -> Dict[str, Any]:
    """Capture live OS tuning provenance so every benchmark is attributable."""
    governor = _read_sysfs("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    epp = _read_sysfs("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference")
    thp_mode = _bracketed(_read_sysfs("/sys/kernel/mm/transparent_hugepage/enabled"))
    scheduler = None
    nvme_dirs = sorted(Path("/sys/block").glob("nvme*n*"))
    if nvme_dirs:
        scheduler = _bracketed(_read_sysfs(f"/sys/block/{nvme_dirs[0].name}/queue/scheduler"))
    hugepages_total = _sysctl_int("vm.nr_hugepages") or 0
    irqbalance = None
    try:
        irqbalance = subprocess.run(
            ["systemctl", "is-active", "irqbalance"], capture_output=True, text=True, timeout=20
        ).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    cmdline = _read_sysfs("/proc/cmdline")
    numa_policy = os.environ.get("AIHOST_BENCH_NUMA_POLICY")
    cpu_affinity = os.sched_getaffinity(0) and ",".join(str(c) for c in sorted(os.sched_getaffinity(0))[:64])
    membind = os.environ.get("AIHOST_BENCH_MEMBIND_NODES")
    return {
        "os_tuning_profile": tuning_profile,
        "tuning_profile_revision": tuning_revision,
        "cpu_governor": governor,
        "energy_performance_policy": epp,
        "numa_policy": numa_policy or ("interleave" if membind else None),
        "cpu_affinity": cpu_affinity or None,
        "memory_binding": membind,
        "thp_mode": thp_mode,
        "hugepages_enabled": bool(hugepages_total),
        "hugepages_size_kib": 2048 if hugepages_total else None,
        "hugepages_count": hugepages_total or None,
        "swappiness": _sysctl_int("vm.swappiness"),
        "io_scheduler": scheduler,
        "irq_policy": f"irqbalance:{irqbalance}" if irqbalance else "irqbalance:unknown",
        "kernel_cmdline": cmdline,
    }


def _live_system_provenance(hostname: str) -> Dict[str, Any]:
    """Read live system identity; 'unknown' beats fabrication."""
    kernel = _run_capture("/usr/bin/uname", "-r") or "unknown"
    bios = _read_sysfs("/sys/class/dmi/id/bios_version") or "unknown"

    intel_runtime = "unknown"
    try:
        gpu_dirs = sorted(Path("/var/cache/local-ai/intel-gpu").iterdir())
        if gpu_dirs:
            intel_runtime = gpu_dirs[-1].name
    except OSError:
        pass

    l0 = _dpkg_first_version(["libze1", "libze-intel-gpu1"])

    pytorch = "unknown"
    current_link = Path("/opt/local-ai/pytorch-xpu/current")
    try:
        target = current_link.resolve().name
        marker = target.find("-py")
        pytorch = target[:marker] if marker > 0 else target
    except OSError:
        pass

    vllm_version = _first_line_of("/etc/local-ai/vllm/VERSION") or "unknown"
    llama_commit = _first_line_of("/opt/llama.cpp-sycl/BUILD_COMMIT") or "unknown"

    return {
        "hostname": hostname,
        "bios_version": bios,
        "kernel_version": kernel,
        "intel_runtime_version": intel_runtime,
        "level_zero_version": l0 or "unknown",
        "pytorch_version": pytorch,
        "vllm_version": vllm_version,
        "llama_commit": llama_commit,
    }


def read_boot_id() -> Optional[str]:
    return _first_line_of("/proc/sys/kernel/random/boot_id")


def read_systemd_service(service_unit: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    active = _run_capture("/usr/bin/systemctl", "is-active", service_unit)
    info["active_state"] = active or "unknown"
    info["unit"] = service_unit
    invocation = _run_capture(
        "/usr/bin/systemctl", "show", service_unit, "-p", "InvocationID", "--value"
    )
    nrestarts = _run_capture(
        "/usr/bin/systemctl", "show", service_unit, "-p", "NRestarts", "--value"
    )
    info["invocation_id"] = invocation
    try:
        info["nrestarts"] = int(nrestarts) if nrestarts else None
    except ValueError:
        info["nrestarts"] = None
    return info


def read_container_identity(container_name: str = "vllm-xpu") -> Dict[str, Any]:
    rootless = os.environ.get("AIHOST_CONTAINER_RUNTIME_HOST") == "rootless"
    base_env = dict(os.environ)
    if rootless:
        base_env.setdefault("HOME", "/var/lib/aihost-runtime")
        base_env.setdefault("XDG_RUNTIME_DIR", "/run/user/999")
    try:
        out = subprocess.run(
            ["/usr/bin/podman", "ps", "--format", "{{.ID}}|{{.Names}}|{{.Image}}"],
            capture_output=True, text=True, timeout=20, env=base_env,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    digest = None
    image_ref = None
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[1] == container_name:
            image_ref = parts[2]
            match = re.search(r"sha256:[0-9a-f]{64}", parts[2])
            if match:
                digest = match.group(0)
            return {"container_id": parts[0], "image_ref": image_ref, "image_digest": digest}
    return {}


def collect_live_identity(
    base_url: str,
    api_key: Optional[str],
    model_expected: str,
    service_unit: str,
    container_name: str,
) -> Dict[str, Any]:
    topology = discover_gpu_topology()
    service = read_systemd_service(service_unit)
    container = read_container_identity(container_name)
    served = query_served_models(base_url, api_key)
    return {
        "boot_id": read_boot_id(),
        "systemd_invocation_id": service.get("invocation_id"),
        "systemd_nrestarts": service.get("nrestarts"),
        "systemd_active_state": service.get("active_state"),
        "container_id": container.get("container_id"),
        "image_ref": container.get("image_ref"),
        "image_digest": container.get("image_digest"),
        "model_observed": served,
        "model_expected": model_expected,
        "gpu_identity": topology,
    }


def identity_requires_fail_closed(identity: Dict[str, Any], gpu_count: int) -> List[str]:
    """Return reasons a physical run cannot be VALID."""
    reasons: List[str] = []
    if not identity.get("boot_id"):
        reasons.append("boot_id unreadable")
    topology = identity.get("gpu_identity") or []
    if len(topology) == 0 and gpu_count >= 1:
        reasons.append("no gpu topology discovered")
    model_observed = identity.get("model_observed") or []
    if not model_observed:
        reasons.append("served model id could not be observed")
    elif identity.get("model_expected") and identity["model_expected"] not in model_observed:
        reasons.append(f"served model {model_observed} != expected {identity.get('model_expected')}")
    return reasons


# --------------------------------------------------------------- workload

def _deterministic_filler(target_tokens: int, chars_per_token: float, seed: str) -> str:
    """Deterministic pseudo-code filler approximating a target token budget.
    Fills in whole chunks then a partial remainder so any character budget is
    hit exactly; whole-chunk-only repeat arithmetic used to undershoot by a
    chunk, which pushed short-budget prompts outside the deviation bound."""
    needed_characters = max(int(target_tokens * chars_per_token), 1)
    chunk = (
        f"// {seed} - inference workload block\n"
        "def compute_layer(activations, weights, biases):\n"
        "    out = [0.0] * len(activations)\n"
        "    for i in range(len(activations)):\n"
        "        acc = biases[i] if i < len(biases) else 0.0\n"
        "        for j in range(len(weights[i])):\n"
        "            acc += activations[j] * weights[i][j]\n"
        "        out[i] = max(acc, 0.0)\n"
        "    return out\n\n"
    )
    if len(chunk) >= needed_characters:
        return chunk[:needed_characters]
    repeats, remainder = divmod(needed_characters, len(chunk))
    return chunk * repeats + chunk[:remainder]


def build_deterministic_prompt(
    prompt_class: str,
    target_tokens: int,
    base_url: str,
    api_key: Optional[str],
    model: str,
    max_deviation_pct: float = 5.0,
    tokenize_timeout: float = 30.0,
) -> Dict[str, Any]:
    """Deterministic synthetic prompt sized to a target token budget using the
    authoritative server tokenizer when available."""
    seed = f"b0-{prompt_class}-{target_tokens}"
    if prompt_class == "fixed_custom":
        text = "Write a short sentence about efficient inference."
        observed = None
        source = "estimated"
        estimate = max(int(len(text) / 4.0), 1)
        tok = tokenize_prompt(base_url, api_key, model, text, timeout_sec=tokenize_timeout)
        if tok.get("ok"):
            observed = tok["count"]
            source = "server_tokenize"
        actual = observed or estimate
        deviation = abs(actual - target_tokens) if target_tokens else 0
        deviation_pct = (deviation / target_tokens * 100.0) if target_tokens else None
        return {
            "prompt_text": text, "observed_tokens": actual, "token_source": source,
            "deviation_tokens": deviation, "deviation_pct": deviation_pct,
            "prompt_class": prompt_class,
        }

    text = _deterministic_filler(target_tokens, chars_per_token=3.8, seed=seed)
    tok = tokenize_prompt(base_url, api_key, model, text, timeout_sec=tokenize_timeout)
    if tok.get("ok") and tok["count"] > 0:
        # Iterate the character/token ratio to convergence: a single pass can
        # land outside the deviation bound because the filler's exact-repeat
        # remainder must be re-measured against the served tokenizer.
        observed = tok["count"]
        best: Optional[tuple[float, str, int]] = None
        for _ in range(6):
            ratio = len(text) / observed
            candidate = _deterministic_filler(target_tokens, chars_per_token=ratio, seed=seed)
            tok2 = tokenize_prompt(base_url, api_key, model, candidate, timeout_sec=tokenize_timeout)
            if not tok2.get("ok") or tok2["count"] <= 0:
                break
            text = candidate
            observed = tok2["count"]
            deviation = abs(observed - target_tokens)
            deviation_pct = (deviation / target_tokens * 100.0) if target_tokens else None
            if best is None or (deviation_pct is not None and deviation_pct < best[0]):
                best = (deviation_pct or 0.0, text, observed)
            if best[0] <= max_deviation_pct:
                break
        if best is not None:
            _, text, observed = best
        source = "server_tokenize"
    else:
        observed = max(int(len(text) / 3.8), 1)
        source = "estimated"

    deviation = abs(observed - target_tokens)
    deviation_pct = (deviation / target_tokens * 100.0) if target_tokens else None
    return {
        "prompt_text": text, "observed_tokens": observed, "token_source": source,
        "deviation_tokens": deviation, "deviation_pct": deviation_pct,
        "prompt_class": prompt_class,
    }


def build_sentinel(prompt_class: str, run_id: str) -> str:
    seed = hashlib.sha256(f"{run_id}:{prompt_class}".encode("utf-8")).hexdigest()
    return f"RESPONSE_MARKER_{seed[:12]}"


# --------------------------------------------------------------- statistics

def _pct(sorted_values: List[float], pctile: float) -> Optional[float]:
    if not sorted_values:
        return None
    index = max(0, min(len(sorted_values) - 1, int((pctile / 100.0) * (len(sorted_values) - 1))))
    return sorted_values[index]


def compute_distribution(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "p50": None, "p95": None, "p99": None}
    rounded = [round(v, 6) for v in values]
    ordered = sorted(rounded)
    return {
        "count": len(rounded),
        "min": round(min(rounded), 6),
        "max": round(max(rounded), 6),
        "mean": round(statistics.fmean(rounded), 6),
        "p50": round(_pct(ordered, 50), 6),
        "p95": round(_pct(ordered, 95), 6),
        "p99": round(_pct(ordered, 99), 6),
    }


# --------------------------------------------------------------- validity

def compute_validity(
    status: str,
    triggered_reasons: List[Dict[str, Any]],
    interrupted: bool = False,
    performance_assessment: str = "NOT_EVALUATED",
) -> Dict[str, Any]:
    if interrupted:
        state = "INCOMPLETE"
        reasons = triggered_reasons or [{"code": "INCOMPLETE", "detail": "run interrupted before completion"}]
    elif status == "PASS" or status == "SIMULATED_PASS":
        state = "VALID"
        reasons = []
    else:
        state = "INVALID"
        reasons = triggered_reasons or [{"code": "FAIL", "detail": "run did not pass"}]
    return {
        "state": state,
        "reasons": reasons,
        "interrupted": interrupted,
        "performance_assessment": performance_assessment,
    }


def metric_support_classification(supported: bool) -> str:
    return "MEASURED" if supported else "UNSUPPORTED"


# ------------------------------------------------------------ document build

def _telemetry_metric(
    expected: float | None,
    unit: str,
    *,
    measured: Optional[float] = None,
    classification: str = "UNAVAILABLE",
    reason: str = "not measured in this mode",
) -> Dict[str, Any]:
    expected_value = {
        "value": expected,
        "unit": unit,
    } if expected is not None else {"status": "unsupported", "reason": "no platform expectation defined"}
    if classification == "MEASURED" and measured is not None:
        observed = {"value": round(measured, 4), "unit": unit}
    elif classification == "DERIVED" and measured is not None:
        observed = {"value": round(measured, 4), "unit": unit}
    elif classification in ("UNSUPPORTED", "UNAVAILABLE"):
        observed = {"status": "unavailable" if classification == "UNAVAILABLE" else "unsupported", "reason": reason}
        classification = classification
    else:
        observed = {"status": "unavailable", "reason": reason}
    return {
        "classification": classification,
        "expected": expected_value,
        "observed": observed,
    }


def build_environment_document(
    benchmark_run_id: str,
    identity: Dict[str, Any],
    hostname: str,
    system: Dict[str, Any],
) -> Dict[str, Any]:
    gpu_replace = []
    for gpu in identity.get("gpu_identity", []):
        gpu_replace.append({
            "gpu_index": gpu.get("gpu_index"),
            "card": gpu.get("card"),
            "pci_address": gpu.get("pci_address"),
            "driver": gpu.get("driver"),
            "vendor": gpu.get("vendor"),
            "device": gpu.get("device"),
            "hwmon": gpu.get("hwmon"),
        })
    return {
        "schema_version": "2.0.0",
        "benchmark_run_id": benchmark_run_id,
        "collected_at": utc_now(),
        "identity": {
            "boot_id": identity.get("boot_id"),
            "systemd_invocation_id": identity.get("systemd_invocation_id"),
            "systemd_nrestarts": identity.get("systemd_nrestarts"),
            "container_id": identity.get("container_id"),
            "image_ref": identity.get("image_ref"),
            "image_digest": identity.get("image_digest"),
            "model_observed": identity.get("model_observed", []),
            "model_expected": identity.get("model_expected"),
            "gpu_identity": gpu_replace,
            "versions": {
                "vllm": system.get("vllm_version"),
                "podman": os.environ.get("PODMAN_VERSION"),
                "kernel": system.get("kernel_version"),
                "level_zero": system.get("level_zero_version"),
                "intel_runtime": system.get("intel_runtime_version"),
                "pytorch": system.get("pytorch_version"),
                "api_key_configured": identity.get("api_key_configured"),
            },
            "service": {
                "unit": identity.get("service_unit"),
                "active_state": identity.get("systemd_active_state"),
                "nrestarts": identity.get("systemd_nrestarts"),
            },
        },
    }


def build_workload_document(
    benchmark_run_id: str,
    prompt: Dict[str, Any],
    prompt_class: str,
    output_class: str,
    max_new_tokens: int,
    concurrency: int,
    requests: int,
    warmup_requests: int,
    max_deviation_pct: float,
    model: str,
    profile: str = "custom",
) -> Dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "benchmark_run_id": benchmark_run_id,
        "workload_id": f"b0-{prompt_class}-{output_class}-c{concurrency}",
        "profile": profile,
        "prompt_class": prompt_class,
        "output_class": output_class,
        "concurrency": concurrency,
        "requests": requests,
        "warmup_requests": warmup_requests,
        "max_new_tokens": max_new_tokens,
        "target_prompt_tokens": PROMPT_CLASSES.get(prompt_class),
        "observed_prompt_tokens": prompt.get("observed_tokens"),
        "deviation_tokens": prompt.get("deviation_tokens"),
        "deviation_pct": prompt.get("deviation_pct"),
        "max_deviation_pct": max_deviation_pct,
        "token_source": prompt.get("token_source"),
        "tokenize_endpoint": prompt.get("tokenize_endpoint"),
        "deterministic": True,
        "model": model,
        "prompt_sample": (prompt.get("prompt_text") or "")[:500],
        "workload_sha256": hashlib.sha256((prompt.get("prompt_text") or "").encode("utf-8")).hexdigest(),
        "max_requests_deviation_pct": 0.0,
    }


def build_metrics_document(
    benchmark_run_id: str,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    measured = [r for r in records if r.get("status") == "ok" and r.get("sample_class") == "measured"]
    warmup = [r for r in records if r.get("sample_class") == "warmup"]
    failed = [r for r in records if r.get("status") != "ok"]

    counts = {
        "attempted": len(records),
        "measured": len(measured),
        "warmup": len(warmup),
        "failed": len(failed),
        "timed_out": sum(1 for r in failed if r.get("failure_code") == "TIMEOUT"),
        "invalid_response": sum(1 for r in failed if r.get("failure_code") == "INVALID_RESPONSE"),
        "oom": sum(1 for r in failed if r.get("failure_code") == "OOM"),
        "device_lost": sum(1 for r in failed if r.get("failure_code") == "DEVICE_LOST"),
    }

    distributions: Dict[str, Any] = {}
    distributions["ttft_ms"] = compute_distribution(
        [r["ttft_ms"] for r in measured if r.get("ttft_ms") is not None]
    )
    itl_values: List[float] = []
    for r in measured:
        itl_values.extend(r.get("inter_token_latency_ms") or [])
    distributions["inter_token_latency_ms"] = compute_distribution(itl_values)
    distributions["end_to_end_ms"] = compute_distribution(
        [r["elapsed_seconds"] * 1000.0 for r in measured if r.get("elapsed_seconds") is not None]
    )
    distributions["decode_tokens_per_second"] = compute_distribution(
        [r["generation_tokens_per_second"] for r in measured if r.get("generation_tokens_per_second") is not None]
    )
    distributions["prompt_tokens"] = compute_distribution(
        [float(r["prompt_tokens"]) for r in measured if r.get("prompt_tokens") is not None]
    )
    distributions["completion_tokens"] = compute_distribution(
        [float(r["completion_tokens"]) for r in measured if r.get("completion_tokens") is not None]
    )

    total_decode = sum(r["generation_seconds"] for r in measured if r.get("generation_seconds"))
    total_tokens = sum(r["completion_tokens"] for r in measured if r.get("completion_tokens"))
    aggregates = {
        "requests_per_second": None,
        "decode_tokens_per_second": round(total_tokens / total_decode, 4) if total_decode > 0 else None,
        "wall_seconds": None,
        "group_wall_seconds": None,
    }

    prefill = {
        "classification": "UNSUPPORTED",
        "tokens_per_second": None,
        "estimated_prompt_seconds": None,
        "reason": "exact prefill duration is not exposed by the streaming API; never "
                  "report prompt_tokens/generation_seconds as prefill throughput",
    }

    return {
        "schema_version": "2.0.0",
        "benchmark_run_id": benchmark_run_id,
        "counts": counts,
        "distributions": distributions,
        "aggregates": aggregates,
        "prefill": prefill,
    }


def build_validity_document(
    benchmark_run_id: str,
    validity: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "benchmark_run_id": benchmark_run_id,
        "state": validity.get("state"),
        "reasons": validity.get("reasons", []),
        "interrupted": validity.get("interrupted", False),
        "performance_assessment": validity.get("performance_assessment", "NOT_EVALUATED"),
        "fail_closed_identity": validity.get("fail_closed_identity", False),
    }


def build_summary_document(benchmark_run_id: str, doc: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    counts = metrics.get("counts", {})
    distributions = metrics.get("distributions", {})
    gen = distributions.get("decode_tokens_per_second", {}) or {}
    ttft = distributions.get("ttft_ms", {}) or {}
    inspects = [
        f"Run {benchmark_run_id}",
        f"status={doc.get('status')} validity={doc.get('validity', {}).get('state')} simulated={doc.get('simulated')}",
        f"prompt_class={doc.get('workload', {}).get('prompt_class')} output_class={doc.get('workload', {}).get('output_class')}",
        f"concurrency={doc.get('workload', {}).get('concurrency')} requests={counts.get('measured')} warmup={counts.get('warmup')}",
        f"decode_tokens_per_second p50={gen.get('p50')} p95={gen.get('p95')} p99={gen.get('p99')}",
        f"ttft_ms p50={ttft.get('p50')} p95={ttft.get('p95')} p99={ttft.get('p99')}",
        f"model={doc.get('model', {}).get('model_id')}",
    ]
    return {
        "benchmark_run_id": benchmark_run_id,
        "summary": "\n".join(inspects),
        "status": doc.get("status"),
        "validity": doc.get("validity"),
    }


def default_safety_block(mode: str, runtime: str) -> Dict[str, Any]:
    return {
        "mode": mode,
        "runtime": runtime,
        "guardrails": {
            "psu_capacity_watts": 1000,
            "gpu_tdp_watts_per_gpu": 225,
            "system_base_power_watts": 250,
            "power_headroom_pct": 20.0,
            "abort_temperature_c": 90,
            "telemetry_required": True,
        },
        "power_budget": {"status": "not_evaluated", "estimated_watts": None, "limit_watts": None},
        "thermal_abort_triggered": False,
        "telemetry_lost": False,
        "telemetry_source": "unavailable",
        "peak_gpu_temperature_c": None,
        "per_gpu_telemetry": [],
    }


def build_benchmark_document(
    profile_name: str = "small",
    hostname: str = "ai-p620-01",
    git_sha: str = "0000000000000000000000000000000000000000",
    simulated: bool = False,
    model_id: str = "Qwen/Qwen2.5-Coder-7B-Instruct",
    revision: str = "main",
    artifact_sha256: str = "0000000000000000000000000000000000000000000000000000000000000000",
    quantization: str = "FP16",
    gpu_count: int = 1,
    tensor_parallelism: int = 1,
    context_window_tokens: int = 4096,
    duration_seconds: float = 30.0,
    status: str = "PASS",
    mode: str = "simulated",
    runtime: str = "simulated",
    safety: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Optional[float]]] = None,
    generated_at: Optional[str] = None,
    benchmark_run_id: Optional[str] = None,
    baseline_id: str = "B0",
    config_id: str = "b0",
    git_dirty: bool = False,
    identity: Optional[Dict[str, Any]] = None,
    workload: Optional[Dict[str, Any]] = None,
    harness: Optional[Dict[str, Any]] = None,
    validity: Optional[Dict[str, Any]] = None,
    raw_artifacts: Optional[Dict[str, str]] = None,
    component_files: Optional[Dict[str, str]] = None,
    collected_metrics_doc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not generated_at:
        generated_at = utc_now()
    if not benchmark_run_id:
        benchmark_run_id = generate_run_id(generated_at)
    if harness is None:
        harness = {"version": HARNESS_VERSION, "source_sha256": source_sha256()}

    resolved_metrics = {
        "prompt_tokens_per_second": 125.4 if status == "PASS" else None,
        "generation_tokens_per_second": 42.1 if status == "PASS" else None,
        "ttft_ms": 35.8 if status == "PASS" else None,
        "vram_gib_per_gpu": 14.2 if status == "PASS" else None,
        "system_ram_gib": 6.5 if status == "PASS" else None,
        "gpu_temperature_c": 62.0 if status == "PASS" else None,
        "gpu_power_watts": 185.0 if status == "PASS" else None,
        "gpu_utilization_percent": None,
        "gpu_memory_percent": None,
    }
    if metrics:
        resolved_metrics.update(metrics)

    if mode == "simulated" and status == "PASS":
        status = "SIMULATED_PASS"

    expected_values = {
        "prompt_tokens_per_second": 100.0,
        "generation_tokens_per_second": None,
        "ttft_ms": 50.0,
        "vram_gib_per_gpu": 16.0,
        "system_ram_gib": 8.0,
        "gpu_temperature_c": 75.0,
        "gpu_power_watts": 225.0,
        "gpu_utilization_percent": 100.0,
        "gpu_memory_percent": 100.0,
    }
    units = {
        "prompt_tokens_per_second": "tokens/sec",
        "generation_tokens_per_second": "tokens/sec",
        "ttft_ms": "ms",
        "vram_gib_per_gpu": "GiB",
        "system_ram_gib": "GiB",
        "gpu_temperature_c": "C",
        "gpu_power_watts": "W",
        "gpu_utilization_percent": "%",
        "gpu_memory_percent": "%",
    }

    is_simulated_pass = status == "SIMULATED_PASS"
    is_real_pass = (status == "PASS" and mode == "real")

    def _metric(key: str) -> Dict[str, Any]:
        observed = resolved_metrics.get(key)
        if is_real_pass:
            if key in ("vram_gib_per_gpu", "gpu_power_watts", "gpu_utilization_percent", "gpu_memory_percent"):
                return _telemetry_metric(
                    expected_values[key], units[key], classification="UNSUPPORTED",
                    reason="not exposed by this platform in a measurable form",
                )
            if observed is None:
                return _telemetry_metric(
                    expected_values[key], units[key], classification="UNAVAILABLE",
                    reason="not measured in this run",
                )
            return _telemetry_metric(
                expected_values[key], units[key], measured=float(observed), classification="MEASURED",
            )
        if is_simulated_pass:
            if observed is None:
                return _telemetry_metric(
                    expected_values[key], units[key], classification="UNAVAILABLE",
                    reason="simulated run; metric intentionally not measured",
                )
            return _telemetry_metric(
                expected_values[key], units[key], measured=float(observed), classification="MEASURED",
            )
        return _telemetry_metric(
            expected_values[key], units[key], classification="UNAVAILABLE",
            reason="not measured in this mode",
        )

    telemetry = {key: _metric(key) for key in expected_values}

    if is_simulated_pass:
        correctness_status = "SIMULATED_PASS"
        correctness_summary = (
            "Simulated placeholder metrics. NOT physical acceptance evidence; "
            "do not use for promotion decisions."
        )
    elif is_real_pass:
        correctness_status = "PASS"
        correctness_summary = "Received output passed the deterministic sentinel check."
    else:
        correctness_status = status if status in ("PASS", "FAIL") else "NOT_TESTED"
        correctness_summary = (
            "Benchmark check failed or unverified."
            if correctness_status in ("FAIL", "NOT_TESTED") else "Benchmark check passed."
        )

    triggered = (
        bool(safety and safety.get("thermal_abort_triggered"))
        or bool(safety and safety.get("telemetry_lost"))
        or bool(safety and safety.get("power_budget", {}).get("status") == "refused")
    )
    correctness = {
        "status": correctness_status,
        "mode": "sentinel" if not simulated else "none",
        "summary": correctness_summary,
        "expected": {"summary": "Deterministic output validation match"},
        "observed": {
            "summary": correctness_summary,
            "valid_responses": int(not triggered and is_real_pass),
            "invalid_responses": 0,
            "failed_requests": 0,
        },
    }

    failure_criteria: List[Dict[str, Any]] = []
    # NOT_RUN means nothing was executed: failures are recorded in
    # validity.reasons, never as executed-run criteria.
    if safety and status != "NOT_RUN":
        if safety.get("power_budget", {}).get("status") == "refused":
            failure_criteria.append({
                "criterion": "power_budget_exceeded",
                "status": "triggered",
                "reason": "Estimated platform draw exceeds the PSU capacity headroom.",
                "expected": {"summary": f"<= {safety['power_budget']['limit_watts']} W"},
                "observed": {"summary": f"{safety['power_budget']['estimated_watts']} W estimated"},
            })
        if safety.get("thermal_abort_triggered"):
            failure_criteria.append({
                "criterion": "thermal_abort",
                "status": "triggered",
                "reason": "GPU temperature reached the configured abort threshold during the run.",
                "expected": {"summary": f"< {safety['guardrails']['abort_temperature_c']} C"},
                "observed": {"summary": ">= abort temperature C"},
            })
        if safety.get("telemetry_lost"):
            failure_criteria.append({
                "criterion": "telemetry_lost",
                "status": "triggered",
                "reason": "Required fail-closed telemetry became unavailable during the run.",
                "expected": {"summary": "required GPU temperature sensors present for the whole run"},
                "observed": {"summary": "required sensor data lost"},
            })

    if validity is None:
        triggered_reasons: List[Dict[str, Any]] = []
        for criterion in failure_criteria:
            code = criterion["criterion"].upper()
            if code in FAILURE_TAXONOMY:
                triggered_reasons.append({
                    "code": code,
                    "detail": criterion.get("reason") or FAILURE_TAXONOMY[code],
                })
        validity_doc = compute_validity(status, triggered_reasons)
    else:
        validity_doc = validity

    if safety is None:
        safety = default_safety_block(mode=mode, runtime=runtime)

    return {
        "schema_version": "2.0.0",
        "benchmark_run_id": benchmark_run_id,
        "baseline_id": baseline_id,
        "config_id": config_id,
        "generated_at": generated_at,
        "started_at": generated_at,
        "completed_at": generated_at,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "simulated": simulated,
        "status": status,
        "identity": identity,
        "workload": workload,
        "harness": harness,
        "raw_artifacts": raw_artifacts,
        "component_files": component_files,
        "system": _live_system_provenance(hostname),
        "model": {
            "model_id": model_id,
            "revision": revision,
            "artifact_sha256": artifact_sha256,
            "quantization": quantization,
            "split_parameters": None if tensor_parallelism == 1 else {"strategy": "tensor_parallel", "shard_count": tensor_parallelism},
        },
        "execution": {
            "gpu_count": gpu_count,
            "tensor_parallelism": tensor_parallelism,
            "context_window_tokens": context_window_tokens,
        },
        "os_tuning": collect_os_tuning(
            os.environ.get("AIHOST_BENCH_TUNING_PROFILE", "unknown"),
            os.environ.get("AIHOST_BENCH_TUNING_REVISION"),
        ),
        "safety": safety,
        "duration": {
            "test_type": profile_name,
            "seconds": duration_seconds,
        },
        "telemetry": telemetry,
        "correctness": correctness,
        "failure_criteria": failure_criteria,
        "validity": validity_doc,
    }


# --------------------------------------------------------------- evidence io

def write_immutable_json(target: Path, payload: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite evidence {target}")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    tmp.unlink(missing_ok=True)


def write_jsonl(target: Path, records: List[Dict[str, Any]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite evidence {target}")
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def write_run_evidence(
    evidence_dir: Path,
    benchmark_run_id: str,
    docs: Dict[str, Any],
) -> Dict[str, Any]:
    """Write an immutable, run-addressed evidence bundle; fails if the run id
    already exists (O_EXCL semantics at the file layer)."""
    run_dir = evidence_dir / "benchmarks" / benchmark_run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    writes: Dict[str, Path] = {}
    for key in ("manifest", "environment", "workload", "metrics", "validity", "summary"):
        if docs.get(key) is None:
            continue
        writes[key] = run_dir / f"{key}.json"
        write_immutable_json(writes[key], docs[key])

    requests_written: List[Any] = []
    telemetry_written: List[Any] = []
    requests_path = raw_dir / "requests.jsonl"
    requests_path.write_text(json.dumps([], ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "run_dir": str(run_dir),
        "manifest": str(writes.get("manifest") or run_dir / "manifest.json"),
        "environment": str(writes.get("environment") or run_dir / "environment.json"),
        "workload": str(writes.get("workload") or run_dir / "workload.json"),
        "metrics": str(writes.get("metrics") or run_dir / "metrics.json"),
        "validity": str(writes.get("validity") or run_dir / "validity.json"),
        "summary": str(writes.get("summary") or run_dir / "summary.json"),
        "raw": str(raw_dir),
        "requests_jsonl": str(requests_path),
        "telemetry_jsonl": str(raw_dir / "telemetry.jsonl"),
    }


def write_simulated_projection(evidence_dir: Path, doc: Dict[str, Any]) -> Dict[str, Path]:
    """Simulated evidence is a mutable projection under benchmarks/simulated/,
    explicitly non-authoritative, so site.yml convergence can never touch a
    physical run directory."""
    simulated_dir = evidence_dir / "benchmarks" / "simulated"
    simulated_dir.mkdir(parents=True, exist_ok=True)
    target = simulated_dir / "benchmark.json"
    index = simulated_dir / "simulated-index.json"
    with target.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, indent=2) + "\n")
    index_payload = {
        "authoritative": False,
        "note": "Simulated projection. Not physical acceptance evidence.",
        "writes_to": str(target),
        "namespace": str(simulated_dir),
    }
    with index.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(index_payload, indent=2) + "\n")
    return {"benchmark": target, "index": index}


# ------------------------------------------------------------ real benchmark

def _run_one_request(
    args: argparse.Namespace,
    api_key: Optional[str],
    prompt_text: str,
    sentinel: Optional[str],
    request_id: str,
    sample_class: str,
    index: int,
) -> Dict[str, Any]:
    if args.runtime == "llama":
        return probe_llama_completion(args.base_url, api_key, prompt_text, args.max_new_tokens, args.request_timeout)
    return stream_vllm_completion(
        args.base_url, api_key, args.model, prompt_text,
        args.max_new_tokens, args.request_timeout,
        sentinel=sentinel, request_id=request_id, sample_class=sample_class,
    )


def run_real_benchmark(args: argparse.Namespace) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Returns (run_card, raw_request_records, telemetry_summary)."""
    gpu_count = args.gpu_count
    budget = evaluate_power_budget(
        gpu_count=gpu_count,
        gpu_tdp_watts=args.gpu_tdp_watts,
        psu_capacity_watts=args.psu_capacity_watts,
        base_power_watts=args.system_base_power_watts,
        headroom_pct=args.power_headroom_pct,
    )
    sampler = TelemetrySampler(interval_sec=1.0, abort_threshold_c=args.abort_temperature_c)
    api_key = None
    if args.auth_env_file:
        api_key = load_api_key_from_env_file(args.auth_env_file, args.api_key_env)

    guardrails = {
        "psu_capacity_watts": args.psu_capacity_watts,
        "gpu_tdp_watts_per_gpu": args.gpu_tdp_watts,
        "system_base_power_watts": args.system_base_power_watts,
        "power_headroom_pct": args.power_headroom_pct,
        "abort_temperature_c": args.abort_temperature_c,
        "telemetry_required": True,
    }
    safety_block = {
        "mode": "real",
        "runtime": args.runtime,
        "guardrails": guardrails,
        "power_budget": budget,
        "thermal_abort_triggered": False,
        "telemetry_lost": False,
        "telemetry_source": "unavailable",
        "peak_gpu_temperature_c": None,
        "per_gpu_telemetry": [],
    }

    triggered_reasons: List[Dict[str, Any]] = []
    interrupted = False

    if budget["status"] == "refused":
        triggered_reasons.append({
            "code": "POWER_BUDGET_EXCEEDED",
            "detail": (f"estimated {budget['estimated_watts']}W exceeds "
                       f"headroom-limited {budget['limit_watts']}W"),
        })
        safety_block["power_budget"] = budget
        doc = build_benchmark_document(
            profile_name=args.profile,
            hostname=args.hostname,
            git_sha=args.git_sha,
            simulated=False,
            model_id=args.model,
            revision=args.revision,
            artifact_sha256=args.artifact_sha256,
            quantization=args.quantization,
            gpu_count=gpu_count,
            tensor_parallelism=args.tensor_parallelism,
            context_window_tokens=args.context_window_tokens,
            duration_seconds=args.duration,
            status="NOT_RUN",
            mode="real",
            runtime=args.runtime,
            safety=safety_block,
            metrics={},
            generated_at=args.generated_at,
            benchmark_run_id=args.run_id,
            baseline_id=args.baseline_id,
            config_id=args.config_id,
            git_dirty=bool(args.git_dirty),
            validity=compute_validity("NOT_RUN", triggered_reasons),
        )
        return doc, [], build_metrics_document(args.run_id or "run", [])

    identity = collect_live_identity(
        base_url=args.base_url,
        api_key=api_key,
        model_expected=args.model,
        service_unit=args.service_unit,
        container_name=args.container_name,
    )
    identity["service_unit"] = args.service_unit
    identity["api_key_configured"] = api_key is not None

    prompted = build_deterministic_prompt(
        prompt_class=args.prompt_class,
        target_tokens=PROMPT_CLASSES.get(args.prompt_class, PROMPT_CLASSES["short"]),
        base_url=args.base_url,
        api_key=api_key,
        model=args.model,
        max_deviation_pct=args.max_deviation_pct,
        tokenize_timeout=args.request_timeout,
    )
    if prompted.get("token_source") == "server_tokenize" and args.prompt_class != "fixed_custom":
        target = PROMPT_CLASSES.get(args.prompt_class, 1)
        if prompted["deviation_pct"] is not None and prompted["deviation_pct"] > args.max_deviation_pct:
            triggered_reasons.append({
                "code": "WORKLOAD_TOKEN_DEVIATION",
                "detail": (f"observed {prompted['observed_tokens']} vs target {target} "
                           f"({prompted['deviation_pct']}%, > {args.max_deviation_pct}%)"),
            })

    prompt_text = prompted["prompt_text"]
    sentinel = None
    if args.correctness_sentinel:
        sentinel = build_sentinel(args.prompt_class, args.run_id or "run")
        prompt_text = f"{prompt_text}\n\nReply beginning with the marker {sentinel}.\n"

    if args.model not in (identity.get("model_observed") or []):
        triggered_reasons.append({
            "code": "MODEL_IDENTITY_CHANGED",
            "detail": f"served models {identity.get('model_observed')} do not include expected {args.model}",
        })

    identity_reasons = identity_requires_fail_closed(identity, gpu_count)
    for reason in identity_reasons:
        triggered_reasons.append({"code": "SERVICE_UNREACHABLE" if "served model" in reason else "HARNESS_ERROR", "detail": reason})

    sampler.start()
    record_request_id = 0
    records: List[Dict[str, Any]] = []
    warmup_count = int(args.warmup_requests)
    request_count = int(args.requests)
    concurrency = max(int(args.concurrency), 1)

    started_wall = time.monotonic()
    interruption: Optional[str] = None
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for i in range(request_count):
                sample_class = "warmup" if i < warmup_count else "measured"
                request_id = f"{args.run_id or 'run'}-{i:04d}"
                futures.append(executor.submit(
                    _run_one_request, args, api_key, prompt_text, sentinel,
                    request_id, sample_class, i,
                ))
            for future in futures:
                if sampler.aborted:
                    safety_block["thermal_abort_triggered"] = True
                    triggered_reasons.append({
                        "code": "SAFETY_ABORT",
                        "detail": "GPU temperature reached abort threshold",
                    })
                    break
                try:
                    records.append(future.result())
                except Exception as error:  # noqa: BLE001
                    records.append({
                        "status": "error", "reason": f"harness error: {error}",
                        "failure_code": "HARNESS_ERROR", "sample_class": "measured", "request_id": f"err-{i}",
                    })
    except KeyboardInterrupt:
        interrupted = True
        interruption = "interrupted by user"
    finally:
        ended_wall = time.monotonic()
        sampler.stop_event.set()
        if sampler.is_alive():
            sampler.join(timeout=3)

    group_wall_seconds = max(ended_wall - started_wall, 1e-6)
    safety_block["telemetry_source"] = sampler.telemetry_source
    safety_block["peak_gpu_temperature_c"] = sampler.max_temperature()
    safety_block["per_gpu_telemetry"] = [
        {"gpu_index": gpu.get("gpu_index", 0), "temperature_c": sampler.per_gpu_last_temp.get(gpu.get("card"))}
        for gpu in (identity.get("gpu_identity") or [])
    ]

    topology_count = len(identity.get("gpu_identity") or [])
    if topology_count < gpu_count:
        triggered_reasons.append({
            "code": "TP_TOPOLOGY_CHANGED",
            "detail": f"expected {gpu_count} GPUs, discovered {topology_count}",
        })
    if sampler.required_sensor_present is False and gpu_count >= 1:
        safety_block["telemetry_lost"] = True
        triggered_reasons.append({
            "code": "TELEMETRY_LOST",
            "detail": "required fail-closed GPU temperature sensor was never observed",
        })
    elif sampler.aborted:
        safety_block["thermal_abort_triggered"] = True
        triggered_reasons.append({"code": "SAFETY_ABORT", "detail": "GPU temperature reached abort threshold"})

    if sampler.aborted:
        safety_block["thermal_abort_triggered"] = True

    metrics_doc = build_metrics_document(args.run_id or "run", records)
    metrics_doc["aggregates"]["group_wall_seconds"] = round(group_wall_seconds, 6)
    metrics_doc["aggregates"]["requests_per_second"] = (
        round(metrics_doc["counts"]["measured"] / group_wall_seconds, 6)
        if group_wall_seconds > 0 else None
    )
    metrics_doc["aggregates"]["wall_seconds"] = round(group_wall_seconds, 6)

    measured_records = [r for r in records if r.get("status") == "ok" and r.get("sample_class") == "measured"]
    mean_gen = (
        statistics.fmean(r["generation_tokens_per_second"] for r in measured_records)
        if measured_records else 0.0
    )
    correctness_invalid = sum(1 for r in measured_records if r.get("correctness") == "RESPONSE_INVALID")

    metrics_values: Dict[str, Optional[float]] = {
        "generation_tokens_per_second": mean_gen if measured_records else None,
        "ttft_ms": (
            statistics.median([r["ttft_ms"] for r in measured_records]) if measured_records else None
        ),
    }

    if interrupted:
        status = "INCOMPLETE"
    elif not measured_records:
        status = "NOT_RUN"
        if not any(r.get("code") == "POWER_BUDGET_EXCEEDED" for r in triggered_reasons):
            triggered_reasons.append({
                "code": "SERVICE_UNREACHABLE",
                "detail": "no measured request completed; cannot compute a result",
            })
    elif triggered_reasons:
        status = "FAIL"
    elif correctness_sentinel_enabled(args) and correctness_invalid == len(measured_records):
        status = "FAIL"
        triggered_reasons.append({
            "code": "CORRECTNESS_FAILURE",
            "detail": "every measured response failed the deterministic sentinel check",
        })
    else:
        # Throughput is an observed performance metric, not a validity gate.
        # B0 establishes distributions before a reference is selected.
        status = "PASS"

    if interrupted:
        final_validity = compute_validity("INCOMPLETE", triggered_reasons, interrupted=True)
    elif status == "NOT_RUN":
        final_validity = compute_validity("NOT_RUN", triggered_reasons, interrupted=False)
    elif status == "FAIL":
        final_validity = compute_validity("FAIL", triggered_reasons, interrupted=False)
    else:
        final_validity = {"state": "VALID", "reasons": [], "interrupted": False}

    correctness_counts = {
        "RESPONSE_RECEIVED": 0, "RESPONSE_VALID": 0, "RESPONSE_INVALID": 0, "REQUEST_FAILED": 0,
    }
    for r in records:
        result_code = r.get("correctness")
        if result_code is None:
            result_code = "RESPONSE_RECEIVED" if r.get("status") == "ok" else "REQUEST_FAILED"
        if result_code in correctness_counts:
            correctness_counts[result_code] += 1

    doc = build_benchmark_document(
        profile_name=args.profile,
        hostname=args.hostname,
        git_sha=args.git_sha,
        simulated=False,
        model_id=args.model,
        revision=args.revision,
        artifact_sha256=args.artifact_sha256,
        quantization=args.quantization,
        gpu_count=gpu_count,
        tensor_parallelism=args.tensor_parallelism,
        context_window_tokens=args.context_window_tokens,
        duration_seconds=args.duration,
        status="PASS" if status == "PASS" else ("INCOMPLETE" if interrupted else ("NOT_RUN" if status == "NOT_RUN" else "FAIL")),
        mode="real",
        runtime=args.runtime,
        safety=safety_block,
        metrics=metrics_values,
        generated_at=args.generated_at,
        benchmark_run_id=args.run_id,
        baseline_id=args.baseline_id,
        config_id=args.config_id,
        git_dirty=bool(args.git_dirty),
        identity=identity,
        workload=build_workload_document(
            args.run_id or "run", prompted, args.prompt_class, args.output_class,
            args.max_new_tokens, concurrency, request_count, warmup_count,
            args.max_deviation_pct, args.model, profile=args.profile,
        ),
        harness={"version": HARNESS_VERSION, "source_sha256": source_sha256()},
        validity=final_validity,
    )
    doc["correctness"]["observed"]["valid_responses"] = correctness_counts["RESPONSE_VALID"]
    doc["correctness"]["observed"]["invalid_responses"] = correctness_counts["RESPONSE_INVALID"]
    doc["correctness"]["observed"]["failed_requests"] = correctness_counts["REQUEST_FAILED"]
    doc["metrics"] = {
        "requests_per_second": metrics_doc["aggregates"]["requests_per_second"],
        "decode_tokens_per_second_p50": metrics_doc["distributions"]["decode_tokens_per_second"]["p50"],
        "ttft_ms_p95": metrics_doc["distributions"]["ttft_ms"]["p95"],
    }
    return doc, records, metrics_doc


def correctness_sentinel_enabled(args: argparse.Namespace) -> bool:
    return args.runtime == "vllm" and bool(getattr(args, "correctness_sentinel", False))


# ------------------------------------------------------------------- mock modes

def run_simulated_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    doc = build_benchmark_document(
        profile_name=args.profile,
        hostname=args.hostname,
        git_sha=args.git_sha,
        simulated=True,
        model_id=args.model or "Qwen/Qwen2.5-Coder-7B-Instruct",
        revision=args.revision,
        artifact_sha256=args.artifact_sha256,
        quantization=args.quantization,
        gpu_count=args.gpu_count,
        tensor_parallelism=args.tensor_parallelism,
        context_window_tokens=args.context_window_tokens,
        duration_seconds=args.duration,
        status="PASS",
        mode="simulated",
        runtime="simulated",
        generated_at=args.generated_at,
        benchmark_run_id=args.run_id,
        baseline_id=args.baseline_id,
        config_id=args.config_id,
        git_dirty=bool(args.git_dirty),
        validity=compute_validity("SIMULATED_PASS", []),
    )
    return doc


def _write_output_path(output: Optional[str], doc: Dict[str, Any]) -> None:
    if not output:
        print(json.dumps(doc, indent=2))
        return
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inference benchmark harness")
    parser.add_argument("--profile", default="small", help="Benchmark profile name")
    parser.add_argument("--hostname", default="ai-p620-01", help="Host name")
    parser.add_argument("--git-sha", default="0000000000000000000000000000000000000000", help="Git SHA")
    parser.add_argument("--simulated", action="store_true", help="Simulated run")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--evidence-dir", default=None, help="Evidence root for immutable run bundles")
    parser.add_argument("--mode", choices=["simulated", "real"], default=None,
                        help="Execution mode; real drives a live server and never fabricates data")
    parser.add_argument("--runtime", choices=["vllm", "llama"], default="vllm", help="Real-mode backend")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Inference endpoint base URL")
    parser.add_argument("--auth-env-file", default=None, help="KEY=VALUE env file holding the API key")
    parser.add_argument("--api-key-env", default="VLLM_API_KEY", help="Env var name inside auth env file")
    parser.add_argument("--model", default=None, help="Model id for OpenAI-compatible requests")
    parser.add_argument("--revision", default="main", help="Model revision label")
    parser.add_argument("--artifact-sha256",
                        default="0000000000000000000000000000000000000000000000000000000000000000")
    parser.add_argument("--quantization", default="FP16")
    parser.add_argument("--prompt", default="Write a short sentence about efficient inference.")
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--duration", type=float, default=30.0, help="Wall-clock budget seconds")
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--tensor-parallelism", type=int, default=1)
    parser.add_argument("--context-window-tokens", type=int, default=4096)
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--psu-capacity-watts", type=float, default=1000.0)
    parser.add_argument("--gpu-tdp-watts", type=float, default=225.0)
    parser.add_argument("--system-base-power-watts", type=float, default=250.0)
    parser.add_argument("--power-headroom-pct", type=float, default=20.0)
    parser.add_argument("--abort-temperature-c", type=float, default=90.0)
    # remediation: immutable run addressing + baseline identity
    parser.add_argument("--run-id", default=None, help="Explicit benchmark run id (defaults to generated)")
    parser.add_argument("--baseline-id", default="B0", help="Baseline identity id")
    parser.add_argument("--config-id", default="b0", help="Runtime configuration identity id")
    parser.add_argument("--git-dirty", action="store_true", help="Mark git tree dirty")
    parser.add_argument("--generated-at", default=None, help="Override generated timestamp (tests)")
    # remediation: workload shaping
    parser.add_argument("--prompt-class", choices=list(PROMPT_CLASSES.keys()) + ["fixed_custom"], default="short")
    parser.add_argument("--output-class", choices=list(OUTPUT_CLASSES.keys()), default="short")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--requests", type=int, default=5)
    parser.add_argument("--warmup-requests", type=int, default=0)
    parser.add_argument("--max-deviation-pct", type=float, default=5.0)
    parser.add_argument("--correctness-sentinel", action="store_true",
                        help="Prefix prompts with a deterministic sentinel and validate responses")
    parser.add_argument("--service-unit", default="vllm.service")
    parser.add_argument("--container-name", default="vllm-xpu")
    args = parser.parse_args()

    if args.mode == "real":
        if not args.model:
            parser.error("--model is required in real mode so results are attributable")
        if args.requests < 1:
            parser.error("--requests must be at least 1 in real mode")
        if args.concurrency < 1:
            parser.error("--concurrency must be at least 1 in real mode")
        if not args.run_id:
            args.run_id = generate_run_id()
        if args.prompt_class != "fixed_custom":
            target = PROMPT_CLASSES.get(args.prompt_class, PROMPT_CLASSES["short"])
            if not target:
                parser.error(f"unknown prompt class {args.prompt_class}")
        doc, records, metrics_doc = run_real_benchmark(args)
        _write_output_path(args.output, doc)
        if args.evidence_dir:
            manifest_doc = dict(doc)
            manifest_doc["raw_artifacts"] = {"requests_jsonl": "raw/requests.jsonl", "telemetry_jsonl": "raw/telemetry.jsonl"}
            paths = write_run_evidence(
                Path(args.evidence_dir),
                args.run_id,
                {
                    "manifest": manifest_doc,
                    "environment": build_environment_document(args.run_id, doc.get("identity", {}),
                                                              args.hostname, doc.get("system", {})),
                    "workload": doc.get("workload"),
                    "metrics": metrics_doc,
                    "validity": build_validity_document(args.run_id, doc.get("validity", {})),
                    "summary": build_summary_document(args.run_id, doc, metrics_doc),
                },
            )
            request_path = paths.get("requests_jsonl")
            import pathlib as _pl
            _pl.Path(paths["raw"]).mkdir(exist_ok=True)
            req_target = _pl.Path(request_path)
            _ = req_target.write_text(
                "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            telemetry_target = _pl.Path(paths["telemetry_jsonl"])
            telemetry_target.write_text("", encoding="utf-8")
            for key in sorted(paths):
                print(f"evidence:{key}={paths[key]}")
        return 0 if doc["status"] in ("PASS", "SIMULATED_PASS") else 1

    # simulated
    doc = run_simulated_benchmark(args)
    _write_output_path(args.output, doc)
    if args.evidence_dir:
        write_simulated_projection(Path(args.evidence_dir), doc)
    return 0 if doc["status"] in ("PASS", "SIMULATED_PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
