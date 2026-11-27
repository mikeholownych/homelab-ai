# Architectural Design Specification: NVMe-Backed MoE Expert Streaming for `homelab-ai`

**Status:** Approved Clean-Room Design Specification
**Target Platform:** Dell Precision T5820 Bare-Metal Server (Ubuntu 26.04 LTS, `systemd` + `cgroup v2`, Intel Xeon W-21xx, 64 GiB DDR4 RAM, Dual Intel Arc Pro B65 GPUs [64 GiB combined VRAM, SYCL / Vulkan], Dedicated Dual-NVMe PCIe Array)
**Scope:** Runtime-agnostic three-tier memory hierarchy (`VRAM -> Host RAM -> NVMe`) for Mixture-of-Experts (MoE) `llama.cpp` workers behind `orchestrator_gateway`, Prometheus observability, kernel/OS provisioning, and steady-state benchmarking.

---

## 1. Executive Overview & Architectural Goals

Modern sparse Mixture-of-Experts (MoE) language models (177B to 800B+ total parameters with 3B to 42B active parameters per token) exceed the combined VRAM (64 GiB) and host RAM (64 GiB) of a single workstation node, yet each forward pass touches only a small active subset of routed feed-forward experts per layer. Naive OS `mmap` loading of multi-hundred-gigabyte GGUF checkpoints causes severe Linux page-cache thrashing, unpredictable major page faults inside compute barriers, memory-reclaim stalls, and cgroup OOM kills.

This specification defines a clean-room, production-grade NVMe MoE streaming architecture tailored for `homelab-ai`:

1. **Zero-Copy GGUF Byte-Offset Indexing:** Parse GGUF headers exclusively at startup to map every `(layer, expert, role)` slice to its exact physical file offset and 4 KiB-aligned direct-I/O extent, avoiding weight reads during inspection and preventing OS page-cache pollution for cold experts.
2. **Three-Tier Memory Hierarchy (`VRAM -> RAM -> NVMe`):** Pin dense layers, attention projections, shared experts, norms, embeddings, and KV caches in VRAM/RAM while caching hot routed experts in a bounded, non-THP host RAM arena and streaming cold experts on demand via aligned direct/async I/O (`O_DIRECT`, `io_uring`, or aligned `pread`).
3. **Hardware Probing & Adaptive Bypass:** Benchmark host memory availability, GPU free VRAM, and NVMe random-read throughput at startup; automatically bypass NVMe streaming whenever a model fits entirely within VRAM or VRAM + RAM.
4. **Non-CUDA GPU Staging & Synchronization (Vulkan / SYCL):** Decouple the core storage/cache/policy layer from GPU vendor APIs, using aligned host staging rings and asynchronous queue/event barriers compatible with Intel Arc Pro B65 Vulkan and SYCL backends.
5. **Observability, Stall Integration & Steady-State Benchmarking:** Emit Prometheus counters, histograms, bandwidth gauges, and NVMe I/O stall signals, paired with a repeatable 4K-prompt benchmark separating prefill from steady-state decode (tokens 129–256).

---

## 2. GGUF Metadata & Physical Byte-Offset Indexing

### 2.1 Header-Only Inspection Contract

Before allocating device buffers or launching compute backends, the indexer parses the GGUF binary header (version 2 or 3, little-endian) of every shard in a checkpoint using metadata-only reads (no tensor payload allocation or paging):

- **Header fields extracted:** Magic bytes (`GGUF`), format version, tensor count, metadata KV count, alignment override (`general.alignment`, defaulting to 32 bytes), architecture string (`general.architecture`), layer count (`<arch>.block_count`), routed expert count (`<arch>.expert_count`), active experts per token (`<arch>.expert_used_count`), and tensor descriptor table (`name`, `n_dims`, `dims[]`, `ggml_type`, `relative_offset`).
- **Tensor data base offset:** Computed immediately after the metadata and tensor descriptor tables, rounded up to `general.alignment`.
- **Multi-shard discovery:** Sharded checkpoints matching `*-NNNNN-of-MMMMM.gguf` are discovered and indexed as a single logical model table where each tensor entry records its shard file index (`source_idx`).

### 2.2 Routed Expert Identification & Layout Validation

Routed MoE feed-forward tensors are identified by canonical tensor naming:

