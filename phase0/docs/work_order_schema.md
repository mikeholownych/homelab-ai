# Canonical Work-Order Contract Specification and Versioning Rules

**Document ID**: SPEC-WORK-ORDER-PHASE0-2026-09-26  
**Status**: APPROVED / IMPLEMENTATION BASELINE  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Canonical Contract Definition, Section 4  

---

## 1. Role and Principles of the Work Order

The **Work Order** is the canonical, durable contract representing an engineering objective. It is the single shared interface through which all human inputs, system policies, planning steps, execution stages, and validation requirements are governed.

### Key Principles:
1. **Instruction Preservation**: The original raw instruction and its cryptographic hash are permanently embedded.
2. **Ambiguity Transparency**: Material ambiguities are explicitly listed with their resolution status (`UNRESOLVED`, `HUMAN_RESOLVED`, `COMPILER_DEFAULTED`).
3. **Explicit Scope and Constraints**: File paths authorized for mutation, prohibited commands, network policies, and maximum execution budgets are strictly enumerated.
4. **Deterministic Lineage**: Every work order possesses an immutable ID, a monotonically increasing version integer, a pointer to its predecessor version (`predecessor_hash`), and a tamper-evident digest.
5. **Fail-Closed Admission**: Execution cannot proceed without valid authority evaluation.

---

## 2. Canonical Work Order Schema

A canonical work order is composed of twelve explicit sections:

```json
{
  "work_order_id": "wo-20260926-001",
  "version": 1,
  "predecessor_hash": null,
  "created_at": "2026-09-26T21:50:00Z",
  "source_instruction": {
    "raw_text": "Fix zero division error in calculate_ratio when denominator is 0",
    "source_channel": "opencode_cli",
    "source_reference": "session-f0bfd347-step-12",
    "content_hash": "a1b2c3d4..."
  },
  "intent": {
    "normalized_objective": "Handle zero denominator in calculate_ratio by raising ZeroDivisionError or returning null per spec",
    "target_repo": {
      "repository_id": "homelab-ai",
      "baseline_commit": "1aa374a2..."
    }
  },
  "ambiguities": [
    {
      "ambiguity_id": "amb-001",
      "description": "Should calculate_ratio return None or raise ValueError on 0?",
      "status": "HUMAN_RESOLVED",
      "resolution": "Raise ValueError('Denominator cannot be zero')"
    }
  ],
  "authorization": {
    "authority_source": "human_operator:mike",
    "policy_version": "v1.2",
    "valid_until": "2026-09-27T00:00:00Z",
    "revocation_status": false,
    "authorized_mutation_paths": [
      "src/calculator/math_utils.py",
      "tests/test_math_utils.py"
    ],
    "prohibited_operations": [
      "pip install",
      "rm -rf",
      "network_egress",
      "alter_git_history"
    ]
  },
  "acceptance": {
    "criteria": [
      {
        "criterion_id": "crit-001",
        "description": "pytest tests/test_math_utils.py passes cleanly",
        "validator_type": "independent_pytest",
        "test_target": "tests/test_math_utils.py",
        "required": true
      }
    ],
    "independent_validation_required": true
  },
  "dependencies": {
    "permitted_parallelism": 1,
    "prerequisite_work_orders": []
  },
  "budget": {
    "max_retries": 3,
    "max_wallclock_seconds": 600,
    "escalation_policy": "FAIL_CLOSED_ON_BUDGET_EXHAUSTED"
  },
  "state": {
    "current_stage": "ADMITTED",
    "terminal_disposition": null,
    "fencing_token": 1
  },
  "history": [
    {
      "version": 1,
      "timestamp": "2026-09-26T21:50:00Z",
      "change_reason": "Initial submission"
    }
  ],
  "contract_hash": "e3b0c442..."
}
```

---

## 3. Work-Order Revision and Invalidation Rules

When an instruction is modified or scope changes during or after execution:

1. **Monotonic Version Increment**: A new Work Order record is created with `version = previous_version + 1` and `predecessor_hash = previous_contract_hash`.
2. **Authority Re-evaluation**:
   - If the new version expands `authorized_mutation_paths` or relaxes `prohibited_operations`, existing approvals **do not cover** the new version. The admission gate marks the work order `UNAUTHORIZED` until fresh human authorization is submitted.
   - If scope is strictly narrowed or identical, existing valid policy may permit admission.
3. **Active Assignment Invalidation**:
   - The workflow engine immediately revokes active leases and marks in-flight task steps as `SUPERSEDED`.
   - The fencing token for the work order is incremented, causing any late submissions from workers holding older leases to be rejected with `STALE_FENCING_TOKEN`.
4. **Artifact Lineage Invalidation**:
   - Completed artifacts tied to Version $N$ remain preserved in the immutable store with provenance intact.
   - Any downstream task step in Version $N+1$ cannot accept an artifact from Version $N$ unless the artifact's inputs, scope, and target files are completely unaffected by the revision diff.
5. **No Silent Narrowing or Expansion**:
   - The compiler must record every delta between raw human instruction and normalized intent. It cannot silently drop constraints or expand permissions.

---

## 4. Concrete Examples

### Example 1: Simple Defect Repair
A targeted fix where a bug in a known function causes an existing test to fail.
- **Scope**: Exactly 1 source file (`src/calculator/math_utils.py`) and 1 test file (`tests/test_math_utils.py`).
- **Acceptance Criteria**: Pre-registered unit test suite passes under independent validator.
- **Budget**: 2 repair retries, 300s limit.

### Example 2: Multi-File Implementation
A feature addition spanning multiple modules and documentation.
- **Scope**: `src/calculator/core.py`, `src/calculator/formatter.py`, `tests/test_calculator.py`, `docs/api.md`.
- **Dependencies**: Investigation -> Formatter Implementation -> Core Integration -> End-to-End Tests.
- **Acceptance Criteria**: Unit tests + integration tests + linter clean.

### Example 3: Revised Work Order with Expanded Scope (Approval Invalidation)
- **Version 1**: Authorized for `src/calculator/math_utils.py` with budget 1. Admitted and dispatched.
- **Instruction Update**: Human user sends instruction: "Also update the database schema in db/migrations/ and connect to external service".
- **Compilation**: Compiler detects expansion to `db/migrations/` and prohibited network call.
- **Admission Invalidation**: Version 2 created. Active assignment on Version 1 is canceled. Token for Version 1 revoked. Because Version 2 requests mutation paths and operations outside original authority, Version 2 fails admission with `EXPANDED_SCOPE_REQUIRES_NEW_AUTHORITY`.

---
