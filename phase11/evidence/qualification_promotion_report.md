# Phase 11 Qualification & Promotion Report: Formal Lifecycle and Human Authorization Gates

## Executive Summary

Phase 11 Workstream I established the Candidate Qualification Lifecycle manager. This module governs the formal state progression of candidates, preventing autonomous self-promotion and ensuring every production change is accompanied by human operator signoff and a verified rollback plan.

---

## 1. Formal Qualification State Machine

Candidates transition through a strictly governed lifecycle:

```
[DRAFT] ──> [EVALUATING] ──> [EVALUATED] ──> [COMPARATIVE_ANALYSIS] ──> [QUALIFIED] ──> [PROMOTED]
   │             │                 │                    │                     │             │
   └─────────────┴─────────────────┴────────────────────┴─────────────────────┴─────────────+──> [REVOKED] / [REJECTED]
```

### Transition Invariants
- Direct transition from `DRAFT` or `EVALUATED` directly to `PROMOTED` is prohibited.
- Transitions must strictly follow sequential progression or transition to `REJECTED` upon early stopping or failure.
- Any attempt to bypass intermediary states fails closed with an `InvalidStateTransitionError`.

---

## 2. Mandatory Human Operator Promotion Gate

Promotion to `PROMOTED` status enforces two non-negotiable security requirements:
1. **Operator Authorization**: The `promoted_by` identity must correspond to a verified human operator (e.g. `mike@homelab-ai`). Calls submitted by autonomous system agents (`autonomous_agent`, `orchestrator`, etc.) raise an immediate `UnauthorizedPromotionError`.
2. **Verified Rollback Plan**: The submission must include a complete rollback specification containing:
   - `target_control_id`: The exact control configuration to revert to if instability arises.
   - `rollback_procedure`: Executable instructions for reverting configuration state.
   - `validation_health_check`: Operational endpoint check to confirm post-rollback recovery.
   - `operator_signoff`: Identity confirmation.
   Absence of a complete rollback plan raises an immediate `MissingRollbackPlanError`.

---

## 3. Auditable Promotion & Revocation History

All lifecycle transitions, timestamps, operator identities, and rollback specifications are logged immutably in SQLite. In the event of post-promotion regression, invoking `rollback_candidate` atomically transitions the candidate to `REVOKED` and restores the designated control baseline.