- `blk.<layer>.ffn_up_exps.weight` (role: `up`)
- `blk.<layer>.ffn_gate_exps.weight` (role: `gate`)
- `blk.<layer>.ffn_down_exps.weight` (role: `down`)
- Optional fused variant `blk.<layer>.ffn_gate_up_exps.weight` (recognized for capacity accounting and fallback classification; separate three-role tensors are required for independent per-role streaming).

For every routed layer, the indexer validates:

1. **Tensor rank and contiguity:** Each role tensor must be 3-dimensional `[columns, rows, n_experts]` stored contiguously with `columns` evenly divisible by the quantization block size of its `ggml_type`.
2. **Cross-role geometric consistency:**
   - `gate.columns == up.columns`, `gate.rows == up.rows`, `gate.n_experts == up.n_experts`
   - `down.columns == up.rows`, `down.rows == up.columns`, `down.n_experts == up.n_experts`
3. **Mixed-quantization tolerance:** Individual layers and roles within a layer may use distinct quantization formats (e.g., `Q4_K` for `up`/`gate`, `Q6_K` for `down`, or `MXFP4` experts alongside `Q8_0` dense weights). The indexer deduplicates distinct `(up_type, gate_type, down_type, columns, rows)` format descriptors and computes the global maximum aligned read byte size per role across all routed layers so cache slots and staging buffers are uniformly sized for any layer.

### 2.3 Physical Extent Mapping & 4 KiB Direct-I/O Alignment

For each routed layer `L`, expert index `e in [0, n_experts)`, and role `r in {up, gate, down}`:

- `row_bytes = (columns / block_elements(type)) * block_bytes(type)`
- `expert_bytes = row_bytes * rows`
- `logical_offset = shard_data_offset + tensor_relative_offset + e * expert_bytes`

Because `O_DIRECT` block storage I/O requires file offsets, transfer lengths, and user buffer pointers to be multiples of the storage logical block alignment unit `A = 4096` bytes:

- `data_offset = logical_offset mod A`
- `aligned_offset = logical_offset - data_offset`
- `aligned_bytes = ceil((data_offset + expert_bytes) / A) * A`

When a direct read lands in a 4 KiB-aligned staging or cache buffer at address `buf`, the valid tensor payload begins at `buf + data_offset` for `expert_bytes` bytes.

### 2.4 Preventing OS `mmap` Page-Cache Thrashing

To avoid double-buffering cold experts in Linux's kernel page cache:

1. **Coalesced expert byte-range table:** For each shard file, all routed expert tensor byte intervals `[first, last)` are sorted and merged into disjoint coalesced ranges.
2. **Deferred/non-resident mapping:** Dense tensors (attention, norms, shared experts, embeddings, router gates) are loaded normally into VRAM or host RAM. Any `mmap` mapping covering shard files explicitly advises `MADV_DONTNEED` over coalesced routed-expert intervals immediately after header load (or skips mapping expert-only regions altogether).
3. **File identity pinning:** Every indexed source file records its immutable OS identity `(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns)`. Cache keys bind `(source_identity, logical_offset, expert_bytes)` per role so replacing a model file on disk cannot produce silent stale hits.
4. **Direct descriptors:** Each shard is opened with `O_RDONLY | O_DIRECT | O_CLOEXEC` (and `O_NONBLOCK` during open, followed by `fstat` regular-file verification) for expert streaming. When a configured direct read fails, the error propagates explicitly rather than silently falling back to page-cached `mmap`.

---

## 3. Three-Tier Memory Hierarchy, Admission Control & Eviction

### 3.1 Tier Responsibilities

| Tier | Backing Medium | Target T5820 Capacity | Pinned / Cached Residents | Eviction / Movement Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 0** | Dual Intel Arc Pro B65 VRAM | 64 GiB combined (minus driver/graph reserve) | Attention weights, dense MLP layers, shared experts, router gates, embeddings, KV cache, active GPU staging ring, optional hot expert slots | Static dense placement (multi-GPU layer split) + dynamic staging ring; shrinks before compute graph OOM |
| **Tier 1** | Host DDR4 RAM | 64 GiB physical (bounded by cgroup v2 & `MemAvailable`) | Bounded non-THP (`MADV_NOHUGEPAGE`) routed-expert cache arena, pinned H2D staging buffers, runtime metadata | Frequency-decay LFU (`count_decay`) / LRU with active leases, Tier-0 backup priority eviction, synchronous pressure reclaim |
| **Tier 2** | Dual PCIe NVMe SSD Array | 2 × 4 TB (8 TB raw) | Cold routed MoE experts (direct GGUF extents or 4 KiB-aligned expert packs), optional private unlinked KV spill file | Read-only unbuffered direct async I/O into reusable staging ring (`O_DIRECT` + `io_uring` / aligned `pread`) |

