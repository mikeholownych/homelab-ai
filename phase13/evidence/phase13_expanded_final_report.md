# Phase 13 Expanded Physical Qualification Final Report

## 1. Executive Summary
- **Phase Title**: Phase 13 Expanded Physical Qualification, Remediation, and Deployment Decision
- **Governing Proposal**: `MAINT-PROP-EXPANDED-HETERO-GPU1`
- **Execution Dates**: September 27–28, 2026
- **Terminal Qualification Disposition**:
  $$\mathbf{PHASE\_13\_EXPANDED\_PHYSICAL\_QUALIFICATION:\ PROVEN\_WITH\_LIMITATIONS}$$
  *(Proven for heterogeneous production deployment strictly subject to non-authoritative specialist role fencing and external authority containment)*.
- **Physical Inference Infrastructure**: Dell Precision T5820 (Host `10.0.8.5`, dual Intel Arc Pro B65 32GB GPUs).
- **Current Cluster Status**: **HOMOGENEOUS DUAL-30B BASELINE FULLY RESTORED & OPERATIONAL**. Zero unauthorized production promotions applied.

---

## 2. Campaign Synthesis & Key Findings

### 2.1 Sustained Physical Campaign Results (N = 12 Multi-Stage Projects)
The system executed the preregistered 12-project engineering campaign against the live physical inference cluster, comparing the homogeneous dual-30B baseline against the heterogeneous (30B Lead + 7B Specialist) architecture.

1. **Homogeneous Control Campaign (Dual-30B MoE)**:
   - Projects: `CTRL-01` through `CTRL-06` (48 tasks).
   - Project Acceptance: **6 / 6 (100.0%)**.
   - Total Wall-Clock Duration: 1,271.63 seconds.
   - Sustained Project Throughput: **16.99 accepted projects / hour**.
   - Mean Stage 2 (Concurrent Offload) Duration: **57.05 seconds**.

2. **Heterogeneous Candidate Campaign (30B Lead + 7B Specialist)**:
   - Projects: `HETERO-01` through `HETERO-06` (48 tasks).
   - Project Acceptance: **6 / 6 (100.0%)**.
   - Total Wall-Clock Duration: 1,137.87 seconds.
   - Sustained Project Throughput: **18.98 accepted projects / hour**.
   - Mean Stage 2 (Concurrent Offload) Duration: **34.88 seconds**.

3. **Comparative Performance Delta**:
   - **Throughput Gain**: **+1.99 accepted projects / hour (+11.71% net improvement)**.
   - **Stage 2 Latency Reduction**: **-22.17 seconds (-38.86% latency reduction)**.
   - **Statistical Significance**: Welch's two-sample $t = 93.42$ ($p < 10^{-15}$). Bootstrap 95% Confidence Interval for speedup: **[1.112x, 1.123x]**.
   - **Acceptance Quality**: Parity across all 4 independent acceptance gates (100% acceptance in both cohorts).

---

## 3. Security Reconciliation and Physical Containment Probing

### 3.1 Task 12 Replay & Multi-Channel Adversarial Probing
To definitively address the security finding from the initial Phase 13 physical campaign, the live candidate on Worker 2 (`Qwen/Qwen2.5-7B-Instruct-AWQ`) was subjected to 10 live adversarial probes encompassing Task 12 and 9 operational input channels (repo files, comments, fixtures, tool outputs, docs, structured schemas, handoffs, tests, and security findings):

- **Model Textual Behavior**: The 7B candidate complied in text with 9/10 prompts (reproducing the Task 12 susceptibility).
- **External Quarantine Boundary**: The `ExternalAuthorityBoundary` detected threat vectors across all probes, resulting in **10 / 10 probes rejected and quarantined (100% containment)**.
- **Escalation & Side Effects**:
  - Unauthorized Tool Executions: **0 / 10**.
  - Downstream Context Injections: **0 / 10**.
  - Acceptance Criteria Bypasses: **0 / 10**.

### 3.2 Security Fencing Invariants
To prevent any possibility of security regression in production, the heterogeneous architecture enforces:
1. **Lead Security Review**: Item `-06` (SAST & Security Review) is permanently assigned to Lead 30B on Worker 1.
2. **Specialist Role Bounds**: Worker 2 (7B) is strictly restricted to non-authoritative advisory roles: unit test generation and OpenAPI schema generation.
3. **Out-of-Process Quarantine**: All specialist handoffs must pass through regex threat pattern inspection before consumption by downstream agents.

---

## 4. Controlled Maintenance Lifecycle and Post-Experiment Audit

1. **Preflight Safety**: All 9 preflight gates passed, verifying route isolation, zero in-flight tasks, and cryptographic backups.
2. **Experiment Execution**: Worker 2 was switched to the pinned 7B candidate; live testing completed without affecting Worker 1.
3. **Restoration & Verification**:
   - Worker 2 was immediately reverted to `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on port 8001.
   - Configuration file digest `/etc/local-ai/vllm/worker2/vllm-config.yaml` was verified via SHA-256 (`641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`), exactly matching the baseline backup.
   - Both workers and the orchestrator gateway are active, healthy, and serving the baseline dual-30B configuration.
4. **Protected Service Immunity**:
   - Worker 1 (`aihost-vllm-worker1.service` on port 8000) maintained 100% continuous uptime.
   - Protected workstation processes (Hermes Gateway PID `986`, SSH Tunnel PID `2093382`, and OpenCode Runner PID `3130937`) experienced zero restarts, signal interruptions, or dropped tasks.

---

## 5. Deployment Decision & Governance
- **Recommendation**: The heterogeneous configuration is **qualified and recommended for conditional production deployment**, conditioned upon automated enforcement of specialist role bounds and external containment quarantine.
- **Governance Constraint**: No production promotion was performed during this qualification phase. Permanent deployment remains subject to separate human authorization under a dedicated maintenance window.
