# Phase 13 Physical Campaign Execution Plan: Controlled Heterogeneous Evaluation

**Document Identifier**: `phase13_physical_campaign_execution_plan.md`  
**Proposal Reference**: `MAINT-PROP-PHASE13-HETERO-GPU1`  
**Target Host**: Dell Precision T5820 (`ai-5820-01`, `10.0.8.5`)  
**Created At**: 2026-09-27T22:04:00Z  
**Status**: `FROZEN_PRE_EXECUTION`  

---

## 1. Exact Maintenance Scope

This maintenance campaign executes conditional authorization for proposal `MAINT-PROP-PHASE13-HETERO-GPU1`.
The scope is strictly limited to:
- Temporarily replacing the model on **Worker 2** (`vllm-xpu-tp1-worker2`, port 8001) hosted on **GPU 1** (Intel Arc Pro B65, PCI `0000:93:00.0`, Level Zero device 1) with candidate `Qwen/Qwen2.5-7B-Instruct-AWQ` (revision `b25037543e9394b818fdfca67ab2a00ecc7dd641`).
- Preserving **Worker 1** (`vllm-xpu-tp1-worker1`, port 8000) on **GPU 0** (PCI `0000:51:00.0`, Level Zero device 0) serving the protected baseline `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` as the sole production endpoint for route `engineering/b0`.
- Evaluating candidate performance under identical code-first contracts with `max_tokens=2048`.
- Running the frozen 8-item dependency DAG heterogeneous project workload.
- Evaluating live routing, specialist capability gating, and automatic fallback.
- Restoring Worker 2 to its exact dual-30B baseline configuration and verifying post-restoration health.
- Hard maintenance duration: Maximum 15 minutes (900 seconds) for the disruptive maintenance window.

---

## 2. Current Worker and GPU Identities

Authoritative hardware and service mapping:

| Attribute | Worker 1 (Control / Protected) | Worker 2 (Candidate Target) |
|---|---|---|
| **Host** | Dell Precision T5820 (`10.0.8.5`) | Dell Precision T5820 (`10.0.8.5`) |
| **Systemd Service** | `aihost-vllm-worker1.service` | `aihost-vllm-worker2.service` |
| **Container Name** | `vllm-xpu-tp1-worker1` | `vllm-xpu-tp1-worker2` |
| **Physical PCI BDF** | `0000:51:00.0` | `0000:93:00.0` |
| **Level Zero Device** | `0` (`ZE_AFFINITY_MASK=0`) | `1` (`ZE_AFFINITY_MASK=1`) |
| **DRM / Render Nodes** | `/dev/dri/card1`, `/dev/dri/renderD128` | `/dev/dri/card2`, `/dev/dri/renderD129` |
| **Serving Port** | `8000` | `8001` |
| **Production Route** | `engineering/b0` (via Gateway 8010) | ISOLATED / EXPERIMENTAL (not in Gateway 8010) |
| **Baseline Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Candidate Model** | N/A (Protected immutable) | `Qwen/Qwen2.5-7B-Instruct-AWQ` (rev `b25037543e9394b818fdfca67ab2a00ecc7dd641`) |

Protected host processes:
- Hermes Gateway (PID `986`): Protected local gateway service.
- Local SSH forwarding tunnel (PID `2093382`): Port forwarding to remote host.
- OpenCode Autonomous Engineering Runner (PID `3130937`): Active host process; zero child sandbox processes.

---

## 3. Production-Route Isolation Procedure

1. **Gateway Reconfiguration**:
   - Inspect `/etc/local-ai/orchestrator/gateway.env`.
   - Backup `/etc/local-ai/orchestrator/gateway.env` to `/etc/local-ai/orchestrator/gateway.env.baseline-backup`.
   - Update `ORCHESTRATOR_GATEWAY_WORKER_PORTS="8000 "` (removing port 8001).
   - Restart gateway: `sudo systemctl restart aihost-orchestrator-gateway.service`.
2. **Traffic Verification**:
   - Send 5 consecutive authenticated requests to `http://127.0.0.1:8010/v1/chat/completions`.
   - Verify all 5 requests return response headers/metadata from Worker 1 (port 8000).
   - Confirm Worker 2 receives 0 gateway requests.
3. **Endpoint Segregation**:
   - Worker 2 on port 8001 is accessed directly via authenticated loopback / dedicated experimental tunnel (`http://127.0.0.1:18001`).
   - The candidate model name `Qwen/Qwen2.5-7B-Instruct-AWQ` is never registered as an alias for `engineering/b0`.

---

## 4. Active-Workload Drain Procedure

1. **Inspect Active Workloads**:
   - Check PID `3130937` child processes (`pgrep -P 3130937`).
   - Query Worker 2 metrics: `curl -s http://127.0.0.1:8001/metrics | grep vllm:num_requests_running`.