### 3.2 Dual-Term Host Memory Arbiter & Admission-Before-First-Touch

Linux workloads running large GGUF streams risk silent cgroup OOM kills if expert caches size themselves purely against physical RAM. The host memory arbiter enforces a dual-term admission envelope before any cache or working-buffer allocation touches pages:

1. **Cgroup v2 Term:** Reads the tightest `memory.max` and `memory.current` (plus reclaimable file pages from `memory.stat` when enabled) along the process's cgroup hierarchy, subtracting a fixed safety reserve (default `512 MiB`).
2. **System Available Term:** Reads `/proc/meminfo` (`MemAvailable`, `Active(file)`, `Inactive(file)`, `KReclaimable`/`SReclaimable`) and computes Linux kernel watermark-boost headroom from `/proc/zoneinfo` and `/proc/sys/vm/watermark_boost_factor`. The effective system ceiling is `MemAvailable - watermark_boost_headroom - max(host_headroom_mib, reserve_mib)`.
3. **Allocation Tickets (RAII Admission):**
   - Every allocation requests a ticket for `requested_bytes` before calling `mmap`/`posix_memalign` or touching memory pages.
   - Granted tickets debit an atomic `pending_bytes` counter so concurrent allocations cannot oversubscribe before first touch materializes RSS.
   - Upon allocation and page touch completion, the ticket is committed (releasing `pending_bytes` into measured OS accounting); on error, the ticket cancels cleanly.
4. **Synchronous Pressure Reclaimer:**
   - Compute buffers, KV cache growth, and checkpoint allocations have higher priority than the expert cache.
   - Before rejecting a required runtime allocation, the arbiter invokes a registered reclaimer callback that drops cold Tier-1 RAM cache slots (and releases their physical pages immediately via `madvise(MADV_DONTNEED)` or per-slot unmap) until the requested headroom is satisfied.
5. **Exact Slot Cost Accounting:**
   - Automatic RAM cache sizing solves via binary search for the maximum slot count `N` such that:
     `N * (page_aligned_slot_bytes + page_table_overhead) + entry_metadata_bytes + frequency_table_bytes + guard_margin <= available_budget`.
   - The payload arena disables transparent huge pages (`MADV_NOHUGEPAGE`) to prevent 2 MiB THP fragmentation from invalidating 4 KiB reclaim granularity.

### 3.3 Cache Replacement, Leases & Speculative Prefetch

- **Slot Layout:** Each cache slot holds all three roles (`up`, `gate`, `down`) sequentially at 4 KiB-aligned offsets with total stride `ceil((read_bytes[up] + read_bytes[gate] + read_bytes[down]) / page_size) * page_size`.
- **Per-Layer Uniform Quota:** Total enabled slots are distributed uniformly across routed layers (with optional per-layer overrides or cross-layer borrowing during prefill lookahead).
- **Eviction Ordering:** When admitting an expert into a layer:
  1. Empty or never-used prewarmed slot.
  2. Backup slot holding an expert currently mirrored in Tier-0 VRAM (when a VRAM tier is active).
  3. Lowest-priority unleased, non-inflight slot under the configured policy:
     - **`count_decay` (default):** Exponentially decayed hit frequency (`score *= decay_factor` periodically every `decay_interval` steps) breaking ties by oldest `last_touch` logical clock. This captures skewed MoE Zipfian routing while adapting smoothly when prompt topics shift.
     - **`lru` / `lfu`:** Supported as deterministic alternatives for testing and ablation.
- **Lease & In-Flight Safety:** Slots currently bound to an active compute graph or queued in an H2D transfer hold a non-zero `leases` reference count; slots receiving an async NVMe read set `inflight = true`. Neither may be evicted, overwritten, or reclaimed until drained.
- **Speculative Next-Layer Prefetch & Prefill Lookahead:**
  - During decode, each layer predicts top-ranked candidate experts for layer `L + 1` (up to `prefetch_depth`).
  - A speculative NVMe read is issued only when the expected I/O savings exceed the expected stall penalty: `P(rank_used) > remaining_read_fraction_at_layer_boundary`, using online exponentially weighted moving averages of layer compute gaps and NVMe read rate.
  - During multi-token prefill, lookahead borrows cold/empty slots from completed layers transiently and returns them after layer `L + 1` consumes them.

