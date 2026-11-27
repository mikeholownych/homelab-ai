#!/usr/bin/env python3
"""Repeatable NVMe MoE expert-streaming benchmark harness for homelab-ai.

Isolates three distinct execution phases on a 4K-token prompt:
  1. Prefill (4K prompt): actual_prompt_tokens / ttft_s
  2. Warmup decode (tokens 1..128): absorbs cold Tier-1/Tier-0 cache population
  3. Steady-state decode (tokens 129..256): headline metric measuring steady-state
     decode throughput once expert cache residency stabilizes.

Supports two execution modes:
  - Live mode (--endpoint http://127.0.0.1:8080/v1/chat/completions):
      Streams SSE tokens with greedy decoding (temperature=0.0, top_k=1),
      EOS suppression (ignore_eos=True), and prefix cache disabled (cache_prompt=False).
  - Day-1 dry-run mode (--dry-run):
      Runs the live host hardware probe, non-destructive NVMe random-read probe,
      adaptive bypass planner (against synthetic 48 GiB / 84 GiB / 177B / 800B MoE
      footprints), and an end-to-end NVMeMoEStreamEngine direct-I/O 256-token decode
      simulation against a temporary mock GGUF MoE shard, emitting JSON + Prometheus metrics.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator_runtime.metrics import MetricsRegistry  # noqa: E402
from orchestrator_runtime.nvme_moe.gguf_index import (  # noqa: E402
    DIRECT_IO_BLOCK_SIZE,
    GGML_TYPE_Q4_K,
    GGUF_MAGIC,
    GGUF_TYPE_STRING,
    GGUF_TYPE_UINT32,
    MoEModelIndex,
    index_gguf_model,
)
from orchestrator_runtime.nvme_moe.hardware_probe import (  # noqa: E402
    GpuDeviceInfo,
    HardwareSnapshot,
    NVMeDriveProfile,
    plan_model_placement,
    probe_live_host_snapshot,
    probe_nvme_random_read,
    validate_loopback_bind,
)
from orchestrator_runtime.nvme_moe.io_engine import NVMeMoEStreamEngine  # noqa: E402
from orchestrator_runtime.nvme_moe.memory_arbiter import ExpertCache  # noqa: E402

DEFAULT_PROMPT_TOKENS = 4096
DEFAULT_WARMUP_TOKENS = 128
DEFAULT_MEASURE_TOKENS = 128  # tokens 129..256


@dataclass(frozen=True)
class PhaseMetrics:
    """Isolated timing and throughput metrics for prefill, warmup, and steady-state decode."""

    prompt_tokens: int
    total_generated_tokens: int
    warmup_tokens: int
    steady_tokens: int
    ttft_seconds: float
    prefill_tokens_per_sec: float
    warmup_decode_tokens_per_sec: float
    steady_decode_tokens_per_sec: float
    steady_itl_p50_ms: float
    steady_itl_p95_ms: float
    steady_itl_p99_ms: float


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank linear-interpolated percentile over a sorted sequence."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(math.floor(rank))
    hi = min(len(sorted_values) - 1, lo + 1)
    frac = rank - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


def compute_phase_metrics(
    *,
    prompt_tokens: int,
    t_submit: float,
    token_timestamps: list[float],
    warmup_tokens: int = DEFAULT_WARMUP_TOKENS,
) -> PhaseMetrics:
    """Compute prefill, warmup (1..warmup_tokens), and steady-state (warmup_tokens+1..N) rates."""
    if prompt_tokens <= 0:
        raise ValueError("prompt_tokens must be positive")
    n_tokens = len(token_timestamps)
    if n_tokens < warmup_tokens + 2:
        raise ValueError(
            f"need at least warmup_tokens + 2 ({warmup_tokens + 2}) generated tokens, got {n_tokens}"
        )

    ttft_s = max(1e-9, token_timestamps[0] - t_submit)
    prefill_tps = prompt_tokens / ttft_s

    warmup_elapsed = max(1e-9, token_timestamps[warmup_tokens - 1] - token_timestamps[0])
    warmup_tps = (warmup_tokens - 1) / warmup_elapsed if warmup_tokens > 1 else 0.0

    steady_start_idx = warmup_tokens  # 0-based index of token 129
    steady_count = n_tokens - warmup_tokens
    steady_elapsed = max(1e-9, token_timestamps[-1] - token_timestamps[steady_start_idx - 1])
    steady_tps = steady_count / steady_elapsed

    steady_itls_ms = sorted(
        max(0.0, (token_timestamps[i] - token_timestamps[i - 1]) * 1000.0)
        for i in range(steady_start_idx, n_tokens)
    )

    return PhaseMetrics(
        prompt_tokens=prompt_tokens,
        total_generated_tokens=n_tokens,
        warmup_tokens=warmup_tokens,
        steady_tokens=steady_count,
        ttft_seconds=round(ttft_s, 6),
        prefill_tokens_per_sec=round(prefill_tps, 3),
        warmup_decode_tokens_per_sec=round(warmup_tps, 3),
        steady_decode_tokens_per_sec=round(steady_tps, 3),
        steady_itl_p50_ms=round(percentile(steady_itls_ms, 50.0), 3),
        steady_itl_p95_ms=round(percentile(steady_itls_ms, 95.0), 3),
        steady_itl_p99_ms=round(percentile(steady_itls_ms, 99.0), 3),
    )


def build_deterministic_prompt(target_tokens: int = DEFAULT_PROMPT_TOKENS) -> str:
    """Build a deterministic synthetic engineering prompt sized near ``target_tokens``."""
    header = (
        "You are benchmarking steady-state NVMe MoE expert streaming decode throughput. "
        "Summarize the numbered systems telemetry invariants below in exhaustive technical detail.\n"
    )
    lines = [header]
    n_lines = max(16, target_tokens // 16)
    for idx in range(1, n_lines + 1):
        lines.append(
            f"Invariant {idx:04d}: direct-io shard alignment 4096B queue-depth 32 "
            f"routed-expert layer={(idx % 48):02d} slot={(idx * 7) % 128:03d}.\n"
        )
    return "".join(lines)


def _pack_gguf_str(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def build_synthetic_moe_gguf(
    path: Path,
    *,
    num_layers: int = 8,
    num_experts: int = 16,
    experts_used: int = 4,
    hidden_dim: int = 512,
    ffn_dim: int = 256,
    alignment: int = DIRECT_IO_BLOCK_SIZE,
) -> Path:
    """Create a valid GGUF v3 MoE file with real Q4_K-sized routed expert tensors."""
    kv_entries: list[tuple[str, int, bytes]] = [
        ("general.architecture", GGUF_TYPE_STRING, _pack_gguf_str("qwen3moe")),
        ("general.alignment", GGUF_TYPE_UINT32, struct.pack("<I", alignment)),
        ("qwen3moe.block_count", GGUF_TYPE_UINT32, struct.pack("<I", num_layers)),
        ("qwen3moe.expert_count", GGUF_TYPE_UINT32, struct.pack("<I", num_experts)),
        ("qwen3moe.expert_used_count", GGUF_TYPE_UINT32, struct.pack("<I", experts_used)),
    ]

    q4k_row_bytes = (hidden_dim // 256) * 144
    up_gate_expert_bytes = q4k_row_bytes * ffn_dim
    down_expert_bytes = ((ffn_dim // 256) * 144) * hidden_dim

    tensor_defs: list[tuple[str, tuple[int, ...], int, int]] = []
    running_offset = 0
    for layer in range(num_layers):
        attn_size = q4k_row_bytes * hidden_dim
        tensor_defs.append((f"blk.{layer}.attn_q.weight", (hidden_dim, hidden_dim), GGML_TYPE_Q4_K, running_offset))
        running_offset = ((running_offset + attn_size + alignment - 1) // alignment) * alignment

        for role, dims, expert_bytes in (
            ("ffn_up_exps", (hidden_dim, ffn_dim, num_experts), up_gate_expert_bytes),
            ("ffn_gate_exps", (hidden_dim, ffn_dim, num_experts), up_gate_expert_bytes),
            ("ffn_down_exps", (ffn_dim, hidden_dim, num_experts), down_expert_bytes),
        ):
            total_bytes = expert_bytes * num_experts
            tensor_defs.append((f"blk.{layer}.{role}.weight", dims, GGML_TYPE_Q4_K, running_offset))
            running_offset = ((running_offset + total_bytes + alignment - 1) // alignment) * alignment

    buf = bytearray()
    buf += GGUF_MAGIC
    buf += struct.pack("<IQQ", 3, len(tensor_defs), len(kv_entries))
    for key, vtype, encoded in kv_entries:
        buf += _pack_gguf_str(key)
        buf += struct.pack("<I", vtype)
        buf += encoded

    for name, dims, ggml_type, rel_offset in tensor_defs:
        buf += _pack_gguf_str(name)
        buf += struct.pack("<I", len(dims))
        for d in dims:
            buf += struct.pack("<Q", d)
        buf += struct.pack("<IQ", ggml_type, rel_offset)

    if len(buf) % alignment != 0:
        buf += b"\x00" * (alignment - (len(buf) % alignment))
    data_start = len(buf)
    total_file_size = data_start + running_offset
    if total_file_size % alignment != 0:
        total_file_size = ((total_file_size + alignment - 1) // alignment) * alignment

    with path.open("wb") as fh:
        fh.write(buf)
        remaining = total_file_size - len(buf)
        chunk = b"\x5a\xa5\x3c\xc3" * 1024
        while remaining > 0:
            to_write = min(remaining, len(chunk))
            fh.write(chunk[:to_write])
            remaining -= to_write

    return path


def _synthetic_footprint_index(
    template: MoEModelIndex,
    *,
    dense_bytes: int,
    routed_bytes: int,
    is_moe: bool,
    n_layers: int = 64,
    n_experts: int = 128,
) -> MoEModelIndex:
    """Create a lightweight MoEModelIndex sizing descriptor for placement scenario planning."""
    routed_layers = template.routed_layers if is_moe else {}
    return MoEModelIndex(
        shards=template.shards,
        architecture=template.architecture if is_moe else "llama",
        n_layers=n_layers,
        n_experts=n_experts if is_moe else 0,
        n_experts_used=8 if is_moe else 0,
        dense_bytes=dense_bytes,
        routed_bytes=routed_bytes if is_moe else 0,
        total_tensor_bytes=dense_bytes + (routed_bytes if is_moe else 0),
        latent_dim=4096,
        hidden_dim=4096,
        routed_layers=routed_layers,
        max_role_read_bytes={"up": 1024 * 1024, "gate": 1024 * 1024, "down": 1024 * 1024} if is_moe else {},
        coalesced_expert_ranges={},
    )


def run_live_benchmark(
    *,
    endpoint: str,
    model: str,
    api_key: str | None,
    prompt_tokens: int,
    warmup_tokens: int,
    measure_tokens: int,
    allow_remote: bool,
    timeout_s: float,
) -> dict[str, Any]:
    """Execute a live SSE streaming benchmark against a gateway/worker OpenAI endpoint."""
    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.hostname or ""
    if not allow_remote:
        validate_loopback_bind(host)

    total_tokens = warmup_tokens + measure_tokens
    prompt = build_deterministic_prompt(prompt_tokens)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": total_tokens,
        "temperature": 0.0,
        "top_k": 1,
        "stream": True,
        "stream_options": {"include_usage": True},
        "ignore_eos": True,
        "cache_prompt": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    token_timestamps: list[float] = []
    actual_prompt_tokens = prompt_tokens
    t_submit = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                event = json.loads(body)
            except json.JSONDecodeError:
                continue
            usage = event.get("usage")
            if isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int):
                actual_prompt_tokens = int(usage["prompt_tokens"])
            choices = event.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content"):
                    token_timestamps.append(time.perf_counter())

    metrics = compute_phase_metrics(
        prompt_tokens=actual_prompt_tokens,
        t_submit=t_submit,
        token_timestamps=token_timestamps,
        warmup_tokens=warmup_tokens,
    )
    return {
        "mode": "live",
        "endpoint": endpoint,
        "model": model,
        "phase_metrics": asdict(metrics),
    }


def run_dry_run_benchmark(
    *,
    probe_dir: Path,
    worker_id: str,
    model_name: str,
    prompt_tokens: int,
    warmup_tokens: int,
    measure_tokens: int,
    strict_direct: bool,
) -> tuple[dict[str, Any], str]:
    """Run Day-1 dry-run validation of hardware probe, bypass planner, and NVMe streaming."""
    registry = MetricsRegistry()
    # Target Dell T5820 dual Intel Arc Pro B65 topology (64 GiB combined VRAM).
    t5820_gpus = (
        GpuDeviceInfo(ordinal=0, name="Intel Arc Pro B65", backend="vulkan", total_vram_bytes=32 * 1024**3, free_vram_bytes=30 * 1024**3),
        GpuDeviceInfo(ordinal=1, name="Intel Arc Pro B65", backend="vulkan", total_vram_bytes=32 * 1024**3, free_vram_bytes=30 * 1024**3),
    )

    with tempfile.TemporaryDirectory(dir=str(probe_dir), prefix="nvme-moe-bench-") as tmp:
        tmp_dir = Path(tmp)
        nvme_profile: NVMeDriveProfile = probe_nvme_random_read(
            tmp_dir,
            request_sizes=(4096, 65536),
            queue_depths=(1, 4, 8),
            reads_per_point=16,
            repeats=2,
            strict_direct=strict_direct,
        )

        live_hw = probe_live_host_snapshot(gpus=t5820_gpus, nvme_profile=nvme_profile)
        # Ensure deterministic T5820 64 GiB planning floor even on smaller dev runners.
        planning_hw = HardwareSnapshot(
            cpu_logical_cores=max(8, live_hw.cpu_logical_cores),
            ram_total_bytes=max(64 * 1024**3, live_hw.ram_total_bytes),
            ram_usable_bytes=max(48 * 1024**3, live_hw.ram_usable_bytes),
            gpus=t5820_gpus,
            nvme=nvme_profile,
        )

        gguf_path = build_synthetic_moe_gguf(tmp_dir / "mock-moe-00001-of-00001.gguf")
        index = index_gguf_model(gguf_path)

        placement_scenarios = {
            "dense_40gib": asdict(
                plan_model_placement(
                    _synthetic_footprint_index(index, dense_bytes=40 * 1024**3, routed_bytes=0, is_moe=False),
                    planning_hw,
                    backend="vulkan",
                    context_tokens=16384,
                )
            ),
            "medium_moe_80gib": asdict(
                plan_model_placement(
                    _synthetic_footprint_index(index, dense_bytes=16 * 1024**3, routed_bytes=64 * 1024**3, is_moe=True),
                    planning_hw,
                    backend="vulkan",
                    context_tokens=16384,
                )
            ),
            "large_moe_177b_112gib": asdict(
                plan_model_placement(
                    _synthetic_footprint_index(index, dense_bytes=14 * 1024**3, routed_bytes=98 * 1024**3, is_moe=True),
                    planning_hw,
                    backend="vulkan",
                    context_tokens=32768,
                )
            ),
            "frontier_moe_800b_420gib": asdict(
                plan_model_placement(
                    _synthetic_footprint_index(index, dense_bytes=24 * 1024**3, routed_bytes=396 * 1024**3, is_moe=True),
                    planning_hw,
                    backend="vulkan",
                    context_tokens=32768,
                )
            ),
        }

        # Keep Tier-1 cache smaller than total routed working set so both cache hits
        # and Tier-2 NVMe direct reads are exercised cleanly.
        cache = ExpertCache(
            max_slots=max(4, (index.n_layers * index.n_experts) // 3),
            slot_stride_bytes=index.max_expert_slot_bytes,
            policy="count_decay",
        )

        total_tokens = warmup_tokens + measure_tokens
        token_timestamps: list[float] = []
        vram_hits = 0
        ram_hits = 0
        nvme_misses = 0
        nvme_bytes_read = 0

        t_submit = time.perf_counter()
        with NVMeMoEStreamEngine(
            index,
            worker_id=worker_id,
            model_name=model_name,
            cache=cache,
            metrics=registry,
            strict_direct=strict_direct,
            io_workers=4,
            vram_resident_experts={(0, 0), (1, 0)},
        ) as engine:
            # Prefill pass: touch initial experts across all layers.
            for layer in range(index.n_layers):
                for exp_id in (0, 1, 2, 3):
                    res = engine.fetch_expert(layer, exp_id, layer_wall_seconds=0.004)
                    if res.tier == "vram":
                        vram_hits += 1
                    elif res.tier == "ram":
                        ram_hits += 1
                    else:
                        nvme_misses += 1
                        nvme_bytes_read += res.read_bytes

            # Decode pass: warmup (1..128) + steady-state (129..256).
            for step in range(total_tokens):
                layer = step % index.n_layers
                if step < warmup_tokens:
                    active = (step % index.n_experts, (step + 1) % index.n_experts)
                else:
                    cold = (step % index.n_experts) if (step % 4 == 0) else (step % 3)
                    active = (0, 1, cold)
                for exp_id in active:
                    res = engine.fetch_expert(layer, exp_id, layer_wall_seconds=0.004)
                    if res.tier == "vram":
                        vram_hits += 1
                    elif res.tier == "ram":
                        ram_hits += 1
                    else:
                        nvme_misses += 1
                        nvme_bytes_read += res.read_bytes
                token_timestamps.append(time.perf_counter())

            engine_bw = engine.bandwidth_bytes_per_sec
            engine_io_wait = engine.io_wait_ratio

        phase = compute_phase_metrics(
            prompt_tokens=prompt_tokens,
            t_submit=t_submit,
            token_timestamps=token_timestamps,
            warmup_tokens=warmup_tokens,
        )

    prom_text = registry.render_prometheus_text()
    report = {
        "mode": "dry-run",
        "worker_id": worker_id,
        "model": model_name,
        "hardware": {
            "cpu_logical_cores": planning_hw.cpu_logical_cores,
            "ram_total_gib": round(planning_hw.ram_total_bytes / 1024**3, 2),
            "ram_usable_gib": round(planning_hw.ram_usable_bytes / 1024**3, 2),
            "total_vram_gib": round(planning_hw.total_vram_bytes / 1024**3, 2),
            "gpu_count": len(planning_hw.gpus),
        },
        "nvme_probe": {
            "direct_io": nvme_profile.direct_io,
            "knee_queue_depth": nvme_profile.knee_queue_depth,
            "effective_read_mb_s": round(nvme_profile.effective_read_bps / (1024**2), 2),
            "points": [asdict(p) for p in nvme_profile.points],
        },
        "placement_scenarios": placement_scenarios,
        "engine_stats": {
            "vram_hits": vram_hits,
            "ram_hits": ram_hits,
            "nvme_misses": nvme_misses,
            "nvme_bytes_read": nvme_bytes_read,
            "cache_evictions": cache.stats.evictions,
            "effective_bandwidth_bps": round(engine_bw, 2),
            "io_wait_ratio": round(engine_io_wait, 4),
        },
        "phase_metrics": asdict(phase),
    }
    return report, prom_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="4K-prefill + steady-state (tokens 129-256) NVMe MoE benchmark harness."
    )
    parser.add_argument("--dry-run", action="store_true", help="Run Day-1 dry-run using mock GGUF + live NVMe probe.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1/chat/completions", help="OpenAI-compatible SSE endpoint.")
    parser.add_argument("--allow-remote", action="store_true", help="Allow non-loopback endpoint URLs in live mode.")
    parser.add_argument("--model", default="moe-177b-nvme", help="Model alias or label.")
    parser.add_argument("--worker-id", default="llama-nvme-0", help="Worker label for Prometheus output.")
    parser.add_argument("--api-key", default=os.environ.get("AIHOST_API_KEY"), help="Bearer API key for live endpoint.")
    parser.add_argument("--prompt-tokens", type=int, default=DEFAULT_PROMPT_TOKENS, help="Target prompt length (default 4096).")
    parser.add_argument("--warmup-tokens", type=int, default=DEFAULT_WARMUP_TOKENS, help="Warmup tokens excluded from steady state (default 128).")
    parser.add_argument("--measure-tokens", type=int, default=DEFAULT_MEASURE_TOKENS, help="Steady-state measured tokens (default 128 -> tokens 129..256).")
    parser.add_argument("--probe-dir", type=Path, default=Path(tempfile.gettempdir()), help="Directory for Day-1 NVMe probe & mock shard.")
    parser.add_argument("--strict-direct", action="store_true", help="Fail closed if O_DIRECT is unsupported on --probe-dir.")
    parser.add_argument("--timeout", type=float, default=300.0, help="HTTP timeout in seconds for live mode.")
    parser.add_argument("--json-out", type=Path, default=None, help="Write JSON provenance report to this path.")
    parser.add_argument("--prom-out", type=Path, default=None, help="Write Prometheus exposition metrics to this path.")
    args = parser.parse_args(argv)

    if args.dry_run:
        report, prom_text = run_dry_run_benchmark(
            probe_dir=args.probe_dir,
            worker_id=args.worker_id,
            model_name=args.model,
            prompt_tokens=args.prompt_tokens,
            warmup_tokens=args.warmup_tokens,
            measure_tokens=args.measure_tokens,
            strict_direct=args.strict_direct,
        )
    else:
        report = run_live_benchmark(
            endpoint=args.endpoint,
            model=args.model,
            api_key=args.api_key,
            prompt_tokens=args.prompt_tokens,
            warmup_tokens=args.warmup_tokens,
            measure_tokens=args.measure_tokens,
            allow_remote=args.allow_remote,
            timeout_s=args.timeout,
        )
        prom_text = (
            "# HELP homelab_ai_benchmark_prefill_tokens_per_sec Prefill throughput on 4K prompt.\n"
            "# TYPE homelab_ai_benchmark_prefill_tokens_per_sec gauge\n"
            f'homelab_ai_benchmark_prefill_tokens_per_sec{{model="{args.model}"}} {report["phase_metrics"]["prefill_tokens_per_sec"]}\n'
            "# HELP homelab_ai_benchmark_steady_decode_tokens_per_sec Steady-state decode throughput (tokens 129-256).\n"
            "# TYPE homelab_ai_benchmark_steady_decode_tokens_per_sec gauge\n"
            f'homelab_ai_benchmark_steady_decode_tokens_per_sec{{model="{args.model}"}} {report["phase_metrics"]["steady_decode_tokens_per_sec"]}\n'
        )

    rendered_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered_json, encoding="utf-8")
    if args.prom_out is not None:
        args.prom_out.parent.mkdir(parents=True, exist_ok=True)
        args.prom_out.write_text(prom_text, encoding="utf-8")

    print(rendered_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
