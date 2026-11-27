"""Unit & integration tests for NVMe-backed MoE expert streaming in homelab-ai."""

from __future__ import annotations

import struct
from pathlib import Path

import jinja2
import pytest

from orchestrator_runtime.metrics import MetricsRegistry
from orchestrator_runtime.nvme_moe.gguf_index import (
    DIRECT_IO_BLOCK_SIZE,
    GGML_TYPE_Q4_K,
    GGML_TYPE_Q6_K,
    GGUF_MAGIC,
    GGUF_TYPE_STRING,
    GGUF_TYPE_UINT32,
    ByteRange,
    MoEModelIndex,
    coalesce_ranges,
    index_gguf_model,
)
from orchestrator_runtime.nvme_moe.hardware_probe import (
    GpuDeviceInfo,
    HardwareSnapshot,
    NVMeBandwidthPoint,
    NVMeDriveProfile,
    SecurityBindError,
    bit_reversed_layer_order,
    compute_knee_queue_depth,
    plan_model_placement,
    probe_nvme_random_read,
    validate_loopback_bind,
)
from orchestrator_runtime.nvme_moe.io_engine import (
    NVMeMoEStreamEngine,
    should_issue_prefetch,
)
from orchestrator_runtime.nvme_moe.memory_arbiter import (
    ExpertCache,
    ExpertCacheKey,
    HostMemoryArbiter,
    compute_watermark_boost_headroom,
    size_cache_slots_for_budget,
)
from orchestrator_runtime.watchdog import StallTracker
from scripts.benchmark_nvme_moe import (
    compute_phase_metrics,
    run_dry_run_benchmark,
)
from tests.test_orchestrator_metrics_contract import validate_exposition

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pack_str(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _write_mixed_quant_gguf(path: Path) -> tuple[Path, dict[str, bytes]]:
    """Create a GGUF v3 MoE file with mixed quantization (Q4_K up/gate, Q6_K down) and unique payloads."""
    num_layers = 2
    num_experts = 4
    hidden_dim = 256
    ffn_dim = 256
    alignment = DIRECT_IO_BLOCK_SIZE

    q4k_expert_bytes = (hidden_dim // 256) * 144 * ffn_dim  # 36,864 B
    q6k_expert_bytes = (ffn_dim // 256) * 210 * hidden_dim  # 53,760 B

    kv_entries = [
        ("general.architecture", GGUF_TYPE_STRING, _pack_str("qwen3moe")),
        ("general.alignment", GGUF_TYPE_UINT32, struct.pack("<I", alignment)),
        ("qwen3moe.block_count", GGUF_TYPE_UINT32, struct.pack("<I", num_layers)),
        ("qwen3moe.expert_count", GGUF_TYPE_UINT32, struct.pack("<I", num_experts)),
        ("qwen3moe.expert_used_count", GGUF_TYPE_UINT32, struct.pack("<I", 2)),
    ]

    tensor_defs: list[tuple[str, tuple[int, ...], int, int]] = []
    payload_map: dict[str, bytes] = {}
    tensor_blobs: list[tuple[int, bytes]] = []
    running_offset = 0

    for layer in range(num_layers):
        for role, ggml_type, expert_bytes in (
            ("up", GGML_TYPE_Q4_K, q4k_expert_bytes),
            ("gate", GGML_TYPE_Q4_K, q4k_expert_bytes),
            ("down", GGML_TYPE_Q6_K, q6k_expert_bytes),
        ):
            name = f"blk.{layer}.ffn_{role}_exps.weight"
            tensor_defs.append((name, (hidden_dim, ffn_dim, num_experts), ggml_type, running_offset))
            blob = bytearray()
            for exp_id in range(num_experts):
                tag = ((layer + 1) * 31 + (exp_id + 1) * 7 + ord(role[0])) & 0xFF
                expert_data = bytes([tag]) * expert_bytes
                payload_map[f"{layer}:{exp_id}:{role}"] = expert_data
                blob += expert_data
            tensor_blobs.append((running_offset, bytes(blob)))
            running_offset = ((running_offset + len(blob) + alignment - 1) // alignment) * alignment

    header = bytearray()
    header += GGUF_MAGIC
    header += struct.pack("<IQQ", 3, len(tensor_defs), len(kv_entries))
    for k, vt, val in kv_entries:
        header += _pack_str(k) + struct.pack("<I", vt) + val
    for name, dims, ggml_type, rel_offset in tensor_defs:
        header += _pack_str(name) + struct.pack("<I", len(dims))
        for d in dims:
            header += struct.pack("<Q", d)
        header += struct.pack("<IQ", ggml_type, rel_offset)

    if len(header) % alignment != 0:
        header += b"\x00" * (alignment - (len(header) % alignment))
    data_start = len(header)

    file_buf = bytearray(data_start + running_offset)
    file_buf[0 : len(header)] = header
    for rel_off, blob in tensor_blobs:
        file_buf[data_start + rel_off : data_start + rel_off + len(blob)] = blob

    path.write_bytes(bytes(file_buf))
    return path, payload_map


class TestGGUFExpertIndexing:
    def test_mixed_quant_offsets_and_direct_io_alignment(self, tmp_path: Path) -> None:
        gguf_path, expected_payloads = _write_mixed_quant_gguf(tmp_path / "mixed-moe.gguf")
        index = index_gguf_model(gguf_path)

        assert index.architecture == "qwen3moe"
        assert index.n_layers == 2
        assert index.n_experts == 4
        assert index.n_experts_used == 2
        assert index.is_moe is True
        assert index.routed_bytes > 0

        raw_file = gguf_path.read_bytes()
        for layer in range(2):
            layout = index.routed_layers[layer]
            assert layout.roles["up"].ggml_type == GGML_TYPE_Q4_K
            assert layout.roles["gate"].ggml_type == GGML_TYPE_Q4_K
            assert layout.roles["down"].ggml_type == GGML_TYPE_Q6_K
            assert layout.roles["up"].expert_bytes == 36864
            assert layout.roles["down"].expert_bytes == 53760
            for expert_id in range(4):
                for role in ("up", "gate", "down"):
                    ext = layout.extent_for(expert_id, role)
                    assert ext.aligned_offset % DIRECT_IO_BLOCK_SIZE == 0
                    assert ext.aligned_bytes % DIRECT_IO_BLOCK_SIZE == 0
                    assert ext.aligned_bytes >= ext.data_offset + ext.logical_bytes
                    sliced = raw_file[ext.aligned_offset : ext.aligned_offset + ext.aligned_bytes]
                    extracted = sliced[ext.data_offset : ext.data_offset + ext.logical_bytes]
                    assert extracted == expected_payloads[f"{layer}:{expert_id}:{role}"]

        assert 0 in index.coalesced_expert_ranges
        covered = sum(r.end - r.start for r in index.coalesced_expert_ranges[0])
        assert covered >= index.routed_bytes

    def test_coalesce_ranges_merges_overlapping_and_adjacent(self) -> None:
        merged = coalesce_ranges([ByteRange(100, 200), ByteRange(200, 350), ByteRange(500, 600), ByteRange(550, 700)])
        assert merged == (ByteRange(100, 350), ByteRange(500, 700))


class TestMemoryArbiterAndExpertCache:
    def test_watermark_boost_headroom_and_dual_term_arbiter(self) -> None:
        meminfo = (
            "MemTotal:       67108864 kB\n"
            "MemAvailable:   41943040 kB\n"
            "Active(file):    8388608 kB\n"
            "Inactive(file):  8388608 kB\n"
            "KReclaimable:    2097152 kB\n"
            "Hugepagesize:       2048 kB\n"
        )
        zoneinfo = """\
Node 0, zone   Normal
  pages free     100000
        boost    0
        min      2000
        low      4000
        high     6000
        managed  500000
"""
        headroom = compute_watermark_boost_headroom(meminfo, zoneinfo, "15000", page_size=4096)
        assert headroom > 0

        # Synthetic Linux procfs + cgroup v2 hierarchy
        cg_current = 20 * 1024**3
        fake_fs = {
            "/proc/meminfo": meminfo,
            "/proc/zoneinfo": zoneinfo,
            "/proc/sys/vm/watermark_boost_factor": "0",
            "/proc/self/cgroup": "0::/system.slice/llama-worker.service\n",
            "/sys/fs/cgroup/system.slice/llama-worker.service/memory.max": str(32 * 1024**3),
            "/sys/fs/cgroup/system.slice/llama-worker.service/memory.current": str(cg_current),
            "/sys/fs/cgroup/system.slice/llama-worker.service/memory.stat": "file 0\n",
        }

        def fake_reader(path: str) -> str | None:
            return fake_fs.get(path)

        arbiter = HostMemoryArbiter(
            cgroup_reserve_bytes=2 * 1024**3,
            host_headroom_bytes=2 * 1024**3,
            reader=fake_reader,
        )
        room = arbiter.measure()
        # Tightest term is cgroup: 32 GiB - 2 GiB reserve - 20 GiB current = 10 GiB
        assert room.binding_term == "cgroup"
        assert room.effective_surplus_bytes == 10 * 1024**3

        reclaimed: list[int] = []

        def fake_reclaimer(deficit: int) -> int:
            reclaimed.append(deficit)
            fake_fs["/sys/fs/cgroup/system.slice/llama-worker.service/memory.current"] = str(15 * 1024**3)
            return 5 * 1024**3

        arbiter.register_reclaimer(fake_reclaimer)
        # Request 12 GiB -> short by 2 GiB -> triggers reclaimer -> succeeds
        ticket = arbiter.admit(12 * 1024**3)
        assert ticket is not None
        assert reclaimed == [2 * 1024**3]
        assert arbiter.measure().pending_bytes == 12 * 1024**3
        ticket.commit()
        assert arbiter.measure().pending_bytes == 0

    def test_cache_eviction_policies_lease_safety_and_slot_sizing(self) -> None:
        slots = size_cache_slots_for_budget(
            100 * 1024 * 1024,
            2 * 1024 * 1024,
            n_layers=16,
            n_experts=64,
        )
        assert 40 <= slots <= 50

        sig = ((1, 2, 4096, 100, 100),)
        for policy in ("count_decay", "lru", "lfu"):
            cache = ExpertCache(max_slots=2, slot_stride_bytes=4096, policy=policy)
            k0 = ExpertCacheKey(0, 0, sig)
            k1 = ExpertCacheKey(0, 1, sig)
            k2 = ExpertCacheKey(0, 2, sig)

            assert cache.put(k0, {"up": b"a" * 4096}) is True
            assert cache.put(k1, {"up": b"b" * 4096}) is True
            # Hold active lease on k0 -> must never be evicted
            assert cache.lookup(k0, acquire_lease=True) is not None
            assert cache.put(k2, {"up": b"c" * 4096}) is True
            assert cache.lookup(k0) is not None
            assert cache.lookup(k2) is not None
            assert cache.lookup(k1) is None
            assert cache.stats.evictions >= 1
            cache.release_lease(k0)

    def test_vram_mirrored_backup_evicted_before_unique_ram_expert(self) -> None:
        sig = ((1, 2, 4096, 100, 100),)
        cache = ExpertCache(max_slots=2, slot_stride_bytes=4096, policy="count_decay")
        k0 = ExpertCacheKey(0, 0, sig)
        k1 = ExpertCacheKey(0, 1, sig)
        k2 = ExpertCacheKey(0, 2, sig)

        cache.put(k0, {"up": b"a" * 4096})
        cache.put(k1, {"up": b"b" * 4096})
        for _ in range(10):
            assert cache.lookup(k0) is not None
        # Mark k0 as mirrored in Tier-0 VRAM -> disposable backup copy evicted first
        cache.mark_vram_mirrored(k0, True)
        cache.put(k2, {"up": b"c" * 4096})
        assert cache.lookup(k0) is None
        assert cache.lookup(k1) is not None
        assert cache.lookup(k2) is not None


class TestNVMeStreamEngineAndPrometheusMetrics:
    def test_end_to_end_streaming_and_prometheus_exposition(self, tmp_path: Path) -> None:
        gguf_path, expected = _write_mixed_quant_gguf(tmp_path / "stream-moe.gguf")
        index = index_gguf_model(gguf_path)
        registry = MetricsRegistry()
        cache = ExpertCache(max_slots=2, slot_stride_bytes=index.max_expert_slot_bytes, policy="count_decay")

        with NVMeMoEStreamEngine(
            index,
            worker_id="llama-b65-0",
            model_name="qwen3-moe-177b",
            cache=cache,
            metrics=registry,
            strict_direct=False,
            io_workers=2,
            vram_resident_experts={(0, 0)},
        ) as engine:
            # Tier-0 VRAM hit
            r_vram = engine.fetch_expert(0, 0, layer_wall_seconds=0.005)
            assert r_vram.tier == "vram"
            assert r_vram.read_bytes == 0

            # Tier-2 NVMe direct miss
            r_miss = engine.fetch_expert(0, 1, layer_wall_seconds=0.005)
            assert r_miss.tier == "nvme"
            assert r_miss.payload["up"] == expected["0:1:up"]
            assert r_miss.payload["gate"] == expected["0:1:gate"]
            assert r_miss.payload["down"] == expected["0:1:down"]
            assert r_miss.read_bytes > 0

            # Subsequent fetch of (0, 1) must hit Tier-1 RAM
            r_ram = engine.fetch_expert(0, 1, layer_wall_seconds=0.005)
            assert r_ram.tier == "ram"
            assert r_ram.payload["down"] == expected["0:1:down"]
            assert engine.bandwidth_bytes_per_sec > 0.0

        prom_text = registry.render_prometheus_text()
        validate_exposition(prom_text)
        assert 'homelab_ai_moe_expert_cache_hits_total{worker_id="llama-b65-0",tier="vram",model="qwen3-moe-177b"} 1' in prom_text
        assert 'homelab_ai_moe_expert_cache_hits_total{worker_id="llama-b65-0",tier="ram",model="qwen3-moe-177b"} 1' in prom_text
        assert 'homelab_ai_moe_expert_cache_misses_total{worker_id="llama-b65-0",model="qwen3-moe-177b"} 1' in prom_text
        assert "homelab_ai_nvme_expert_read_latency_seconds_bucket" in prom_text
        assert "homelab_ai_nvme_stream_bandwidth_bytes_per_sec" in prom_text
        assert "homelab_ai_nvme_io_wait_ratio" in prom_text
        assert 'homelab_ai_moe_streaming_mode{worker_id="llama-b65-0",mode="nvme_stream",model="qwen3-moe-177b"} 1' in prom_text

    def test_prefetch_decision_threshold(self) -> None:
        # estimated_read_us=1000, layer_gap_us=500 -> remaining_fraction=0.5
        assert should_issue_prefetch(0.75, estimated_read_us=1000.0, layer_gap_us=500.0) is True
        assert should_issue_prefetch(0.40, estimated_read_us=1000.0, layer_gap_us=500.0) is False
        assert should_issue_prefetch(0.50, estimated_read_us=1000.0, layer_gap_us=500.0) is False


class TestAdaptiveBypassAndSecurity:
    def _t5820_hw(self) -> HardwareSnapshot:
        nvme = NVMeDriveProfile(
            path="/var/lib/local-ai/models/experts",
            direct_io=True,
            points=(
                NVMeBandwidthPoint(65536, 1, 1000e6, 950e6, 1050e6, 60.0, 90.0),
                NVMeBandwidthPoint(65536, 16, 4800e6, 4700e6, 4950e6, 210.0, 350.0),
                NVMeBandwidthPoint(65536, 32, 5000e6, 4900e6, 5100e6, 400.0, 650.0),
            ),
            knee_queue_depth=16,
            effective_read_bps=4800e6,
        )
        return HardwareSnapshot(
            cpu_logical_cores=16,
            ram_total_bytes=64 * 1024**3,
            ram_usable_bytes=48 * 1024**3,
            gpus=(
                GpuDeviceInfo(0, "Intel Arc Pro B65", "vulkan", 32 * 1024**3, 31 * 1024**3),
                GpuDeviceInfo(1, "Intel Arc Pro B65", "vulkan", 32 * 1024**3, 31 * 1024**3),
            ),
            nvme=nvme,
        )

    def _mock_index(self, tmp_path: Path, *, dense_bytes: int, routed_bytes: int, is_moe: bool) -> MoEModelIndex:
        gguf_path, _ = _write_mixed_quant_gguf(tmp_path / f"plan-{dense_bytes}-{routed_bytes}.gguf")
        base = index_gguf_model(gguf_path)
        return MoEModelIndex(
            shards=base.shards,
            architecture="qwen3moe" if is_moe else "llama",
            n_layers=64,
            n_experts=128 if is_moe else 0,
            n_experts_used=8 if is_moe else 0,
            dense_bytes=dense_bytes,
            routed_bytes=routed_bytes if is_moe else 0,
            total_tensor_bytes=dense_bytes + (routed_bytes if is_moe else 0),
            latent_dim=4096,
            hidden_dim=4096,
            routed_layers=base.routed_layers if is_moe else {},
            max_role_read_bytes={"up": 1024 * 1024, "gate": 1024 * 1024, "down": 1024 * 1024} if is_moe else {},
            coalesced_expert_ranges={},
        )

    def test_adaptive_bypass_thresholds_for_t5820_dual_b65(self, tmp_path: Path) -> None:
        hw = self._t5820_hw()

        # Case 1: <= 64 GiB combined VRAM -> bypass_vram (streaming OFF)
        p_small = plan_model_placement(
            self._mock_index(tmp_path, dense_bytes=40 * 1024**3, routed_bytes=0, is_moe=False),
            hw,
            backend="vulkan",
            context_tokens=16384,
        )
        assert p_small.mode == "bypass_vram"
        assert p_small.nvme_streaming_enabled is False
        assert p_small.bind_host == "127.0.0.1"

        # Case 2: > VRAM but <= VRAM + RAM -> bypass_ram (streaming OFF)
        p_med = plan_model_placement(
            self._mock_index(tmp_path, dense_bytes=16 * 1024**3, routed_bytes=64 * 1024**3, is_moe=True),
            hw,
            backend="vulkan",
            context_tokens=16384,
        )
        assert p_med.mode == "bypass_ram"
        assert p_med.nvme_streaming_enabled is False

        # Case 3: 177B-800B+ MoE (> VRAM + RAM) -> nvme_stream (streaming ON)
        p_large = plan_model_placement(
            self._mock_index(tmp_path, dense_bytes=16 * 1024**3, routed_bytes=164 * 1024**3, is_moe=True),
            hw,
            backend="vulkan",
            context_tokens=32768,
        )
        assert p_large.mode == "nvme_stream"
        assert p_large.nvme_streaming_enabled is True
        assert p_large.ram_expert_cache_bytes > 0
        assert p_large.ram_expert_cache_slots > 0
        assert p_large.gpu_staging_alignment_bytes == 65536
        assert p_large.device_staging_ring_slots == 4
        assert "--host" in p_large.llama_args and "127.0.0.1" in p_large.llama_args
        assert "--no-mmap" in p_large.llama_args

        # Case 4: Huge dense model (> VRAM + RAM, not MoE) -> dense_spill (bit-reversed NVMe layer spill)
        p_dense = plan_model_placement(
            self._mock_index(tmp_path, dense_bytes=140 * 1024**3, routed_bytes=0, is_moe=False),
            hw,
            backend="sycl",
            context_tokens=16384,
        )
        assert p_dense.mode == "dense_spill"
        assert p_dense.nvme_streaming_enabled is True
        assert len(p_dense.dense_layer_order) == 64

    def test_loopback_bind_enforcement_fails_closed(self) -> None:
        assert validate_loopback_bind("127.0.0.1") == "127.0.0.1"
        for bad in ("0.0.0.0", "::", "192.168.1.10", "localhost", ""):
            with pytest.raises(SecurityBindError):
                validate_loopback_bind(bad)

    def test_bit_reversed_order_and_knee_qd(self) -> None:
        order = bit_reversed_layer_order(8)
        assert len(order) == 8
        assert set(order) == set(range(8))
        assert order[0] == 0 and order[1] == 4
        qd, bps = compute_knee_queue_depth(
            [
                NVMeBandwidthPoint(65536, 1, 500.0, 480.0, 520.0, 100.0, 150.0),
                NVMeBandwidthPoint(65536, 4, 2000.0, 1900.0, 2100.0, 120.0, 180.0),
                NVMeBandwidthPoint(65536, 16, 4600.0, 4500.0, 4950.0, 200.0, 320.0),
                NVMeBandwidthPoint(65536, 32, 5000.0, 4900.0, 5100.0, 350.0, 500.0),
            ]
        )
        assert qd == 16
        assert bps == 4600.0

    def test_nvme_probe_runs_non_destructively(self, tmp_path: Path) -> None:
        sample = tmp_path / "probe.bin"
        sample.write_bytes(b"\x11" * (2 * 1024 * 1024))
        report = probe_nvme_random_read(
            sample,
            request_sizes=(4096,),
            queue_depths=(1, 4),
            reads_per_point=8,
            repeats=1,
            strict_direct=False,
        )
        assert len(report.points) == 2
        assert report.effective_read_bps > 0
        assert report.knee_queue_depth in (1, 4)


class TestStallDetectionIntegration:
    def test_pcie_nvme_io_wait_advances_stall_gauge_while_running(self) -> None:
        tracker = StallTracker()
        assert tracker.update("w1", 100.0, running=1, progress=10, nvme_io_wait_ratio=0.85) == 0.0
        assert tracker.update("w1", 112.0, running=1, progress=11, nvme_io_wait_ratio=0.90) == 12.0
        assert tracker.update("w1", 120.0, running=1, progress=12, nvme_io_wait_ratio=0.20) == 0.0
        assert tracker.update("w1", 130.0, running=1, progress=13, nvme_io_wait_ratio=0.95) == 0.0
        assert tracker.update("w1", 140.0, running=0, progress=13, nvme_io_wait_ratio=0.95) == 0.0


class TestBenchmarkHarnessAndAnsibleTemplates:
    def test_phase_metrics_isolates_4k_prefill_from_steady_state_129_to_256(self) -> None:
        t0 = 1000.0
        ts = [t0 + 2.0]  # token 1 arrival
        for _ in range(1, 128):
            ts.append(ts[-1] + 0.100)
        for _ in range(128):
            ts.append(ts[-1] + 0.025)

        pm = compute_phase_metrics(prompt_tokens=4096, t_submit=t0, token_timestamps=ts, warmup_tokens=128)
        assert pm.prefill_tokens_per_sec == pytest.approx(2048.0, rel=1e-3)
        assert pm.warmup_decode_tokens_per_sec == pytest.approx(10.0, rel=1e-3)
        assert pm.steady_decode_tokens_per_sec == pytest.approx(40.0, rel=1e-3)
        assert pm.steady_itl_p50_ms == pytest.approx(25.0, rel=1e-3)
        assert pm.steady_tokens == 128

    def test_dry_run_benchmark_end_to_end(self, tmp_path: Path) -> None:
        report, prom_text = run_dry_run_benchmark(
            probe_dir=tmp_path,
            worker_id="llama-b65-dryrun",
            model_name="qwen3-moe-177b",
            prompt_tokens=4096,
            warmup_tokens=32,
            measure_tokens=32,
            strict_direct=False,
        )
        assert report["mode"] == "dry-run"
        assert report["placement_scenarios"]["dense_40gib"]["mode"] == "bypass_vram"
        assert report["placement_scenarios"]["medium_moe_80gib"]["mode"] == "bypass_ram"
        assert report["placement_scenarios"]["large_moe_177b_112gib"]["mode"] == "nvme_stream"
        assert report["placement_scenarios"]["frontier_moe_800b_420gib"]["mode"] == "nvme_stream"
        assert report["phase_metrics"]["steady_decode_tokens_per_sec"] > 0
        assert report["engine_stats"]["vram_hits"] > 0
        assert report["engine_stats"]["ram_hits"] > 0
        assert report["engine_stats"]["nvme_misses"] > 0
        validate_exposition(prom_text)

    def test_llama_worker_service_renders_cgroup_v2_and_nvme_expert_mount(self) -> None:
        tpl_path = REPO_ROOT / "roles/llama_cpp_container/templates/llama-worker.service.j2"
        env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
        rendered = env.from_string(tpl_path.read_text(encoding="utf-8")).render(
            llama_worker={
                "worker_id": "llama-moe-0",
                "container_name": "aihost-llama-moe-0",
                "gpu": "0",
                "config_dir": "/etc/local-ai/llama/moe-0",
                "model_file": "moe.gguf",
                "context": 8192,
                "port": 8081,
                "served_name": "engineering/moe",
                "nvme_expert_dir": "/var/lib/local-ai/models/experts",
                "memory_high": "44G",
                "memory_max": "52G",
                "memory_swap_max": "0",
            },
            llama_cpp_container_uid=999,
            llama_cpp_container_user="aihost-runtime",
            llama_cpp_container_home="/var/lib/aihost-runtime",
            llama_cpp_container_model_dir="/var/lib/local-ai/models/gguf",
            llama_cpp_container_image="ghcr.io/ggml-org/llama.cpp",
            llama_cpp_container_digest="sha256:" + "0" * 64,
            llama_cpp_container_host="127.0.0.1",
            llama_cpp_container_default_args=["-ngl", "99", "--no-mmap"],
            llama_cpp_container_reasoning_budget_message="stop",
            llama_cpp_container_log_dir="/var/log/local-ai/llama",
            llama_cpp_container_slot_persistence=False,
            llama_cpp_container_slot_dir="/var/lib/aihost-runtime/slots",
        )
        assert "--host 127.0.0.1 --port 8081" in rendered
        assert "-v /var/lib/local-ai/models/experts:/experts:ro" in rendered
        assert "MemoryAccounting=yes" in rendered
        assert "MemoryHigh=44G" in rendered
        assert "MemoryMax=52G" in rendered
        assert "MemorySwapMax=0" in rendered

    def test_udev_io_rules_template_renders_nvme_queue_tuning(self) -> None:
        tpl_path = REPO_ROOT / "roles/os_tuning/templates/61-aihost-io.rules.j2"
        env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
        rendered = env.from_string(tpl_path.read_text(encoding="utf-8")).render(
            os_tuning_config={
                "os_tuning": {
                    "io": {
                        "scheduler": "none",
                        "read_ahead_kb": 16,
                        "nr_requests": 1024,
                        "rq_affinity": 2,
                        "add_random": 0,
                    }
                }
            }
        )
        assert 'ATTR{queue/scheduler}="none"' in rendered
        assert 'ATTR{queue/read_ahead_kb}="16"' in rendered
        assert 'ATTR{queue/nr_requests}="1024"' in rendered
        assert 'ATTR{queue/rq_affinity}="2"' in rendered
        assert 'ATTR{queue/add_random}="0"' in rendered