### 3.4 Asynchronous Direct-I/O Read Ring

- **Linux Primary Path (`io_uring`):** Direct kernel syscall interface (`io_uring_setup`, `io_uring_enter`, `io_uring_register`) avoiding external `liburing` library coupling, with optional `IORING_REGISTER_BUFFERS` fixed staging buffers (requiring sufficient `RLIMIT_MEMLOCK`).
- **Portable Direct-I/O Fallback (`pread` Worker Pool):** When `io_uring` is unavailable or disabled in constrained environments (e.g., restricted seccomp profiles or unit tests), an aligned `O_DIRECT` `pread` worker thread pool implements the identical submission/completion queue contract.
- **Reusable Staging Ring:** Fixed depth of `R = 8` expert staging slots (`8 * 3 = 24` concurrent role read operations in flight), each 4 KiB-aligned, reused in FIFO/ring order as compute consumes completed experts.
- **Drain-Before-Free Invariant:** Closing a ring, shrinking a cache, or recovering from an I/O error MUST submit remaining SQEs and drain every pending completion before unmapping or freeing any target buffer.

---

## 4. Hardware Probing & Adaptive Bypass Engine

### 4.1 Machine Profile vs. Live Launch State

Hardware characteristics are separated into two strict categories:

1. **Cached Static Machine Profile** (invalidated automatically if hardware identity, kernel release, GPU driver version, or total RAM >1% changes):
   - **CPU Topology:** Logical core count, core/package/SMT siblings, performance vs. efficiency cluster splits, pinning capability, and SIMD ISA features.
   - **DRAM & CPU Compute:** DRAM streaming bandwidth and per-quantization matrix-vector/matrix-matrix throughput vs. thread count.
   - **GPU Inventory:** PCI/driver enumeration for Vulkan/SYCL/ROCm/CUDA devices (e.g., dual Intel Arc Pro B65 32 GiB × 2), H2D pinned/pageable transfer rates, and device bandwidth.
   - **NVMe Storage Profile:** Keyed by physical device model + SHA-256 digest of serial number (tracing through partitions, mdraid, and dm-crypt/LVM). Measured non-destructively via direct random reads across existing ≥1 GiB model shards (or an uncached temporary 4 GiB test file deleted immediately afterward) sweeping request sizes (`64 KiB`, `256 KiB`, `1 MiB`, `4 MiB`) and queue depths (`1, 2, 4, 8, 16, 32`). Records median bandwidth (`Bps`), latency quantiles (`p50`, `p90`, `p99`), and **knee queue depth** (smallest QD whose best run reaches the worst run of the fastest QD).
2. **Live Dynamic Launch State** (measured fresh on every worker startup, never cached):
   - Free VRAM per GPU and detection of competing compute processes (triggering automatic VRAM reserve, e.g. `1024 MiB` when shared, `0` when dedicated).
   - Live Linux `MemAvailable`, watermark-boost headroom, and active cgroup v2 `memory.max` / `memory.current`.
   - Allowed CPU affinity mask (`sched_getaffinity`).

### 4.2 Adaptive Tier Bypass Decision Matrix

At worker launch, the runtime computes the model's exact memory requirements from GGUF headers:
- `dense_bytes`: non-routed weights (attention, shared experts, embeddings, norms, routers).
- `routed_bytes`: total routed MoE expert weights across all layers.
- `kv_and_scratch_bytes`: context KV cache footprint + compute graph scratch + safety reserve.
- `total_model_bytes = dense_bytes + routed_bytes + kv_and_scratch_bytes`.

Given live `usable_vram_bytes` (sum of free VRAM across assigned GPUs minus reserves) and `usable_ram_bytes` (dual-term host arbiter surplus):

