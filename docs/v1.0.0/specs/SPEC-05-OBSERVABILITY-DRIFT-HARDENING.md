# Technical Specification: SPEC-05 - Observability & Operational Drift Hardening

- **Specification ID**: `SPEC-05`
- **Related Findings**: `F-06` (Appliance-side lifecycle timers disabled), `F-07` (Incomplete worker trace propagation)
- **Related Requirements**: `REQ-OPS-01`, `REQ-OPS-02`, `REQ-OPS-03`
- **Target Milestone**: `M4` (Observability, Operational Hardening & Vault Control Plane)
- **Status**: Ready for Implementation

---

## 1. Problem Statement & Evidence
1. **Appliance-Side Lifecycle Timers Disabled**: In `inventory/production/host_vars/ai-5820-01.yml`, `scheduled_ansible_reconcile_enabled: false` and `scheduled_ansible_validate_enabled: false`. Reconciliation was moved to the controller (`aihost-reconcile.service` on `mike-dev`) because the appliance does not possess the CA private key and cannot safely self-converge without controller secrets. However, the architectural rationale for this split is undocumented in operator runbooks, leaving operators uncertain whether appliance timers should be re-enabled.
2. **Distributed Tracing Boundary Limitation**: While the gateway ingests W3C `traceparent` headers and exports spans via OTLP (`http://10.0.8.2:4318/v1/traces`), the downstream llama.cpp workers do not parse or propagate trace context into their compute kernels. This boundary must be formalized so operators understand the observability scope.

---

## 2. Desired Behavior & Scope
- **Scope**:
  - Document the controller-side drift reconciliation architecture in `docs/operations.md` and `docs/observability.md`, explaining why appliance timers are disabled and how drift alerts are handled.
  - Define and verify Prometheus alert `AIHostReconciliationStale` (triggers if `reconcile-last.json` is older than 2 hours).
  - Verify VictoriaMetrics metric ingestion from `10.0.8.5:9100` and `10.0.8.5:8010/metrics`.
  - Validate that Grafana dashboards render with zero "No Data" states under both idle and loaded conditions.
  - Formalize the OTLP tracing boundary: gateway provides full request lifecycle and latency attribution; worker-internal kernel spans are documented as post-v1.
- **Non-Goals**:
  - Modifying upstream llama.cpp source code to inject OpenTelemetry spans into C++ Level Zero kernels.
  - Enabling local mutating reconciliation on the appliance without controller CA keys.

---

## 3. Implementation & Verification Details
- **Alert Rule Verification**:
  - Validate `AIHostReconciliationStale` in `observability/prometheus/rules/aihost.rules.yml`.
  - Execute `promtool check rules` and `promtool test rules`.
- **Dashboard Synchronization**:
  - Run `python3 observability/tools/build_dashboards.py` to ensure dashboards and Jinja2 templates remain byte-synchronized.
- **Runbook Enhancement**:
  - Add troubleshooting section to `docs/operations.md` detailing how to inspect controller reconciliation logs (`journalctl --user -u aihost-reconcile -n 50`) and verify target stamp (`/var/lib/local-ai/evidence/reconcile-last.json`).

---

## 4. Acceptance Criteria
1. `promtool check rules observability/prometheus/rules/aihost.rules.yml` succeeds.
2. `promtool test rules observability/prometheus/tests/aihost.rules.test.yml` passes with SUCCESS.
3. `python3 observability/tools/build_dashboards.py && git diff --exit-code` shows zero uncommitted changes.
4. `docs/operations.md` contains the authoritative controller reconciliation and drift troubleshooting runbook.
