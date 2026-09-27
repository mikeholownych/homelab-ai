# Phase 12 Physical Inference Evaluation Results

## 1. Executive Summary

This report documents the physical inference evaluation conducted on authorized capacity during Phase 12. 

In strict adherence to Operating Authority (Section 2) and Gate G7/G8 criteria:
1. Physical inference measurements were executed against the authorized live resident serving endpoint `engineering/b0` (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on GPU 0).
2. For alternative candidate `Qwen/Qwen2.5-7B-Instruct-AWQ`, physical execution would require replacing protected resident Worker 2 (`vllm-xpu-tp1-worker2` on GPU 1). Because explicit human authorization for a protected-model swap was not granted, **the physical swap was stopped and Gate G7/G8 are recorded as BLOCKED**.
3. In strict compliance with governance rules, **simulation is NOT substituted for physical candidate execution**.

---

## 2. Authorized Physical Endpoint Telemetry: Protected Resident Control

The live serving endpoint on local port `18010` (forwarded to `10.0.8.5:8010`) backed by dual Intel Arc Pro B65 GPUs was evaluated across baseline calibration workloads:

```
========================================================================================================
METRIC CATEGORY                             PHYSICAL MEASUREMENT           MEASUREMENT SOURCE
========================================================================================================
Resident Model Identifier                   cyankiwi/Qwen3-Coder-30B-AWQ   vLLM Config & API Header
Served Model Alias                          engineering/b0                 HTTP GET /v1/models
Physical GPU VRAM Allocation                27,869 MiB (GPU 0) / 27,861 MiB xpu-smi memory stats
Memory Utilization                          85.3% of 32,656 MiB physical   xpu-smi tile utilization
Time to First Token (TTFT)                  0.342 seconds                  Live HTTP streaming probe
Decode Throughput (Single Sequence)         32.4 tokens / second           Live completion benchmarks
Prefill Throughput                          285.6 tokens / second          Context prefill latency
Average Task Execution Latency              14.5 seconds                   4 calibration tasks
Independent Acceptance Rate                 100.0% (4 / 4 accepted)        Automated pytest test runners
Worker Health & Restarts                    0 crashes, 0 restarts (41+ hrs) Podman container inspect
========================================================================================================
```

---

## 3. Alternative Candidate Evaluation: `Qwen/Qwen2.5-7B-Instruct-AWQ`

### 3.1 Preflight & Physical Resource Availability
- **Weight Footprint**: 5.3 GB on disk (`/var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ`)
- **Required VRAM**: 7,185.0 MiB (weights + runtime overhead + 32K context KV cache)
- **Physical Headroom Available on Active GPUs**:
  - GPU 0: $31,023 - 27,869 = 3,154\text{ MiB}$ available (Insufficient for 7B model)
  - GPU 1: $31,023 - 27,861 = 3,162\text{ MiB}$ available (Insufficient for 7B model)
- **Deployment Requirement**: Loading the candidate requires stopping `vllm-xpu-tp1-worker2` on GPU 1 and updating its container mount to point to the 7B model snapshot.

### 3.2 Operating Authority Enforcement
Under Section 2:
> *"You are not authorized to: Unload or replace either protected resident model without explicit human authorization... If physical candidate testing requires a protected-model swap, complete all non-disruptive preparation and stop only the affected experiment pending explicit authorization."*

Under Section 17:
> *"Do not mark G7 or G8 as satisfied using the existing engineering/b0 control alone. If alternative physical model testing requires maintenance that has not been authorized, record those gates as blocked rather than substituting simulation."*

### 3.3 Candidate Evaluation Disposition
- **Candidate Physical Execution Status**: **STOPPED PENDING HUMAN AUTHORIZATION**
- **Gate G7 Status**: **BLOCKED**
- **Gate G8 Status**: **BLOCKED** (Awaiting real outputs from an authorized alternative model)
- **Prepared Maintenance Artifact**: [`maintenance_and_rollback_plan.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase12/evidence/maintenance_and_rollback_plan.md) (Fully prepared for operator signoff).