2. **Drain Confirmation**:
   - Verify `vllm:num_requests_running == 0.0` and `vllm:num_requests_waiting == 0.0`.
   - If in-flight requests > 0, pause for up to 30 seconds until count reaches 0.
   - If drain does not complete within 60s, abort maintenance.

---

## 5. Candidate Startup Procedure

1. **Configuration Backup**:
   - Backup `/etc/local-ai/vllm/worker2/vllm-config.yaml` to `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup`.
   - Backup `/etc/local-ai/vllm/worker2/vllm.env` to `/etc/local-ai/vllm/worker2/vllm.env.baseline-backup`.
   - Record SHA-256 digests.
2. **Stop Baseline Worker 2**:
   - Record maintenance start timestamp.
   - Run: `sudo systemctl stop aihost-vllm-worker2.service`.
   - Verify container stops and GPU 1 memory drops to baseline (~42 MiB).
3. **Deploy Candidate Configuration**:
   - Update `/etc/local-ai/vllm/worker2/vllm-config.yaml`:
     - `model: /var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641`
     - `served-model-name: ["Qwen/Qwen2.5-7B-Instruct-AWQ"]`
     - `max-model-len: 32768`
     - `enable-auto-tool-choice: true`
     - `tool-call-parser: hermes`
     - `device: xpu`
   - Update `/etc/local-ai/vllm/worker2/vllm.env`:
     - `VLLM_XPU_EXPECTED_MODEL="Qwen/Qwen2.5-7B-Instruct-AWQ"`
4. **Start Candidate Worker 2**:
   - Run: `sudo systemctl start aihost-vllm-worker2.service`.
   - Monitor startup log until readiness observer records `READY` on port 8001.
   - Expected startup duration: 25-35 seconds.
5. **Direct Smoke Probe**:
   - Query candidate endpoint on port 8001: authenticated completion with prompt `"Respond with CANDIDATE_SMOKE_OK"`.
   - Verify model header reports `Qwen/Qwen2.5-7B-Instruct-AWQ`.

---

## 6. Fair-Comparison Protocol

To eliminate the Phase 12 completion-budget asymmetry:
1. **Contract Parity**: Both 30B control and 7B candidate are evaluated under the identical code-first prompt and JSON/code fence contract.
2. **Completion Budget**: Both models receive `max_tokens=2048` and identical temperature (`0.0`).
3. **Task Set**: The frozen 12-task qualification cohort:
   - `calib-01-defect-repair`
   - `calib-02-security-sanitize`
   - `calib-03-feature-hmac`
   - `calib-04-refactor-ast`
   - `heldout_defect_01_off_by_one_paging`
   - `heldout_defect_02_deadlock_ordering`
   - `heldout_defect_03_memory_leak_closure`
   - `heldout_maintain_01_decouple_notifier`
   - `heldout_maintain_02_extract_transaction`
   - `heldout_maintain_03_consolidate_validation`
   - `heldout_multifile_01_rate_limiter`
   - `heldout_testdev_01_fencing_invariant`
4. **Validation**: All completions are evaluated against the authoritative independent test runners and AST linters.
5. **Trace Preservation**: Store candidate results in `phase13/traces/phase13_matched_comparison_results.json` and `phase13/evidence/phase13_matched_comparison_results.json`.

---

## 7. Sustained Workload Duration and Arrival Profile

The sustained heterogeneous workload exercises the frozen 8-item dependency DAG:
- Item 1: `T1_ARCH_PLAN` (Lead Architect, 30B, context ~4K, planning)
- Item 2: `T2_INTERFACE_DEF` (Lead Architect, 30B, interface contract)
- Item 3: `T3_IMPL_CORE` (Specialist, 7B, core implementation, code-first)
- Item 4: `T4_IMPL_STORAGE` (Specialist, 7B, storage backend, code-first)
- Item 5: `T5_UNIT_TESTS` (Specialist, 7B, unit test generation)
- Item 6: `T6_STRUCTURED_CONFIG` (Specialist, 7B, schema validation & JSON config)
- Item 7: `T7_SECURITY_REVIEW` (Lead Architect, 30B, security audit & taint analysis)
- Item 8: `T8_FINAL_INTEGRATION` (Lead Architect, 30B, integration & project gate)

Concurrency profile:
- Stage A (Sequential Lead): T1 -> T2
- Stage B (Concurrent Specialists): T3 || T4 || T5 || T6 (parallel requests dispatched to Worker 2 while Worker 1 serves lead tasks)
- Stage C (Sequential Review & Acceptance): T7 -> T8

Multiple project waves will be dispatched sequentially to measure throughput stability, latency distribution, and zero-degradation sustainability.
Results stored in `phase13/traces/phase13_sustained_physical_results.json`.

---