| Mode | Condition | Placement & Execution Behavior |
| :--- | :--- | :--- |
| **`bypass_vram`** | `total_model_bytes <= usable_vram_bytes` (e.g., models ≤ 64 GiB effective VRAM on dual Arc Pro B65) | **NVMe streaming completely bypassed.** All layers (dense + routed experts) offloaded to VRAM across GPUs (`-ngl 999`, layer split). Zero RAM expert cache overhead, zero direct-I/O threads. |
| **`bypass_ram`** | `total_model_bytes > usable_vram_bytes` AND `total_model_bytes <= usable_vram_bytes + usable_ram_bytes` (e.g., ~64–115 GiB models on T5820) | **NVMe streaming bypassed.** Dense layers + maximum fitting layers pinned in VRAM; remaining routed experts kept resident in host RAM (`mmap` / pinned host buffers) without direct NVMe streaming. |
| **`nvme_stream`** | `total_model_bytes > usable_vram_bytes + usable_ram_bytes` AND model has validated routed MoE tensors (e.g., 177B–800B+ MoE checkpoints) | **Three-tier NVMe streaming activated.** Dense layers + KV cache pinned in dual Arc Pro B65 VRAM; routed expert `mmap` ranges dropped (`MADV_DONTNEED`); Tier-1 RAM expert cache sized from dual-term arbiter; Tier-2 direct-I/O NVMe streaming ring and speculative prefetch enabled. |
| **`dense_spill`** | `total_model_bytes > usable_vram_bytes + usable_ram_bytes` AND model has no routed experts | Dense layer placement orders layers via bit-reversed indexing into VRAM → pinned host RAM → NVMe streaming ring (`ring_weights = 4`). |

### 4.3 CPU Isolation & Thread-Pool Sizing

- **Compute Pools:** Decode thread count (`-t`) selects the minimum thread count reaching the memory-bandwidth saturation plateau (avoiding barrier wait inflation); prefill thread count (`-tb`) selects maximum compute throughput leaving at least one core free for I/O.
- **I/O Thread Pinning (`io_cpus`):** Direct-I/O submission/completion and prefetch threads are pinned outside the decode compute mask so NVMe completion interrupts and submission queues do not preempt compute threads at layer barriers.
- **Dynamic Contention Reserve:** Between decode tokens, non-compute CPU busy time is measured so decode participant count yields cleanly when GPU backend driver threads or background I/O consume cores.

---

## 5. Non-CUDA GPU Backend Hooks (Vulkan & SYCL for Dual Intel Arc Pro B65)

### 5.1 Backend-Agnostic Provider Boundary

Core storage, I/O, host-arbiter, and placement-policy components must have **zero compile-time or link-time dependencies on CUDA, ROCm, SYCL, or Vulkan headers**. GPU backends expose optional capabilities through a versioned, size-checked provider table queried from `ggml`'s backend registry:

- **Device capability flags:** Unified vs. discrete memory, supported quantized weight types, minimum imported host pointer alignment, and multi-device layer-split geometry.
- **Dual Arc Pro B65 discrete topology:** Both cards are discrete PCIe GPUs (32 GiB VRAM each, 64 GiB aggregate). Dense layers and attention KV caches are split across both GPUs (`--split-mode layer` with balanced per-card capacity accounting).

### 5.2 Asynchronous Staging Ring & Graph Lane Synchronization

For non-CUDA GPU backends (Vulkan and SYCL on Intel Arc Pro B65):

1. **Alignment-Safe Host Staging:** Vulkan and SYCL host-pointer imports enforce strict device alignment (`minImportedHostPointerAlignment`, conservatively padded to **64 KiB** for staging allocations). Staging buffers are allocated via aligned host memory and registered once per pass/context rather than per expert.
2. **Double/Ring Device Staging (`ring_weights = 4`):** When streaming weights or offloading heavy prefill experts to GPU command queues, a 4-slot device staging ring overlaps asynchronous H2D DMA transfers (`vkCmdCopyBuffer` / SYCL `queue::memcpy` on a dedicated transfer queue/stream) with compute queue execution (`up -> gate -> activation -> down`) using explicit event/semaphore fences.
3. **Workload-Aware Decode vs. Prefill Split:**
   - **Prefill (High Token Multiplicity):** Routed experts receiving many tokens in a prompt batch achieve high arithmetic intensity (one weight matrix read amortizes across many token rows). An online least-squares cost model (`cost = fixed_us + routes * route_us + h2d_bytes / link_gbps`) offloads heavy experts whose reads have landed to the Vulkan/SYCL graph lane while lighter experts run concurrently on CPU threads.
   - **Decode (1 Token / Expert):** On discrete PCIe GPUs without a resident VRAM expert tier, streaming a cold expert from NVMe → RAM → PCIe H2D for a single token incurs double transfer latency. Decode therefore computes RAM-cached and NVMe-streamed experts directly on the CPU threadpool (or in VRAM if resident), avoiding PCIe/command-queue stalls in the decode loop.
