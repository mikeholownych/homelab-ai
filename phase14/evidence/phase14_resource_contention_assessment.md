# Phase 14 Experiment 02: Physical Resource Contention Assessment

- **Date:** 2026-09-29
- **Host Target:** Dell Precision T5820 (Intel Xeon W-2145, 64 GB DDR4, dual Intel Arc A770 16GB)
- **Engine Core:** vLLM v0.6.x XPU Tensor-Parallel 1 Containerized Service

---

## 1. Physical Contention Mechanisms

Forensic analysis of the physical host and container engine identified three primary interaction dimensions:

### A. GPU Compute & Execution Sharing (Continuous Batching)
vLLM implements continuous iteration-level scheduling. When multiple requests arrive:
- Prompt prefill chunks (e.g. 2,582 to 3,165 tokens for OpenCode) preempt or share compute cycles with ongoing token generation.
- Decode iterations for co-scheduled requests run together in fused GEMM kernels.
- **Empirical Measurement:** During Burst 2, Worker 1 vLLM engine loggers reported:
  - Generation throughput jumped from nominal single-stream 18.2 tokens/s to 33.9 tokens/s (aggregate across 2 concurrent streams).
  - Effective per-stream generation throughput slowed from ~18.2 tokens/s to ~11.3 - 12.2 tokens/s.
  - This ~35% degradation in per-stream decode speed prolonged item latencies for Projects 5 and 6.

### B. KV-Cache Memory Allocation
- Single-request KV-cache allocation on Worker 1 nominally consumed **0.3% - 0.8%** of available GPU KV-cache blocks.
- During Burst 2 (06:24:32 - 06:25:42), GPU KV-cache usage rose to **3.9%**.
- Because KV-cache usage peaked at <4%, **no cache eviction, swapping to CPU host RAM, or request preemption occurred**. The memory subsystem remained stable.

### C. Host CPU, RAM, and Thermals
- Host CPU utilization (Xeon W-2145 8C/16T) remained below 15% throughout the campaign.
- Host memory usage remained steady at ~14.2 GB of 64 GB.
- Intel Arc A770 temperatures remained nominal: GPU 0 peaked at $61^\circ\text{C}$ and GPU 1 peaked at $58^\circ\text{C}$, well below the $90^\circ\text{C}$ thermal throttling threshold.

---

## 2. Contention Impact Summary

| Subsystem | Contention Level | Evidence / Metric | Operational Impact |
|---|---|---|---|
| **GPU Compute (Worker 1)** | **Moderate** | Generation rate dropped to 11-12 tok/s per stream | Item duration extended by 10-15s |
| **GPU Compute (Worker 2)** | **Negligible** | 2 requests near end of run (<20s) | Minor (~2s) delay on last item |
| **KV Cache Capacity** | **Zero Stress** | Peak usage 3.9% (plenty of headroom) | Zero swaps, zero preemptions |
| **Host CPU / Memory** | **Zero Stress** | CPU <15%, RAM 22% | No operating system bottlenecks |
| **Thermal Subsystem** | **Zero Stress** | Arc A770 peak temp $61^\circ\text{C}$ | Zero thermal throttling observed |

---

## 3. Directional Bias on Experimental Findings

Because all contention fell on Configuration B+ during Regime 2:
1. **Configuration B+ metrics were pessimistically degraded:** Turnaround latencies, P95 tail latencies, and queue wait times for Projects 5 and 6 under B+ reflect an artificially loaded worker, rather than pure single-tenant performance.
2. **Configuration B metrics were optimistically isolated:** Configuration B ran with 100% of GPU compute dedicated exclusively to its workload.
3. **Robustness Implication:** The fact that Configuration B+ still outperformed Configuration B by +10.15% in accepted throughput (17.79 vs 16.15 proj/hr) despite this unmodeled background load demonstrates the architectural power of offloading Item 01.
