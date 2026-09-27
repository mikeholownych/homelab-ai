# Operational Performance Results: Work-Per-Hour & Multi-Agent Telemetry

## 1. Executive Summary & Primary Metric Formulation

In accordance with Phase 13 Workstream F, Section 10, and Gate G10, this report presents the disaggregated operational performance metrics of the Autonomous Engineering System.

### Primary Operational Target:
$$\mathbf{INDEPENDENTLY\_ACCEPTED\_ENGINEERING\_WORK\_PER\_HOUR}$$

To preserve scientific rigor and engineering integrity:
1. **No Collapsed Composite Scores**: Token throughput, wall-clock latency, validator pass rates, and hardware utilization are reported as distinct dimensions and are **never collapsed into an opaque composite metric**.
2. **Acceptance Floor Requirement**: A throughput gain that increases failed deliverables or unaccepted patches is strictly classified as a regression.
3. **Task-Level vs. Project-Level Separation**: Single-task specialist execution and full multi-stage project integration are measured and reported separately.

---

## 2. Disaggregated Operational Metrics Matrix

```
========================================================================================================================
METRIC DIMENSION                          BASELINE HOMOGENEOUS (DUAL 30B)    HETEROGENEOUS (30B W1 + 7B W2)  OPERATIONAL DELTA
========================================================================================================================
[PRIMARY METRIC: ACCEPTED WORK / HOUR]
Accepted Specialist Tasks / Hour          70.3 tasks/hr                      182.4 tasks/hr                  +159.5%
Accepted End-to-End Projects / Hour       4.12 projects/hr                   5.68 projects/hr                +37.9%

[TASK-LEVEL EXECUTION TELEMETRY]
Test Specialist Task Latency (TASK-09)    56.15s (Truncated in P12)          18.75s (Accepted in P12)        -66.6% (3.0x faster)
Structured Schema Latency (TASK-07)       56.47s (Truncated in P12)          10.13s (Accepted in P12)        -82.1% (5.6x faster)
Security Review Latency (TASK-08)         56.43s                             15.05s                          -73.3% (3.7x faster)
Specialist Decode Throughput              18.22 tokens/sec                   39.30 tokens/sec                +115.7% (2.16x faster)
Time to First Token (TTFT)                0.48s                              0.28s                           -41.7% (Faster)

[ACCEPTANCE & REPAIR TELEMETRY]
Specialist First-Pass Acceptance Rate     25.0% (P12 1024 cap) / 91.7% (Fair) 100.0% (12/12 accepted)        Parity / Superior
Specialist Final Acceptance (with repair) 91.7% (Fair 2048 budget)           100.0% (12/12 accepted)         +8.3%
Bounded Repair Turn Frequency             16.7% (2 of 12 tasks)              0.0% (0 of 12 tasks)            -16.7% (Less repair)
Validator Rejection Rate (Post-Repair)    8.3% (1 of 12 tasks)               0.0% (0 of 12 tasks)            -8.3%

[PROJECT-LEVEL MULTI-AGENT TELEMETRY]
End-to-End 8-Item Project Completion Time 873.8 seconds                      633.4 seconds                   -27.5% (-240.4s)
Average Queue Wait Time for Specialist    14.2 seconds                       2.1 seconds                     -85.2%
Specialist Handoff Overhead               0.00 seconds (Monolithic)          0.42 seconds                    +0.42s
Resource Contention / Bus Stalls          0.0% (Independent PCIe)            0.0% (Independent PCIe)         0.0% (Parity)
Service Errors / 5xx Faults               0.0%                               0.0%                            0.0% (Zero errors)

[HARDWARE & CAPACITY ENVELOPE]
GPU 1 Weight VRAM Footprint               16.85 GiB                          5.19 GiB                        -69.2% (-11.66 GiB)
GPU 1 KV Cache Allocation                 8.33 GiB (90,944 tokens)           20.47 GiB (383,296 tokens)      +145.7% (+292,352 tok)
GPU 1 Peak Operating Temperature          62°C                               54°C                            -8°C cooler
GPU 1 Average Active Power                145W                               100W                            -45W (-31.0%)
========================================================================================================================
```

---

## 3. Nuanced Operational Trade-Off Analysis

### 3.1 Specialist Throughput Acceleration vs. Multi-Stage Handoff Overhead
- **Acceleration**: Delegating test suite generation, OpenAPI synthesis, and SAST review to Worker 2 yields a **2.16x increase in decode speed** (39.30 tps vs 18.22 tps).
- **Handoff Overhead**: Inter-agent context serialization and provenance verification introduce an average overhead of **0.42 seconds** per handoff.
- **Net Operational Gain**: Because specialist tasks save between 30 and 45 seconds of generation time per task, the 0.42-second handoff penalty represents $< 1.5\%$ of the gross time savings. The net operational benefit is overwhelmingly positive.

### 3.2 Context Ceiling Boundary vs. KV Cache Concurrency
- **Context Ceiling**: The 7B specialist's 32K context cap prevents it from processing monolithic repository-scale prompts.
- **Concurrency Expansion**: However, within its 32K operating envelope, the 7B specialist provides **20.47 GiB of KV cache** (383,296 tokens), supporting up to 46 simultaneous 8K context streams.
- **Architectural Match**: This creates an ideal division of labor: Worker 1 handles deep, single-stream 64K architectural reasoning, while Worker 2 concurrently serves bursts of lightweight, fast specialist tasks without queue stalling.

---

## 4. Operational Performance Conclusion

Heterogeneous serving delivers a **37.9% increase in independently accepted engineering projects per hour** (from 4.12 to 5.68 projects/hr) and a **159.5% increase in specialist task throughput**, while reducing GPU 1 thermal and power load. Gate G10 is fully characterized.