4. **Deterministic Teardown & Quiescing:** Before freeing any staging buffer, shrinking the RAM cache, or destroying a backend context, the runtime flushes pending GPU command queues/events and joins all asynchronous worker/I/O threads.

---

## 6. Worker Networking, Security & Gateway Integration

To preserve `homelab-ai`'s defense-in-depth contract:

- **Loopback-Only Worker Binding:** Every `llama.cpp` / NVMe-streaming worker endpoint MUST bind strictly to `127.0.0.1` (rejecting `0.0.0.0`, `::`, or external interface addresses at configuration validation and launch time).
- **Gateway Front Door:** All client traffic, authentication, RBAC role enforcement, PII redaction, and request routing continue to terminate at `orchestrator_gateway`.
- **Runtime-Agnostic Worker Abstraction:** NVMe MoE streaming is exposed as an additive capability profile inside `orchestrator_runtime`, preserving compatibility with existing non-streaming `vllm` and `llama.cpp` workers.

---

## 7. Observability, Stall Detection & Telemetry Contract

### 7.1 Structured Runtime Events

Workers optionally emit a sequence-numbered UTF-8 JSONL stream (`v=1`, contiguous `seq`, event name `ev`) recording effective configuration, per-layer placement/cache outcomes (`selected_experts`, `vram_hit`, `ram_hit`, `nvme_miss`, `wall_us`, `wait_io_us`, `compute_us`), and prefill batch summaries.

### 7.2 Prometheus Exporter Metrics

The Prometheus exporter exposes the following NVMe MoE streaming metrics (all with safe zero/idle fallbacks when streaming is bypassed or idle):

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `homelab_ai_moe_expert_cache_hits_total` | Counter | `worker`, `tier` (`vram`\|`ram`), `model` | Cumulative routed expert lookups served from VRAM or RAM cache without NVMe read. |
| `homelab_ai_moe_expert_cache_misses_total` | Counter | `worker`, `model` | Cumulative routed expert lookups requiring a Tier-2 NVMe direct read. |
| `homelab_ai_nvme_expert_read_latency_seconds` | Histogram | `worker`, `role` (`up`\|`gate`\|`down`\|`expert`), `model` | Distribution of Tier-2 NVMe direct-I/O read latencies for cold routed experts. |
| `homelab_ai_nvme_stream_bandwidth_bytes_per_sec` | Gauge | `worker`, `model` | Rolling effective NVMe expert streaming read throughput in bytes/second. |
| `homelab_ai_nvme_io_wait_ratio` | Gauge | `worker`, `model` | Fraction of layer execution wall time spent blocked on NVMe/PCIe I/O (`wait_io_us / wall_us`). |
| `homelab_ai_moe_streaming_mode` | Gauge | `worker`, `mode` (`bypass_vram`\|`bypass_ram`\|`nvme_stream`\|`dense_spill`), `model` | Active tier placement mode (1 for active mode, 0 otherwise). |

### 7.3 Stall-Detection Integration

Existing inference stall-detection gauges incorporate NVMe/PCIe I/O wait alongside GPU compute/memory stalls:
- A worker reports an **NVMe I/O stall condition** when active decode generation is in flight (`inflight_requests > 0`) AND either:
  1. `nvme_io_wait_ratio` exceeds the configured stall threshold (default `0.75`) over the evaluation window, OR
  2. Average NVMe expert read latency exceeds the latency ceiling (default `50 ms` per expert read) while cache hit rate drops below threshold (thrashing), OR
  3. Kernel PSI `some avg10` I/O pressure or block-device queue wait stalls exceed bounds.

---

## 8. Host Provisioning & Linux Kernel Tuning (Ubuntu 26.04 / T5820)

To guarantee predictable tail latencies and prevent page-cache OOMs on Ubuntu 26.04 (`systemd` + `cgroup v2`):

