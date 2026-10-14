# Implementation Plan: PLAN-05 - Observability & Operational Drift Hardening

- **Plan ID**: `PLAN-05`
- **Specification Ref**: `SPEC-05`
- **Milestone**: `M4`
- **Target Components**: `observability/`, `docs/operations.md`, `docs/observability.md`
- **Estimated Effort**: 4-6 hours (Observability / SRE Engineer)

---

## 1. Concrete Tasks & Execution Sequence

### Task 5.1: Document Controller-Driven Reconciliation
- In `docs/operations.md`:
  - Detail why appliance lifecycle timers (`scheduled_ansible_reconcile_enabled`) remain disabled on the target node.
  - Explain the security boundary: Controller `mike-dev` holds the CA private key and Vault AppRole SecretID; the appliance is treated as an isolated workload runner.
  - Provide instructions for inspecting the controller timer:
    ```bash
    systemctl --user status aihost-reconcile.timer
    systemctl --user status aihost-reconcile.service
    ```
  - Document the verification stamp: `/var/lib/local-ai/evidence/reconcile-last.json` on `ai-5820-01`.

### Task 5.2: Verify Prometheus Alerts & Tests
- Execute `promtool` validation:
  ```bash
  promtool check rules observability/prometheus/rules/aihost.rules.yml
  promtool test rules observability/prometheus/tests/aihost.rules.test.yml
  ```
- Assert: SUCCESS for both syntax check and alert rule evaluation scenarios.

### Task 5.3: Synchronize Grafana Dashboards
- Re-run dashboard builder:
  ```bash
  python3 observability/tools/build_dashboards.py
  git diff --exit-code observability/ roles/observability/
  ```
- Assert: Clean exit code 0 with zero uncommitted changes.

### Task 5.4: Live Telemetry & Tracing Pipeline Verification
- Query VictoriaMetrics on `10.0.8.2`:
  ```bash
  curl -s "http://10.0.8.2:8428/api/v1/query?query=up%7Binstance%3D%22ai-5820-01%22%7D"
  ```
- Query Tempo trace collector on `10.0.8.2:3200` to confirm ingestion of gateway spans (`service.name = "aihost-gateway"`).
- Query Grafana on `http://10.0.8.2:3000` to confirm zero "No Data" panels across `aihost-inference` and `aihost-host` dashboards.

---

## 2. Acceptance Criteria
1. `promtool test rules` passes 100%.
2. `build_dashboards.py` produces zero diff.
3. Observability dashboards render live metrics without missing panels.
