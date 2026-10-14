# homelab-ai v1.0.0 Documentation & Planning Index

- **Document Version**: `1.0.0-PROPOSED`
- **Audit Baseline SHA**: `2d69e5df37263ee38c14adcd8af8755f67d9513d`
- **Audit Date**: 2026-10-14
- **Readiness Verdict**: **`V1_0_0_NOT_DEMONSTRATED_CONTRADICTED_BY_BLOCKERS`**

---

## 1. Overview of the v1.0.0 Planning Package

This documentation package provides the authoritative audit, formal requirements, execution roadmap, technical specifications, implementation plans, and objective release gates necessary to bring `homelab-ai` to defensible v1.0.0 maturity.

The audit verified that while low-level inference on the target Dell Precision 5820 Tower (`ai-5820-01`) with dual Intel Arc Pro B65 GPUs is highly operational and performant, release readiness is currently contradicted by **five critical blockers**:
1. **Live Gateway Drift**: Production appliance runs older gateway release `6a3a52e` via a controller snapshot pinned to historical commit `f169cbbd896e` (Oct 11), while repo `main` contains Phase 4 enterprise capabilities (`b72a4f5`).
2. **`make lint` Failure**: Clean-checkout CI validation fails with 3 fatal violations in Prometheus rules and orchestrator gateway defaults/tasks.
3. **Documentation Architecture Mismatch**: `README.md` and `docs/architecture.md` claim vLLM TP=2 is the primary serving runtime, whereas vLLM is retired on production in favor of dual-llama.cpp SYCL TP=1 instances.
4. **Phantom Fleet Member `ai-p620-01`**: Uncommissioned Lenovo P620 host remains declared in active production inventory with `ansible_host: CHANGE_ME`.
5. **Orphaned `vault_servers` Inventory Definition**: Playbook `vault-server.yml` targets a missing host group, generating warnings and leaving Vault control plane automation ambiguous.

---

## 2. Deliverables Directory Map

```
docs/v1.0.0/
├── README.md                                  # This master index and traceability map
├── V1.0.0-AUDIT.md                            # Comprehensive baseline audit & ranked findings
├── V1.0.0-REQUIREMENTS.md                     # Product contract & master requirement ledger
├── V1.0.0-ROADMAP.md                          # Dependency-ordered execution milestones (M0-M5)
├── V1.0.0-RELEASE-GATES.md                    # Objective go/no-go checklist & qualification matrix
├── specs/                                     # Technical specifications
│   ├── SPEC-01-LINT-REPO-INTEGRITY.md         # Linter and repository hygiene remediation
│   ├── SPEC-02-FLEET-TOPOLOGY-DECOUPLING.md   # Inventory decoupling of ai-p620-01 & vault_servers
│   ├── SPEC-03-GATEWAY-CONTROLLER-ALIGNMENT.md# Gateway deployment & reconciliation snapshot sync
│   ├── SPEC-04-ENGINE-DOCS-RECONCILIATION.md  # Truth-in-docs: dual-llama.cpp SYCL serving stack
│   ├── SPEC-05-OBSERVABILITY-DRIFT-HARDENING.md# Observability, alerting, and drift runbooks
│   └── SPEC-06-VAULT-BOUNDARY-BACKUP.md       # Vault authority boundary, unsealing, and DR
└── implementation-plans/                      # Step-by-step executable plans
    ├── PLAN-01-LINT-REPO-INTEGRITY.md         # Execution plan for SPEC-01
    ├── PLAN-02-FLEET-TOPOLOGY-DECOUPLING.md   # Execution plan for SPEC-02
    ├── PLAN-03-GATEWAY-CONTROLLER-ALIGNMENT.md# Execution plan for SPEC-03
    ├── PLAN-04-ENGINE-DOCS-RECONCILIATION.md  # Execution plan for SPEC-04
    ├── PLAN-05-OBSERVABILITY-DRIFT-HARDENING.md# Execution plan for SPEC-05
    └── PLAN-06-VAULT-BOUNDARY-BACKUP.md       # Execution plan for SPEC-06
```

---

## 3. End-to-End Traceability Matrix

This matrix establishes complete forward and backward traceability across the planning package:
**Finding $\to$ Requirement $\to$ Milestone $\to$ Specification $\to$ Implementation Plan $\to$ Acceptance Evidence $\to$ Release Gate**