1. **NVMe Mount Options:** Dedicated model/expert NVMe array mounted with `noatime,nodiratime` (eliminating metadata write amplification on read-heavy direct I/O; `ext4` with `data=ordered` or `xfs` with aligned allocation groups).
2. **Block Device / I/O Scheduler Tuning (udev rules):**
   - Set NVMe I/O scheduler to `none` (bypassing unnecessary legacy elevator queuing on NVMe multi-queue hardware).
   - Tune `nr_requests` (e.g., `256`–`512`) and `read_ahead_kb` (`0` or low `16` KiB on dedicated direct-I/O model volumes so incidental buffered reads do not bloat page cache) while maintaining optimal random 4 KiB/64 KiB read latency.
   - Disable `add_random` (`0`) and set `rq_affinity=2` for deterministic completion locality.
3. **`systemd` + `cgroup v2` Memory & Memlock Guardrails:**
   - Dedicated worker slice/unit sets explicit finite `MemoryMax` (e.g., leaving 8–10 GiB for OS, gateway, and monitoring on a 64 GiB T5820 host), `MemoryHigh` (soft throttle before hard OOM), `MemorySwapMax=0` (disabling swap to prevent catastrophic silent paging of expert caches), and `LimitMEMLOCK=infinity` (or bounded ≥ 4 GiB) to allow `io_uring` fixed-buffer registration and pinned H2D staging buffers.
4. **Sysctl Guardrails:**
   - `vm.swappiness=1`, `vm.dirty_background_ratio=5`, `vm.dirty_ratio=10`, `vm.vfs_cache_pressure=100` to keep kernel caches bounded and prevent sudden reclaim spikes.
5. **Build & Runtime Dependencies:**
   - Ensure `cmake`, `ninja-build`, `pkg-config`, `libvulkan-dev`, `glslc` / `vulkan-tools`, `intel-opencl-icd` / oneAPI Level Zero / SYCL runtime headers (when SYCL backend enabled), `liburing-dev` (optional diagnostic tooling), `nvme-cli`, and `fio` are provisioned cleanly via Ansible.

---

## 9. Verification & Steady-State Benchmark Methodology

### 9.1 Automated Verification Suite

- **GGUF Offset & Alignment Tests:** Synthesize deterministic mock GGUF v3 binary files containing dense tensors and 3D routed MoE expert tensors (`Q4_K`, `Q8_0`, `F16`, mixed layer quantizations), verifying exact byte offsets, 4 KiB direct-I/O alignment (`aligned_offset`, `data_offset`, `aligned_bytes`), multi-shard resolution, and coalesced `MADV_DONTNEED` range generation.
- **Cache Eviction & Arbiter Tests:** Verify `count_decay` LFU and LRU eviction order, active lease protection, Tier-0 backup prioritization, dual-term cgroup + `MemAvailable` watermark-boost headroom enforcement, and synchronous pressure reclaim.
- **Adaptive Bypass Tests:** Verify exact mode transitions (`bypass_vram`, `bypass_ram`, `nvme_stream`, `dense_spill`) across T5820 hardware profiles (64 GiB dual Arc Pro B65 VRAM + 64 GiB RAM) for 32B/70B/177B/763B models.
- **Security & Observability Tests:** Verify strict `127.0.0.1` loopback enforcement, Prometheus exposition of all required `homelab_ai_*` metrics, idle zero-value fallbacks, and NVMe I/O wait integration into stall gauges.

### 9.2 Repeatable 4K Prefill vs. Steady-State Decode Benchmark

To isolate steady-state NVMe streaming decode from prefill and cold-cache warmup:

- **Fixed Workload:** Fixed ~4K-token prompt (SHA-256 recorded), `max_tokens = 256`, greedy decoding (`temperature = 0.0`, `top_k = 1`), EOS ignored/suppressed (`ignore_eos = true`), prompt caching disabled (`cache_prompt = false`).
- **Monotonic Per-Token Timing:** Record `t_start`, `t_tok[1..256]` via `time.monotonic_ns()` over streaming SSE token events:
  - `prefill_time_s = (t_tok[1] - t_start) / 1e9` (TTFT)
  - `prefill_tok_per_s = actual_prompt_tokens / prefill_time_s`
  - `warmup_decode_tok_per_s = 127 / ((t_tok[128] - t_tok[1]) / 1e9)` (tokens 1–128)
  - `steady_decode_tok_per_s = 128 / ((t_tok[256] - t_tok[128]) / 1e9)` (tokens 129–256 — primary steady-state metric)
- **Outputs:** Emit both structured JSON provenance artifact (host hardware, model hash, mode, latency quantiles, cache hit rate, NVMe bandwidth) and Prometheus textfile / exposition format for Grafana/Alertmanager ingestion.