## 8. Independent Acceptance Criteria

Project acceptance is strictly decoupled from generation. A project is marked `ACCEPTED` iff:
1. **Gate 1 (Syntax & Parsing)**: Generated files parse cleanly into AST without syntax errors.
2. **Gate 2 (Unit Testing)**: Generated unit tests run in disposable test harness and pass 100%.
3. **Gate 3 (Security & Invariants)**: Static analyzer detects 0 security vulnerabilities or contract violations.
4. **Gate 4 (Integration Invariant)**: Full cross-module integration test passes.

---

## 9. Operational Performance Metrics

The primary metric is:
`INDEPENDENTLY_ACCEPTED_ENGINEERING_PROJECTS_PER_HOUR = (Accepted Projects / Total Elapsed Seconds) * 3600`

Secondary metrics:
- First-pass task acceptance rate (%).
- Final task acceptance rate (%).
- Specialist decode throughput (tokens/second).
- Lead decode throughput (tokens/second).
- Peak GPU VRAM per device (MiB).
- KV cache utilization (%).
- Dynamic context memory consumption.
- Handoff latency (seconds).
- Automatic fallback invocation rate.

---

## 10. Failure Injection and Fallback Tests

Verify fail-closed specialist boundary:
1. **Context Limit Exceeded**: Dispatch task with prompt > 32,768 tokens -> Verify rejection at specialist boundary and clean fallback to Lead (30B).
2. **Authority Violation**: Specialist attempts architectural approval -> Verify permission rejected and routed to Lead.
3. **Schema Violation**: Malformed output from specialist -> Bounded repair initiated; if second attempt fails, transparent fallback to 30B.
4. **Endpoint Failure**: Simulate specialist unavailability -> Transparent fallback to Worker 1 without task loss.

---

## 11. Maintenance Time Budget

| Phase | Description | Estimated Duration | Cumulative Time |
|---|---|---|---|
| Step 1 | Isolation & Drain Verification | 30 s | 0:30 |
| Step 2 | Worker 2 Stop & Candidate Load | 35 s | 1:05 |
| Step 3 | Candidate Smoke Test | 10 s | 1:15 |
| Step 4 | Matched Comparison Campaign (N=12) | 210 s | 4:45 |
| Step 5 | Sustained Heterogeneous DAG Projects | 90 s | 6:15 |
| Step 6 | Live Routing & Fallback Verification | 45 s | 7:00 |
| Step 7 | Candidate Shutdown & Baseline Load (30B) | 270 s | 11:30 |
| Step 8 | Baseline Health & Gateway Restoration | 45 s | 12:15 |
| **Total** | **Planned Disruptive Window** | **~735 s (12.25 min)** | **Buffer: 2.75 min (< 15 min)** |

---

## 12. Rollback Time Reserve

- **Baseline 30B MoE Load Time**: 240 - 270 seconds (4 shards from local SSD to Intel Arc Pro B65 VRAM).
- **Service Verification**: 30 seconds.
- **Rollback Reserve Threshold**: 330 seconds (5.5 minutes).
- **Hard Execution Deadline**: If campaign execution has not completed by minute 9:30 of the maintenance window, immediate abort is triggered to guarantee clean restoration before minute 15:00.

---

## 13. Automatic Abort Conditions

The campaign aborts immediately with automatic restoration if:
1. Worker 1 on GPU 0 becomes unhealthy or unavailable.
2. Gateway routes candidate traffic to public `engineering/b0`.
3. Candidate startup exceeds 90 seconds.
4. Host memory or VRAM exceeds safe operating thresholds.
5. In-flight tasks under PID `3130937` exhibit anomalies.
6. Maintenance elapsed time reaches 570 seconds (9 min 30 s) before evaluation completes.
7. Any unexpected package or library dependency upgrade is required.

---

## 14. Post-Restoration Verification

Upon completing rollback:
1. Verify Worker 2 configuration matches SHA-256 `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`.
2. Verify Worker 2 reports `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` at port 8001.
3. Verify readiness observer reports `READY` on both Worker 1 and Worker 2.
4. Verify Gateway round-robin balance across port 8000 and 8001 on port 8010.
5. Verify 10 consecutive requests alternate evenly between Worker 1 and Worker 2.
6. Verify protected processes (PIDs 986, 2093382, 3130937) remain undisturbed.

---

## 15. Evidence Custody and Manifest Procedure

1. All raw responses, token counts, timestamps, and validator results are captured in machine-verifiable JSON.
2. Output JSON traces are saved to both `phase13/traces/` and `phase13/evidence/`.
3. Every markdown and JSON artifact is hashed with SHA-256 and recorded in `phase13/evidence/manifest.sha256`.
4. The manifest is verified with `sha256sum -c`.
5. An additive git commit is made on branch `phase13-heterogeneous-qualification`.
