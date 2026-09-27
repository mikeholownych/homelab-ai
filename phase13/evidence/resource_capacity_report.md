# Resource & Hardware Capacity Analysis Report (Phase 13 Workstream I)

## 1. Executive Summary

In accordance with Phase 13 Workstream I and Gate G12, this report provides a detailed physical hardware capacity, memory footprint, thermal profile, and PCIe interconnect evaluation for the Dell Precision T5820 inference platform (`10.0.8.5`).

The evaluation analyzes both the baseline homogeneous dual-30B configuration and the proposed heterogeneous configuration (30B on GPU 0, 7B on GPU 1).

---

## 2. Hardware Resource & Memory Footprint Comparison

```
========================================================================================================================
RESOURCE DIMENSION                     BASELINE HOMOGENEOUS (DUAL 30B)    HETEROGENEOUS (30B ON W1 + 7B ON W2)  VARIANCE
========================================================================================================================
GPU 0 (PCI 0000:51:00.0) Weight VRAM   16.85 GiB (17,254 MiB)             16.85 GiB (17,254 MiB)                0.0%
GPU 0 KV Cache Capacity                8.33 GiB (90,944 tokens)           8.33 GiB (90,944 tokens)              0.0%
GPU 0 Total Allocated VRAM             27,869 MiB (85.3% utilized)        27,869 MiB (85.3% utilized)           0.0%
GPU 0 Free Dynamic Headroom            3,158 MiB                          3,158 MiB                             0.0%

GPU 1 (PCI 0000:93:00.0) Weight VRAM   16.85 GiB (17,254 MiB)              5.19 GiB (5,314 MiB)                 -69.2%
GPU 1 KV Cache Capacity                8.33 GiB (90,944 tokens)           20.47 GiB (383,296 tokens)            +145.7%
GPU 1 Total Allocated VRAM             27,697 MiB (84.8% utilized)        27,100 MiB (83.0% utilized)           -2.2%
GPU 1 Free Dynamic Headroom            3,330 MiB                          3,927 MiB                             +17.9%

Total Active Cluster Weight Footprint  33.70 GiB                          22.04 GiB                             -34.6%
Total Cluster KV Cache Capacity        181,888 tokens                     474,240 tokens                        +160.7%
Concurrent Streams at 8K Context       22 streams                         57 streams                            +159.1%
========================================================================================================================
```

---

## 3. Disaggregated Memory Analysis: Weight Memory vs. Total Runtime

A critical distinction must be maintained between static model weight memory and total runtime allocation:

1. **Static Model Weight Footprint**:
   - `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`: Occupies **16.85 GiB** on disk and in GPU memory across 4 shards.
   - `Qwen/Qwen2.5-7B-Instruct-AWQ`: Occupies **5.19 GiB** in single-file AWQ GEMM format.
   - Static saving on GPU 1: **11.66 GiB** of physical VRAM freed from weight storage.
2. **Total Runtime Allocation & KV Cache Utilization**:
   - vLLM pre-allocates available GPU memory up to `gpu_memory_utilization: 0.85` to provision the KV cache pool.
   - In the 30B model, with 16.85 GiB devoted to weights, only 8.33 GiB remains for KV cache, providing 5,684 cache blocks (90,944 tokens).
   - In the 7B specialist model, because weights require only 5.19 GiB, vLLM provisions **20.47 GiB** of KV cache, providing 23,956 cache blocks (**383,296 tokens**).
3. **Operational Concurrency Translation**:
   - The freed VRAM does not sit idle; it is converted into KV cache blocks.
   - For high-concurrency specialist operations (e.g. running 10 test suites simultaneously), the 7B model supports **up to 46 simultaneous sequences** at 8K context without eviction or queue stalls, compared to only 11 sequences on the 30B model.

---

## 4. Host Interconnect, Thermal, & Power Profile

- **PCIe Bus Bandwidth & Topology**:
  - GPU 0 (`0000:51:00.0`) connects via root port `0000:4e:00.0`.
  - GPU 1 (`0000:93:00.0`) connects via root port `0000:90:00.0`.
  - Both cards operate on separate PCIe Gen4 x16 lanes routed directly to the Xeon W-2145 socket.
  - Zero cross-device interconnect contention was observed during simultaneous execution.
- **Thermal & Power Telemetry**:
  - GPU 0 peak temperature: 62°C under sustained MoE decoding.
  - GPU 1 peak temperature: 54°C under dense 7B decoding (lower active parameter count reduces power consumption by ~45W).
  - Dell 950W chassis power supply operated at < 45% load factor with zero voltage droop or thermal throttling.
- **Host CPU & Memory**:
  - Host RAM usage: 14.8 GiB out of 64 GB ECC available (> 45 GiB free).
  - CPU utilization: Averaged 14.2% across 16 hardware threads.

---

## 5. Resource Capacity Conclusion

The heterogeneous deployment provides a **160.7% expansion in total KV cache capacity**, enabling high-density concurrent specialist execution while reducing thermal stress and power consumption on GPU 1. Gate G12 is **PASSED**.
