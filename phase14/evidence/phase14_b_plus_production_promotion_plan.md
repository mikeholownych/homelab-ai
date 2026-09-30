# Phase 14: Configuration B+ Production Promotion Plan (Non-Executing)

- **Document Identifier:** `PHASE_14_B_PLUS_PRODUCTION_PROMOTION_PLAN`
- **Status:** **DRAFT - AWAITING HUMAN OPERATOR AUTHORIZATION**
- **Date:** 2026-09-29
- **Target Host:** Dell Precision T5820 (`10.0.8.5`)
- **Current Production Mode:** `SchedulingMode.CONFIGURATION_B`
- **Target Production Mode:** `SchedulingMode.CONFIGURATION_B_PLUS`
- **Execution State:** **NON-EXECUTING**. This document defines the formal promotion package, rollback controls, and operational guardrails. It does not execute changes.

---

## 1. Approved Source and Configuration Identities

| Attribute | Baseline Configuration B | Target Configuration B+ | Verification Control |
|---|---|---|---|
| **Git Commit SHA** | `3a21d516244d2d471583d73b64ec471887e07621` | `3a21d516244d2d471583d73b64ec471887e07621` | `git rev-parse HEAD` |
| **Release Artifact** | `t5820-gateway-3a21d51` | `t5820-gateway-3a21d51` (or tagged B+ promotion) | `/var/lib/aihost/releases/` |
| **Scheduler Mode** | `SchedulingMode.CONFIGURATION_B` | `SchedulingMode.CONFIGURATION_B_PLUS` | Gateway configuration / env |
| **Worker 1 (Lead)** | Battlemage B65 (`51:00.0`), port 8000 | Battlemage B65 (`51:00.0`), port 8000 | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Worker 2 (Specialist)**| Battlemage B65 (`93:00.0`), port 8001 | Battlemage B65 (`93:00.0`), port 8001 | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Item 01 Assignment** | Worker 1 (Lead) | Worker 2 (Specialist) | Rebalanced pipeline contract |
| **Item 01 Handoff Gate** | N/A (single worker Stage 1) | Sealed `InvestigationHandoffEnvelope` | Mandatory validation before Item 02 |

---

## 2. Production Configuration Delta (B to B+)

1. **Pipeline Stage Rebalancing:**
   - In Configuration B, Stage 1 (Items 01, 02, 03) runs entirely on Worker 1, creating a $\sim 194\text{s}$ critical-path bottleneck.
   - In Configuration B+, Item 01 (Architecture Investigation) is routed to Worker 2 (Specialist).
2. **Cryptographic Handoff Enforcement:**
   - Worker 2 generates an `InvestigationFinding` set, packages it in an `InvestigationHandoffEnvelope`, seals it with a SHA-256 digest, and submits it to `Item01HandoffValidator`.
   - Worker 1 does not initiate Item 02 DAG planning until the envelope is verified `CLEAN` and accepted.
3. **Gateway Scheduling Configuration:**
   - Update gateway configuration file (`/etc/aihost/orchestrator-gateway.conf` or drop-in) from `SCHEDULING_MODE=CONFIGURATION_B` to `SCHEDULING_MODE=CONFIGURATION_B_PLUS`.

---

## 3. Preserved Rollback Configuration

- **Rollback File:** `/etc/aihost/orchestrator-gateway.conf.baseline-b`
- **Instant Rollback Command:**
  ```bash
  sudo sed -i 's/SCHEDULING_MODE=CONFIGURATION_B_PLUS/SCHEDULING_MODE=CONFIGURATION_B/' /etc/aihost/orchestrator-gateway.conf
  sudo systemctl reload-or-restart aihost-orchestrator-gateway.service
  ```
- **Rollback Target State:** Strict restoration of `SchedulingMode.CONFIGURATION_B` without requiring model reloading or worker restarts.
- **Rollback Recovery Window:** $\le 5\text{ seconds}$ service restart.

---

