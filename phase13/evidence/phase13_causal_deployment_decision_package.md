# Phase 13 Causal Deployment Decision Package: Evidence-Driven Architectural Determination

## 1. Executive Deployment Determination

- **Governing Directive**: Phase 13 Continuation: Scheduling-Matched Causal Qualification
- **Release Baseline**: Commit [`054db16`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization) on branch `phase13-heterogeneous-qualification`
- **Physical Evaluation Framework**: Dell Precision T5820 (`10.0.8.5`), Dual Intel Arc Pro B65 GPUs
- **Terminal Architectural Finding**:

```
DECISION CLASSIFICATION: SCHEDULING IMPROVEMENT WITHOUT SPECIALIST-MODEL BENEFIT
```

### Production Serving Decision:
**RETAIN THE HOMOGENEOUS DUAL-30B INVENTORY AND ADOPT SCHEDULING-MATCHED TASK PLACEMENT (CONFIGURATION B)**.
Do **NOT** promote the heterogeneous candidate (Configuration C, Worker 2 with `Qwen/Qwen2.5-7B-Instruct-AWQ`) to production serving.

---

## 2. Four-Way Decision Matrix Analysis

Section 14 of the governing directive establishes four prospective qualification outcomes:

```
+----------------------------------------------------------------------------------------------------+
| FOUR-WAY DECISION OUTCOME MAPPING                                                                  |
+------------------------------------+-----------------------------------------------+---------------+
| Decision Finding                   | Empirical Evidence Criteria                   | Determination |
+------------------------------------+-----------------------------------------------+---------------+
| **1. Scheduling Improvement        | Configuration B delivers the primary speedup  | **SUPPORTED   |
|    Without Specialist Benefit**    | (A->B: +8.00% throughput, 70.4% latency gain) | BY EVIDENCE** |
|                                    | while C provides a bounded secondary gain.    |               |
+------------------------------------+-----------------------------------------------+---------------+
| **2. Incremental Heterogeneous     | Configuration C demonstrates a secondary gain | Conditionally |
|    Benefit**                       | (B->C: +3.48% throughput, 29.6% latency gain),| Valid (VRAM   |
|                                    | but speedup is truncated by Worker 1 barrier. | & Batch Only) |
+------------------------------------+-----------------------------------------------+---------------+
| **3. Workload-Specific Benefit**   | C improves bounded batch/offline regimes,     | **SUPPORTED   |
|                                    | but unsuited for general production routing.  | BY EVIDENCE** |
+------------------------------------+-----------------------------------------------+---------------+
| **4. No Valid Qualification**      | Mandatory observation, safety, acceptance, or | Refuted       |
|                                    | evidence integrity gates fail.                | (Gates Pass)  |
+------------------------------------+-----------------------------------------------+---------------+
```

### Empirical Grounding for Finding 1:
1. **The Scheduling Gain Delivers the Primary Acceleration (A vs. B)**:
   Offloading Item 06 (Security Review) to Worker 1 while dispatching Items 04 & 05 to Worker 2 on the existing dual-30B inventory reduces mean project latency by **$15.70$ seconds ($7.4\%$)** and Stage 2 latency by **$15.55$ seconds ($27.3\%$)** with overwhelming statistical significance ($t = 45.57, p = 9.61 \times 10^{-8}$). Completed throughput rises from $16.9850$ to $18.3446$ projects/hour ($+8.00\%$), accounting for **$70.4\%$ of total turnaround latency reduction**.
2. **The Model Gain is a Bounded Secondary Speedup (B vs. C)**:
   Under identical task placement and concurrency, swapping Worker 2 from the 30B MoE model to the 7B AWQ model reduces mean project latency by **$6.60$ seconds ($3.4\%$)** and Stage 2 latency by **$6.62$ seconds** ($t = 22.99, p = 2.90 \times 10^{-6}$), accounting for **$29.6\%$ of total turnaround latency reduction**.
3. **The Specialist Speedup is Truncated by the Worker 1 Barrier**:
   Because Worker 1 requires $\approx 34.88$ s to complete Item 06, Worker 2 finishing Items 04 & 05 in $19.20$ s (7B) rather than $40.88$ s (30B) results in Worker 2 sitting idle for **$15.68$ seconds** waiting for Worker 1. The 7B model's theoretical $78.7\%$ token decode speedup is heavily truncated by the Worker 1 critical path barrier.
4. **Security Vulnerability Overhead**:
   The 7B model complies with prompt injection in $60\%$ of test cases, requiring active defense-in-depth quarantine. Swapping to 7B introduces an expanded security attack surface while delivering only a $+3.48\%$ throughput increment ($+0.64$ projects/hour) over the secure dual-30B baseline.

---

## 3. Approved Production Operating Envelope (Configuration B)

The following architectural specification is approved for production deployment under human signoff:

```
+----------------------------------------------------------------------------------------------------+
| APPROVED PRODUCTION SERVING CONFIGURATION (CONFIGURATION B)                                        |
+----------------------------+-----------------------------------------------------------------------+
| Subsystem                  | Production Specification                                              |
+----------------------------+-----------------------------------------------------------------------+
| **Worker 1 (GPU 0)**       | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (Port 8000)         |
| **Worker 2 (GPU 1)**       | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (Port 8001)         |
| **Gateway Routing**        | Round-robin across Workers 8000 & 8001 on Port 8010                   |
| **Stage 1 Assignment**     | Items 01, 02, 03 -> Worker 1 (Authoritative Lead)                     |
| **Stage 2 Assignment**     | Items 04 & 05 -> Worker 2 (Specialist); Item 06 -> Worker 1 (Security)|
| **Stage 3 Assignment**     | Items 07 & 08 -> Worker 1 (Integration & Final Acceptance)            |
| **Concurrency Limits**     | Worker 1: 1 active seq; Worker 2: 2 active seqs (max-num-seqs: 2)     |
| **Expected Throughput**    | 18.97 independently accepted projects/hour (completed saturation)     |
| **Expected Latency**       | 189.78 s mean project turnaround (down from historical 211.94 s)      |
+----------------------------+-----------------------------------------------------------------------+
```

---

## 4. Conditional Role for 7B Specialist (Workload-Specific Offline Envelope)

While disqualified from general interactive production serving, the 7B AWQ candidate is conditionally qualified for **asynchronous batch processing and VRAM-constrained offline sidecars**:

- **Operating Regime**: Large batch test-suite generation where thousands of unit tests are generated asynchronously without real-time human or lead-agent blocking.
- **Resource Envelope**: Workloads requiring GPU 1 to co-locate secondary services (e.g. embedding models, vector databases) where the 7B model's $6.2$ GiB VRAM footprint is mandatory.
- **Mandatory Fence**: Must remain strictly isolated from gateway port 8010 and gated behind `ExternalAuthorityBoundary` AST and JSON validation.

---

## 5. Monitoring Thresholds & Rollback Plan

If Configuration B exhibits any operational degradation, the following automated triggers and runbooks apply:

1. **Worker Failure Fallback**:
   If Worker 2 experiences $> 1$ failure or HTTP 500 response, the orchestrator routes 100% of tasks to Worker 1 and alerts systems operations.
2. **Latency Degradation Trigger**:
   If mean Stage 2 duration exceeds $65.0$ seconds across 3 consecutive projects, the scheduler reverts to Configuration A serial dispatch.
3. **Rollback Script**:
   Immediate reversion to baseline Configuration A is executable in $< 30$ seconds via:
   ```bash
   /etc/local-ai/orchestrator/scripts/revert_to_serial_stage2.sh
   ```
