# Implementation Plan: PLAN-03 - Gateway Release Promotion & Snapshot Reconciliation

- **Plan ID**: `PLAN-03`
- **Specification Ref**: `SPEC-03`
- **Milestone**: `M2`
- **Target Components**: `roles/orchestrator_gateway/`, `inventory/production/host_vars/ai-5820-01.yml`, `/home/mike/.local/share/aihost/reconcile/snapshot`
- **Estimated Effort**: 4-8 hours (Lead Engineer & Platform Operator)

---

## 1. Concrete Tasks & Execution Sequence

### Task 3.1: Pre-Deployment Readiness Check
- Verify current production health:
  ```bash
  curl --cacert /home/mike/.config/opencode/t5820-gateway-ca.crt \
       -H "Authorization: Bearer $(cat /home/mike/.config/opencode/t5820-client-token)" \
       https://10.0.8.5:8443/health
  ```
- Confirm `status: healthy`, 2/2 workers active.

### Task 3.2: Stage Candidate Gateway on Port 8002
- Deploy release candidate `t5820-gateway-b72a4f5` to candidate port:
  ```bash
  ansible-playbook -i inventory/production/hosts.yml playbooks/candidate.yml \
                   -e candidate_gateway_release_id=t5820-gateway-b72a4f5 \
                   -e candidate_port=8002
  ```

### Task 3.3: Run Candidate Qualification Suite
- From controller `mike-dev`, execute the automated candidate evaluation suite:
  ```bash
  python3 scripts/qualify.py all --endpoint https://10.0.8.5:8443 --model candidate/gateway-test
  ```
- Assert: Tool calling passes (7/7 categories), long context passes, finish reason pass-through verified.

### Task 3.4: Promote Gateway Release to Production
- Apply gateway role with production release ID:
  ```bash
  ansible-playbook -i inventory/production/hosts.yml playbooks/inference.yml --tags orchestrator
  ```
- Verify service active:
  ```bash
  ssh mike@10.0.8.5 "systemctl status aihost-orchestrator-gateway.service --no-pager"
  ```

### Task 3.5: Synchronize Controller Reconciliation Snapshot Runner
- Fast-forward snapshot repository to match HEAD:
  ```bash
  cd /home/mike/.local/share/aihost/reconcile/snapshot
  git fetch origin
  git pull --ff-only origin main
  ```
- Verify git commit:
  ```bash
  git rev-parse HEAD
  ```

### Task 3.6: Verify Automated Reconciliation Pass
- Trigger a manual one-shot run of the reconciliation service:
  ```bash
  systemctl --user start aihost-reconcile.service
  journalctl --user -u aihost-reconcile.service -n 50 --no-pager
  ```
- Assert: Exit code 0, 0 tasks changed in steady state, `/var/lib/local-ai/evidence/reconcile-last.json` on `ai-5820-01` updated with new git SHA.

---

## 2. Rollback Procedure
If the new gateway fails to start or rejects requests:
1. Revert `inventory/production/host_vars/ai-5820-01.yml` to `orchestrator_gateway_release_id: t5820-gateway-6a3a52e`.
2. Re-apply: `ansible-playbook -i inventory/production/hosts.yml playbooks/inference.yml --tags orchestrator`.
3. Revert snapshot runner git branch to `f169cbbd896e`.
