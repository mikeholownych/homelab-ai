#!/usr/bin/env python3
"""Inference Benchmark Runner and Evidence Generator.

Two modes:
  simulated (default until physical acceptance)  - deterministic placeholder
                                                   metrics, schema-valid.
  real                                           - drives a live OpenAI-compatible
                                                   endpoint or llama.cpp server,
                                                   samples thermals/power from
                                                   hwmon, enforces guardrails,
                                                   and never fabricates results.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


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
            ["systemctl", "is-active", "irqbalance"], capture_output=True, text=True
        ).stdout.strip() or None
    except OSError:
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


class TelemetrySampler(threading.Thread):
    """Samples GPU temperature/power and host RAM while a benchmark runs."""

    def __init__(self, interval_sec: float = 1.0, abort_threshold_c: Optional[float] = None):
        super().__init__(daemon=True)
        self.interval_sec = interval_sec
        self.abort_threshold_c = abort_threshold_c
        self.stop_event = threading.Event()
        self.gpu_temps_c: List[float] = []
        self.gpu_powers_w: List[float] = []
        self.mem_available_gib: List[float] = []
        self.telemetry_source = "unavailable"
        self.aborted = False

    @staticmethod
    def _first_int(path: Path) -> Optional[float]:
        try:
            return float(path.read_text(errors="replace").strip())
        except (OSError, ValueError):
            return None

    def sample_once(self) -> None:
        hwmons = discover_gpu_hwmons()
        if not hwmons:
            self.telemetry_source = "unavailable"
        else:
            self.telemetry_source = "hwmon"
        for hwmon in hwmons:
            for temp_file in sorted(hwmon.glob("temp*_input")):
                raw = self._first_int(temp_file)
                if raw is not None:
                    celsius = raw / 1000.0
                    self.gpu_temps_c.append(celsius)
            for power_name in ("power1_input", "power2_input"):
                raw = self._first_int(hwmon / power_name)
                if raw is not None:
                    self.gpu_powers_w.append(raw / 1_000_000.0)
        meminfo = _read_sysfs("/proc/meminfo")
        if meminfo:
            match = re.search(r"MemAvailable:\s+(\d+) kB", meminfo)
            if match:
                self.mem_available_gib.append(int(match.group(1)) / 1024 / 1024)

    def max_temperature(self) -> Optional[float]:
        return max(self.gpu_temps_c) if self.gpu_temps_c else None

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


def stream_vllm_completion(
    base_url: str,
    api_key: Optional[str],
    model: str,
    prompt: str,
    max_new_tokens: int,
    timeout_sec: float,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1/completions"
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "max_tokens": max_new_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers)

    started = time.perf_counter()
    ttft_ms: Optional[float] = None
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
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
                    if ttft_ms is None and (choices[0].get("text") or (choices[0].get("delta") or {}).get("content")):
                        ttft_ms = (time.perf_counter() - started) * 1000.0
    except urllib.error.HTTPError as error:
        return {"status": "error", "reason": f"http {error.code}: {error.reason}"}
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return {"status": "error", "reason": f"connection failure: {error}"}

    elapsed_s = time.perf_counter() - started
    if ttft_ms is None or completion_tokens in (None, 0):
        missing = "no token stream observed"
        return {"status": "error", "reason": missing}
    generation_elapsed_s = max(elapsed_s - (ttft_ms / 1000.0), 1e-6)
    return {
        "status": "ok",
        "ttft_ms": ttft_ms,
        "completion_tokens": int(completion_tokens),
        "prompt_tokens": int(prompt_tokens or 0),
        "generation_seconds": generation_elapsed_s,
        "elapsed_seconds": elapsed_s,
        "generation_tokens_per_second": completion_tokens / generation_elapsed_s,
        "finish_reason": finish_reason,
    }


def probe_llama_completion(
    base_url: str,
    api_key: Optional[str],
    prompt: str,
    max_new_tokens: int,
    timeout_sec: float,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/completion"
    body = json.dumps({"prompt": prompt, "n_predict": max_new_tokens, "stream": False}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return {"status": "error", "reason": f"http {error.code}: {error.reason}"}
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as error:
        return {"status": "error", "reason": f"request failure: {error}"}
    elapsed_s = time.perf_counter() - started
    timings = payload.get("timings") or {}
    predicted_per_second = timings.get("predicted_per_second")
    predicted_ms = timings.get("predicted_ms")
    tokens = payload.get("tokens_predicted")
    if predicted_per_second is None and predicted_ms and tokens:
        predicted_per_second = tokens / (predicted_ms / 1000.0)
    if predicted_per_second is None or not tokens:
        return {"status": "error", "reason": "server did not report token timings"}
    ttft_ms = elapsed_s * 1000.0 - (timings.get("prompt_ms") or 0.0)
    return {
        "status": "ok",
        "ttft_ms": ttft_ms,
        "completion_tokens": int(tokens),
        "generation_seconds": (predicted_ms or 0.0) / 1000.0,
        "generation_tokens_per_second": predicted_per_second,
        "elapsed_seconds": elapsed_s,
    }


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
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    lines = [ln for ln in output.splitlines() if ln]
    return lines[0] if lines else None


def _live_system_provenance(hostname: str) -> Dict[str, Any]:
    """Read live system identity; 'unknown' beats fabrication."""
    try:
        kernel = subprocess.run(
            ["uname", "-r"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        kernel = "unknown"
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


# ------------------------------------------------------------ document build

def _metric(expected_value: float, unit: str, observed: Optional[float]) -> Dict[str, Any]:
    if observed is None:
        return {
            "expected": {"value": expected_value, "unit": unit},
            "observed": {"status": "unavailable", "reason": "not measured in this mode"},
        }
    return {
        "expected": {"value": expected_value, "unit": unit},
        "observed": {"value": round(observed, 2), "unit": unit},
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
) -> Dict[str, Any]:
    if not generated_at:
        generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    resolved_metrics = {
        "prompt_tokens_per_second": 125.4 if status == "PASS" else None,
        "generation_tokens_per_second": 42.1 if status == "PASS" else None,
        "ttft_ms": 35.8 if status == "PASS" else None,
        "vram_gib_per_gpu": 14.2 if status == "PASS" else None,
        "system_ram_gib": 6.5 if status == "PASS" else None,
        "gpu_temperature_c": 62.0 if status == "PASS" else None,
        "gpu_power_watts": 185.0 if status == "PASS" else None,
    }
    if metrics:
        resolved_metrics.update(metrics)

    expected_values = {
        "prompt_tokens_per_second": 100.0,
        "generation_tokens_per_second": 30.0,
        "ttft_ms": 50.0,
        "vram_gib_per_gpu": 16.0,
        "system_ram_gib": 8.0,
        "gpu_temperature_c": 75.0,
        "gpu_power_watts": 225.0,
    }
    units = {
        "prompt_tokens_per_second": "tokens/sec",
        "generation_tokens_per_second": "tokens/sec",
        "ttft_ms": "ms",
        "vram_gib_per_gpu": "GiB",
        "system_ram_gib": "GiB",
        "gpu_temperature_c": "C",
        "gpu_power_watts": "W",
    }
    telemetry = {
        key: _metric(expected_values[key], units[key], resolved_metrics.get(key))
        for key in expected_values
    }

    if mode == "simulated" and status == "PASS":
        status = "SIMULATED_PASS"
    correctness_status = status if status in ("PASS", "FAIL", "SIMULATED_PASS") else "NOT_TESTED"
    correctness = {
        "status": correctness_status,
        "summary": {
            "SIMULATED_PASS": (
                "Simulated placeholder metrics. NOT physical acceptance evidence; "
                "do not use for promotion decisions."
            ),
            "PASS": "Output tokens match expected deterministic output.",
        }.get(correctness_status, "Benchmark check failed or unverified."),

        "expected": {"summary": "Deterministic output validation match"},
        "observed": {
            "summary": "Output verified" if correctness_status == "PASS" else "No valid output verified"
        },
    }

    failure_criteria: List[Dict[str, Any]] = []
    if status != "FAIL":
        pass  # NOT_RUN/PASS documents carry no triggered criteria
    elif safety and safety.get("thermal_abort_triggered"):
        failure_criteria.append({
            "criterion": "thermal_abort",
            "status": "triggered",
            "reason": "GPU temperature reached the configured abort threshold during the run.",
            "expected": {"summary": f"< {safety['guardrails']['abort_temperature_c']} C"},
            "observed": {"summary": f">= {safety['guardrails']['abort_temperature_c']} C"},
        })
    if status == "FAIL" and safety and safety.get("power_budget", {}).get("status") == "refused":
        failure_criteria.append({
            "criterion": "power_budget_exceeded",
            "status": "triggered",
            "reason": "Estimated platform draw exceeds the PSU capacity headroom; refusing to run.",
            "expected": {"summary": f"<= {safety['power_budget']['limit_watts']} W"},
            "observed": {"summary": f"{safety['power_budget']['estimated_watts']} W estimated"},
        })
    if status == "FAIL" and not failure_criteria:
        failure_criteria.append({
            "criterion": "throughput_degradation",
            "status": "triggered",
            "reason": "Observed generation throughput fell below minimum baseline.",
            "expected": {"summary": ">= 30.0 tokens/sec"},
            "observed": {"summary": "0.0 tokens/sec"},
        })

    if safety is None:
        safety = default_safety_block(mode=mode, runtime=runtime)

    return {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "git_sha": git_sha,
        "simulated": simulated,
        "status": status,
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
        },
        "power_budget": {"status": "not_evaluated", "estimated_watts": None, "limit_watts": None},
        "thermal_abort_triggered": False,
        "telemetry_source": "unavailable",
        "peak_gpu_temperature_c": None,
    }


def run_real_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
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
    }
    safety_block = {
        "mode": "real",
        "runtime": args.runtime,
        "guardrails": guardrails,
        "power_budget": budget,
        "thermal_abort_triggered": False,
        "telemetry_source": "unavailable",
        "peak_gpu_temperature_c": None,
    }

    def finish(status: str, metrics: Dict[str, Optional[float]], extra_runtime: str) -> Dict[str, Any]:
        safety_block["thermal_abort_triggered"] = sampler.aborted
        safety_block["telemetry_source"] = sampler.telemetry_source
        safety_block["peak_gpu_temperature_c"] = sampler.max_temperature()
        return build_benchmark_document(
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
            status=status,
            mode="real",
            runtime=extra_runtime,
            safety=safety_block,
            metrics=metrics,
        )

    if budget["status"] == "refused":
        return finish("NOT_RUN", {}, args.runtime)

    sampler.start()
    records: List[Dict[str, Any]] = []
    deadline = time.monotonic() + args.duration
    iterations = 0
    while iterations < args.iterations and time.monotonic() < deadline:
        if sampler.aborted:
            break
        if args.runtime == "llama":
            result = probe_llama_completion(
                args.base_url, api_key, args.prompt, args.max_new_tokens, args.request_timeout
            )
        else:
            result = stream_vllm_completion(
                args.base_url, api_key, args.model, args.prompt,
                args.max_new_tokens, args.request_timeout,
            )
        if result["status"] != "ok":
            sampler.stop_event.set()
            sampler.join(timeout=3)
            return finish("NOT_RUN", {}, args.runtime)
        records.append(result)
        iterations += 1
    sampler.stop_event.set()
    if sampler.is_alive():
        sampler.join(timeout=3)

    if sampler.aborted:
        return finish("FAIL", {}, args.runtime)
    if iterations == 0:
        return finish("NOT_RUN", {}, args.runtime)

    gen_rates = [r["generation_tokens_per_second"] for r in records]
    ttfts = [r["ttft_ms"] for r in records]
    prompt_rates = [
        r["prompt_tokens"] / r["generation_seconds"]
        for r in records if r.get("prompt_tokens") and r["generation_seconds"] > 0
    ]
    mean_gen = statistics.fmean(gen_rates)
    status = "PASS" if mean_gen >= args.min_generation_tokens_per_sec else "FAIL"
    metrics = {
        "generation_tokens_per_second": mean_gen,
        "ttft_ms": statistics.median(ttfts),
        "gpu_temperature_c": sampler.max_temperature(),
        "gpu_power_watts": (
            statistics.fmean(sampler.gpu_powers_w) if sampler.gpu_powers_w else None
        ),
        "system_ram_gib": None,
        "prompt_tokens_per_second": statistics.fmean(prompt_rates) if prompt_rates else None,
        "vram_gib_per_gpu": None,
    }
    return finish(status, metrics, args.runtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inference benchmark harness")
    parser.add_argument("--profile", default="small", help="Benchmark profile name")
    parser.add_argument("--hostname", default="ai-p620-01", help="Host name")
    parser.add_argument("--git-sha", default="0000000000000000000000000000000000000000", help="Git SHA")
    parser.add_argument("--simulated", action="store_true", help="Simulated run")
    parser.add_argument("--output", default=None, help="Output JSON path")
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
    parser.add_argument("--min-generation-tokens-per-sec", type=float, default=30.0)
    parser.add_argument("--tensor-parallelism", type=int, default=1)
    parser.add_argument("--context-window-tokens", type=int, default=4096)
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--psu-capacity-watts", type=float, default=1000.0)
    parser.add_argument("--gpu-tdp-watts", type=float, default=225.0)
    parser.add_argument("--system-base-power-watts", type=float, default=250.0)
    parser.add_argument("--power-headroom-pct", type=float, default=20.0)
    parser.add_argument("--abort-temperature-c", type=float, default=90.0)
    args = parser.parse_args()

    if args.mode == "real":
        if not args.model:
            parser.error("--model is required in real mode so results are attributable")
        doc = run_real_benchmark(args)
    else:
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
        )

    formatted_json = json.dumps(doc, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted_json, encoding="utf-8")

    print(formatted_json)
    return 0 if doc["status"] in ("PASS", "SIMULATED_PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
