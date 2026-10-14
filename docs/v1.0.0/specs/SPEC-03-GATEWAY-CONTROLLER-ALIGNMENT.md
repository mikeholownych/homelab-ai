# Technical Specification: SPEC-03 - Gateway Release Alignment & Controller Reconciliation

- **Specification ID**: `SPEC-03`
- **Related Finding**: `F-01` (Live production gateway drift vs. stagnant controller snapshot)
- **Related Requirements**: `REQ-ARCH-04`, `REQ-ARCH-05`, `REQ-PROV-02`
- **Target Milestone**: `M2` (Gateway Release & Controller Reconciliation Alignment)
- **Status**: Ready for Implementation

---

## 1. Problem Statement & Evidence
- **Repository State**: Commit `b72a4f5` introduced Phase 4 enterprise capabilities to the gateway (ASGI engine, zero-downtime hot reload, dual circuit breakers, semantic caching, watchdog supervisor, web console), and commit `fb1a2cd` updated `inventory/production/host_vars/ai-5820-01.yml` to specify `orchestrator_gateway_release_id: t5820-gateway-b72a4f5`.
- **Live Production State**: The running gateway process on `ai-5820-01` (PID 468409) runs older release `t5820-gateway-6a3a52e`.
- **Root Cause**: The controller hourly reconciliation service (`aihost-reconcile.service`) executes from an isolated snapshot at `/home/mike/.local/share/aihost/reconcile/snapshot` pinned to historical commit `f169cbbd896e` (Oct 11 2026). In that snapshot, `orchestrator_gateway_release_id` is still `t5820-gateway-6a3a52e`.
- **Impact**: New features are undeployed; the repository and production are fundamentally out of sync.

---

## 2. Desired Behavior & Scope
- **Scope**:
  - Deploy and stage candidate release `t5820-gateway-b72a4f5` on non-routable port (:8002) using `playbooks/candidate.yml`.
  - Execute remote client qualification suite (`Q-BUDGET`, `Q-TOOLS`, `Q-LONGCTX`, `Q-CONTRACT`) against candidate alias.
  - Promote `t5820-gateway-b72a4f5` to production by deploying through `roles/orchestrator_gateway` and restarting `aihost-orchestrator-gateway.service`.
  - Update the controller snapshot runner `/home/mike/.local/share/aihost/reconcile/snapshot` to git HEAD (fast-forward pull to match commit `fb1a2cd` / current HEAD).
  - Verify live systemd service status, journal logs, `/health` endpoint, `/v1/models`, and OTLP trace emission to `http://10.0.8.2:4318`.
- **Non-Goals**:
  - Modifying inference worker model weights or GGUF files.
  - Changing client authentication tokens or private CA keys.

---

## 3. Interfaces & State Transitions
- **Release Directory Packaging**:
  - New release installed at `/var/lib/aihost/releases/t5820-gateway-b72a4f5`.
  - Unit `aihost-orchestrator-gateway.service` updated:
    `WorkingDirectory=/var/lib/aihost/releases/t5820-gateway-b72a4f5`
    `Environment=PYTHONPATH=/var/lib/aihost/releases/t5820-gateway-b72a4f5`
- **Controller Snapshot Synchronization**:
```bash
git -C /home/mike/.local/share/aihost/reconcile/snapshot fetch origin
git -C /home/mike/.local/share/aihost/reconcile/snapshot checkout main
git -C /home/mike/.local/share/aihost/reconcile/snapshot pull --ff-only
```
- **Service Transition**:
  - Preflight checks verify worker socket availability.
  - Systemd executes daemon-reload and restarts `aihost-orchestrator-gateway.service`.
  - Health check asserts `http://127.0.0.1:8010/health` returns HTTP 200 within 60s.

---

## 4. Operational & Rollback Plan
- **Pre-Deployment Backup**: Retain existing release directory `/var/lib/aihost/releases/t5820-gateway-6a3a52e`.
- **Rollback Procedure**: In the event of gateway failure or unhandled exception, re-converge with `orchestrator_gateway_release_id: t5820-gateway-6a3a52e` or revert the snapshot to commit `f169cbbd896e`.
- **Verification Guardrail**: Verify `systemctl status aihost-orchestrator-gateway` and `journalctl -u aihost-orchestrator-gateway -n 30` immediately post-convergence.

---

## 5. Acceptance Criteria
1. `ssh mike@10.0.8.5 "systemctl show aihost-orchestrator-gateway.service -p WorkingDirectory"` returns `/var/lib/aihost/releases/t5820-gateway-b72a4f5`.
2. `curl -k https://10.0.8.5:8443/health` returns `status: healthy` and `ready: true`.
3. `/home/mike/.local/share/aihost/reconcile/snapshot` git commit matches repository HEAD.
4. Next hourly execution of `aihost-reconcile.service` completes with `result: success` and 0 changed tasks.