## 4. Predeployment Gates

Before applying configuration changes, the following checks must pass:
1. **Workload Drain Gate:** Confirm zero in-flight inference requests across Worker 1, Worker 2, and Gateway (`aihost_scheduler_active_work == 0`, `aihost_http_requests_in_flight == 0`).
2. **Outside Agent Confirmation:** Confirm OpenCode and external agent workloads are paused or coordinated.
3. **Engine Health Check:** Both Battlemage B65 workers must return `200 OK` on `/v1/models` within $50\text{ms}$.
4. **Git Repository Status:** Repository clean on `main` at approved commit `3a21d51`.

---

## 5. Deployment & Postdeployment Acceptance Checks

1. **Deploy Configuration:**
   - Apply drop-in setting `SCHEDULING_MODE=CONFIGURATION_B_PLUS`.
   - Reload gateway systemd unit.
2. **Postdeployment Verification:**
   - Query `GET /health` on port 8010: verify `status: "healthy"`, `ready: true`, `can_route: true`.
   - Query `GET /metrics` on port 8010: verify `aihost_worker_health_status == 1.0` for both workers.
   - Execute one canary project (e.g. `proj-api-01`) through the promoted pipeline:
     - Verify Item 01 executes on Worker 2.
     - Verify handoff receipt digest is recorded.
     - Verify Items 02, 03 execute on Worker 1.
     - Verify 4-gate validation passes.

---

## 6. Prometheus Monitoring & Alert Thresholds

The newly deployed observability release will actively ingest telemetry. The following Prometheus alert rules must be configured:

| Metric / Rule | Warning Threshold | Critical / Rollback Trigger | Description |
|---|---|---|---|
| `aihost_worker_health_status` | $< 1.0$ for $> 15\text{s}$ | $< 1.0$ for $> 30\text{s}$ | Worker unreachable or unhealthy |
| `aihost_scheduler_queue_wait_seconds` | Mean $> 15.0\text{s}$ over $5\text{m}$ | P95 $> 60.0\text{s}$ over $5\text{m}$ | Unexpected queue backlog accumulation |
| `aihost_scheduler_queued_work` | $\ge 2$ projects | $\ge 3$ projects | Queue backlog accumulation |
| `aihost_authority_rejections_total` | $> 0$ | $\ge 2$ in $10\text{m}$ | Preflight or invariant violation |
| `aihost_http_requests_total{status_class="5xx"}` | $> 0$ | $\ge 2$ in $5\text{m}$ | Unhandled gateway server errors |
| `aihost_worker_last_check_timestamp_seconds` | Freshness $> 20\text{s}$ | Freshness $> 30\text{s}$ | Health check probe staleness |

---

## 7. Rollback Triggers

An immediate automated rollback to `SchedulingMode.CONFIGURATION_B` must be initiated if:
1. Any Item 01 handoff validation failure or quarantine event occurs during production execution.
2. P95 queue wait exceeds $60\text{ seconds}$ under offered traffic $\le 18.0\text{ proj/hr}$.
3. Any 5xx error occurs on either worker or gateway.
4. Worker 1 or Worker 2 experiences Level Zero / GPU fault or driver reset.
5. External authority boundary fails closed on any legitimate engineering project.

---

## 8. Evidence Required to Close the Production Change

To declare Phase 14 complete and close the production change:
1. Postdeployment canary receipt verifying Item 01 handoff and 4-gate acceptance.
2. 1-hour sustained production metrics export from Prometheus showing zero 5xx errors, healthy worker status, and stable queue depth.
3. Systemd journalctl cursors recording zero unhandled exceptions.
4. Final signed production promotion receipt.

---

## 9. Operator Authorization Boundary

**STOP: AWAITING OPERATOR AUTHORIZATION.**

- **Current Status:** Configuration B remains the active production mode.
- **Action Required:** The human operator must explicitly authorize production promotion of Configuration B+ before any configuration files or systemd services are modified.