| Finding ID | Requirement ID | Milestone | Specification | Implementation Plan | Required Acceptance Evidence | Release Gate |
|---|---|---|---|---|---|---|
| `F-02` | `REQ-SEC-05`, `REQ-VAL-01` | `M0` | [`SPEC-01`](specs/SPEC-01-LINT-REPO-INTEGRITY.md) | [`PLAN-01`](implementation-plans/PLAN-01-LINT-REPO-INTEGRITY.md) | Clean `make lint` execution (0 errors) | `GATE-CI-01` |
| `F-04` | `REQ-PROV-05` | `M1` | [`SPEC-02`](specs/SPEC-02-FLEET-TOPOLOGY-DECOUPLING.md) | [`PLAN-02`](implementation-plans/PLAN-02-FLEET-TOPOLOGY-DECOUPLING.md) | `ansible-inventory --list` resolves valid IPs | `GATE-FLEET-01` |
| `F-05` | `REQ-OPS-05` | `M1`, `M4` | [`SPEC-02`](specs/SPEC-02-FLEET-TOPOLOGY-DECOUPLING.md), [`SPEC-06`](specs/SPEC-06-VAULT-BOUNDARY-BACKUP.md) | [`PLAN-02`](implementation-plans/PLAN-02-FLEET-TOPOLOGY-DECOUPLING.md), [`PLAN-06`](implementation-plans/PLAN-06-VAULT-BOUNDARY-BACKUP.md) | `make syntax` passes without warnings; unseal runbook | `GATE-CI-02` |
| `F-01` | `REQ-PROV-02`, `REQ-ARCH-04`, `REQ-ARCH-05` | `M2` | [`SPEC-03`](specs/SPEC-03-GATEWAY-CONTROLLER-ALIGNMENT.md) | [`PLAN-03`](implementation-plans/PLAN-03-GATEWAY-CONTROLLER-ALIGNMENT.md) | Live unit runs `b72a4f5`; snapshot matches HEAD | `GATE-DEP-01`, `GATE-DEP-02` |
| `F-03`, `F-09` | `REQ-PROV-01`, `REQ-VAL-04` | `M3` | [`SPEC-04`](specs/SPEC-04-ENGINE-DOCS-RECONCILIATION.md) | [`PLAN-04`](implementation-plans/PLAN-04-ENGINE-DOCS-RECONCILIATION.md) | Docs declare dual-llama.cpp; `test_documentation_contract` passes | `GATE-DOC-01`, `GATE-DOC-02` |
| `F-06`, `F-07` | `REQ-OPS-01`, `REQ-OPS-02` | `M4` | [`SPEC-05`](specs/SPEC-05-OBSERVABILITY-DRIFT-HARDENING.md) | [`PLAN-05`](implementation-plans/PLAN-05-OBSERVABILITY-DRIFT-HARDENING.md) | `promtool test rules` SUCCESS; dashboards render green | `GATE-OPS-01`, `GATE-OPS-02` |
| N/A | `REQ-INFER-01` to `05` | `M5` | Platform Core | Live Baseline Verification | Dual B65 Level Zero memory, context & reasoning verified | `GATE-INF-01` to `04` |
| N/A | `REQ-SEC-01` to `04` | `M5` | Platform Core | Live Baseline Verification | Zero secrets in repo; nftables UID isolation; TLS verified | `GATE-SEC-01` to `04` |
| N/A | `REQ-PROV-04` | `M5` | Platform Core | Rollback Verification | Successful live rollback and re-convergence drill | `GATE-REL-01` |

---

## 4. Recommended First Milestone: Milestone M0 & M1

The recommended immediate implementation step is to execute **Milestone M0 (Repository Hygiene & CI Integrity)** followed immediately by **Milestone M1 (Fleet Topology Decoupling)**:
- **Why Start Here**:
  1. `M0` takes less than 2 hours and unblocks automated CI checks (`make lint`), providing immediate safety for all subsequent changes.
  2. `M1` resolves confusing inventory warnings, ensures playbooks target only accessible hardware, and clearly delineates the v1.0.0 appliance scope without modifying running services.
  3. Neither milestone touches live inference workloads, rotates secrets, or restarts running containers, minimizing operational risk.
- **Next Steps**:
  1. Review and authorize [`PLAN-01`](implementation-plans/PLAN-01-LINT-REPO-INTEGRITY.md).
  2. Review and authorize [`PLAN-02`](implementation-plans/PLAN-02-FLEET-TOPOLOGY-DECOUPLING.md).
  3. Schedule a maintenance window for [`PLAN-03`](implementation-plans/PLAN-03-GATEWAY-CONTROLLER-ALIGNMENT.md) (production gateway promotion).
