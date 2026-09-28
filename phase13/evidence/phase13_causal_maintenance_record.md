# Phase 13 Causal Maintenance Authorization Record: Controlled Worker 2 Qualification

## 1. Maintenance Identifier & Scope
- **Proposal Identifier**: `MAINT-PROP-CAUSAL-HETERO-GPU1`
- **Governing Phase**: Phase 13 Continuation: Scheduling-Matched Causal Qualification
- **Target Host**: Dell Precision T5820 (`10.0.8.5`)
- **Authorized Target**: Worker 2 on GPU 1 (PCI `0000:93:00.0`, Port `8001`)
- **Protected Exclusions**:
  - Worker 1 on GPU 0 (`0000:51:00.0`, Port `8000`) remains strictly protected.
  - Production Gateway (`aihost-orchestrator-gateway.service`, Port `8010`) remains isolated.
  - Protected daemons (Hermes PID `986`, SSH PID `2093382`, OpenCode PID `3130937`) remain completely undisturbed.
- **Authorized Actions**:
  1. Execute Configuration A (Original Homogeneous Baseline) on existing dual-30B workers.
  2. Execute Configuration B (Scheduling-Matched Homogeneous Baseline) on existing dual-30B workers.
  3. Temporarily stop `aihost-vllm-worker2.service` and deploy candidate `Qwen/Qwen2.5-7B-Instruct-AWQ`.
  4. Execute Configuration C (Scheduling-Matched Heterogeneous Candidate) and physical containment revalidation.
  5. Restore Worker 2 to baseline dual-30B serving and verify configuration SHA-256 (`641c9402`).

---

## 2. Maintenance Window Budget & Timeline Allocation

- **Total Authorized Window**: 180 minutes (3.0 hours)
- **Phase Schedule**:
  - Preflight Verification: 5 minutes
  - Configuration A Execution (6 projects): ~20 minutes
  - Configuration B Execution (6 projects): ~20 minutes
  - Worker 2 Candidate Switch (`candidate_switch.sh`): 3 minutes
  - Configuration C Execution (6 projects): ~20 minutes
  - Physical Containment Revalidation Probes (10 probes): 5 minutes
  - Sustained Queueing Telemetry & Evaluation: 30 minutes
  - Baseline Restoration (`baseline_restore.sh`): 5 minutes
  - Post-Restoration Verification & Audit: 10 minutes
  - Rollback Reserve: 62 minutes

---

## 3. Configuration Inventory & Cryptographic Baselines

| Component | Baseline Dual-30B Serving | Candidate Temporary State |
| :--- | :--- | :--- |
| **Worker 2 Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `Qwen/Qwen2.5-7B-Instruct-AWQ` |
| **Model Snapshot** | `4bd30395b72ea6045edd04806c4fea448d4467b3` | `b25037543e9394b818fdfca67ab2a00ecc7dd641` |
| **Config Hash** | `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` | Dynamic ephemeral switch |
| **Backup Config** | `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup` | Preserved read-only |
| **Gateway Port 8010** | Round-robin across Workers 8000 & 8001 | Pinned strictly to Worker 1 (`8000`) |

---

## 4. Automatic Rollback Triggers & Safety Thresholds

The maintenance operator or automated runner must immediately abort and execute `baseline_restore.sh` if any of the following occur:
1. **Protected Service Interference**: Any request failure or timeout on `http://127.0.0.1:18000` (Worker 1) or `http://127.0.0.1:18010` (Gateway).
2. **Containment Escape**: Any tool execution, unauthorized filesystem access, or shell invocation triggered by Worker 2.
3. **Consecutive Project Failures**: 2 consecutive unaccepted projects under any configuration.
4. **Thermal Limit Exceeded**: Any GPU exceeding $80^\circ\text{C}$ or VRAM uncorrectable ECC errors.
5. **Window Expiration**: Elapsed maintenance reaching 120 minutes without campaign completion.

Authorized by Principal Engineering Agent under directive authority.
