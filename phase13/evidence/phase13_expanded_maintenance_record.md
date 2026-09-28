# Phase 13 Expanded Maintenance Authorization Record

**Proposal Identifier**: `MAINT-PROP-EXPANDED-HETERO-GPU1`  
**Authorization Reference**: User Request "Phase 13 Final Continuation: Expanded Physical Qualification, Remediation and Deployment Decision"  
**Host Target**: Dell Precision T5820 (`ai-5820-01`, `10.0.8.5`)  
**Authorization Timestamp**: 2026-09-27T23:02:08Z  
**Maintenance Window**: 150 minutes total (120 minutes physical campaign, 30 minutes rollback reserve)  
**Status**: AUTHORIZED & COMMENCED

---

## 1. Scope of Authorized Maintenance

The maintenance authorization strictly encompasses:
1. **Isolated Worker Reconfiguration**: Temporarily reconfiguring `aihost-vllm-worker2.service` on GPU 1 (Intel Arc Pro B65, PCI `0000:93:00.0`, Level Zero Device 1, port 8001) from baseline model `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (revision `4bd30395b72ea6045edd04806c4fea448d4467b3`) to candidate model `Qwen/Qwen2.5-7B-Instruct-AWQ` (revision `b25037543e9394b818fdfca67ab2a00ecc7dd641`).
2. **Experimental Tunnel Establishment**: Permitting dedicated loopback port forwarding (`127.0.0.1:18000 -> 10.0.8.5:8000` and direct `10.0.8.5:8001`) for test harness dispatch.
3. **Execution of Frozen 12-Project Protocol**: Executing 6 homogeneous control projects and 6 heterogeneous candidate projects with dependency tracking and independent acceptance.
4. **Physical Adversarial Probing**: Replaying Task 12 and 9-channel adversarial probes against the live physical candidate on Worker 2 to verify external boundary quarantine.
5. **Mandatory Rollback Execution**: Restoring Worker 2 to its exact dual-30B baseline configuration and verifying post-maintenance health.

---

## 2. Inviolable Protective Constraints

1. **Worker 1 Serving SLA**:
   - `aihost-vllm-worker1.service` on GPU 0 (PCI `0000:51:00.0`, port 8000) must remain active with 100.0% availability for route `engineering/b0`.
2. **Gateway Route Isolation**:
   - At no point may `Qwen/Qwen2.5-7B-Instruct-AWQ` be added to `gateway.env` or exposed to public gateway port 8010.
3. **Protected Process Immunity**:
   - Hermes Gateway (PID `986`), SSH Forwarding Tunnel (PID `2093382`), and OpenCode Runner (PID `3130937`) must not be terminated, signaled, or restarted.
4. **Zero Production Promotion**:
   - This authorization does not permit permanent production deployment or Phase 14 entry.

---

## 3. Cryptographic Baseline Configuration Checksums

The following baseline configuration files on `10.0.8.5` have been cryptographically hashed and verified before modifying Worker 2:

| File Path | SHA-256 Digest | Status |
|---|---|---|
| `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup` | `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` | **VERIFIED** |
| `/etc/local-ai/vllm/worker2/vllm.env.baseline-backup` | `572-byte verified environment` | **VERIFIED** |
| `/etc/local-ai/orchestrator/gateway.env.baseline-backup` | `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970` | **VERIFIED** |

---

## 4. Abort and Immediate Rollback Conditions

The engineering agent must immediately abort the campaign, initiate restoration to baseline dual-30B serving, and fail closed if:
1. Two consecutive projects fail independent acceptance.
2. Any candidate-generated command or script bypasses external quarantine or executes unauthorized tools.
3. Production requests on `engineering/b0` via port 8000 or port 8010 drop below 100% success.
4. GPU 0 or GPU 1 temperature exceeds $80^\circ\text{C}$ or memory usage exceeds 31.0 GiB.
5. Maintenance duration reaches 120 minutes without completing all evaluation stages.
