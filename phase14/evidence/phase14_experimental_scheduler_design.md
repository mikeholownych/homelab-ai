# Phase 14 Experiment 01: Experimental Scheduler Design

## 1. Executive Summary & Rationale

Phase 13 promoted `SchedulingMode.CONFIGURATION_B` into the default production engineering pipeline on a homogeneous dual-30B physical deployment:
- **Worker 1 (Lead)**: GPU 0 (local `127.0.0.1:18000`), `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Worker 2 (Specialist)**: GPU 1 (remote `10.0.8.5:8001`), `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`

Under Configuration B, Worker 2 executes Item 04 (advisory test generation) and Item 05 (schema contract generation) concurrently with Worker 1 executing Item 06 (security review) in Stage 2. However, Worker 1 executes all of Stage 1 (Items 01, 02, 03) and all of Stage 3 (Items 07, 08). Worker 1 accounts for ~80.1% of all critical-path service demand, while Worker 2 sits completely idle during Stage 1 and Stage 3.

**Configuration B+** rebalances the pipeline by offloading **Item 01 (Architecture & System Investigation)** to Worker 2. Because both workers run identical 30B MoE models, offloading Item 01 incurs **zero semantic degradation** while relieving ~28.3 seconds of critical-path service demand from Worker 1 per project.

---

## 2. Formal Scheduling Mode Specification

The scheduler extends Phase 13's `CapabilityAwareScheduler` via `RebalancedScheduler`, introducing `ExtendedSchedulingMode`:

```python
class ExtendedSchedulingMode(str, Enum):
    CONFIGURATION_A = "config_a"        # Sequential dual-30B baseline
    CONFIGURATION_B = "config_b"        # Production default: Stage 2 parallelization
    CONFIGURATION_B_PLUS = "config_b_plus"  # Experimental: Item 01 offload to Worker 2
```

### Production Protection Invariant
- **Default Production Mode**: `SchedulingMode.CONFIGURATION_B` (`config_b`).
- **Activation of Configuration B+**: Strictly opt-in via explicit parameter `ExtendedSchedulingMode.CONFIGURATION_B_PLUS` or runtime mode selection.
- **Fail-Closed Fallback**: In the event of invalid configuration or corrupted state, the scheduler reverts automatically to `CONFIGURATION_B`.

---

## 3. Task Placement Matrix

| Item | Stage | Task Description | Configuration B Worker | Configuration B+ Worker | Authority Level | Preconditions |
|---|---|---|---|---|---|---|
| **01** | Stage 1 | Architecture & System Investigation | **Worker 1 (Lead)** | **Worker 2 (Specialist)** | Non-Authoritative (Advisory Finding) | Repository HEAD Verified |
| **--** | **Handoff** | **Quarantined Envelope Validation** | N/A | **Item01HandoffValidator** | Security Boundary | Item 01 completed, SHA matched |
| **02** | Stage 1 | Execution DAG & Rollback Plan | Worker 1 (Lead) | Worker 1 (Lead) | Lead Authoritative | Handoff Validated & Ingested |
| **03** | Stage 1 | Core Multi-File Implementation | Worker 1 (Lead) | Worker 1 (Lead) | Lead Authoritative | Item 02 Plan Approved |
| **04** | Stage 2 | Advisory Test Generation | Worker 2 (Specialist) | Worker 2 (Specialist) | Non-Authoritative | Item 03 Implemented |
| **05** | Stage 2 | Structured Output & Schema Contract | Worker 2 (Specialist) | Worker 2 (Specialist) | Non-Authoritative | Item 03 Implemented |
| **06** | Stage 2 | Lead Security Review | Worker 1 (Lead) | Worker 1 (Lead) | Lead Authoritative | Concurrent with 04/05 |
| **07** | Stage 3 | Multi-File Integration & Gate Wiring | Worker 1 (Lead) | Worker 1 (Lead) | Lead Authoritative | Stage 2 Items Completed |
| **08** | Stage 3 | Project Acceptance & Signoff | Worker 1 (Lead) | Worker 1 (Lead) | Lead Authoritative | 4-Gate Independent Passes |

---

## 4. Item 01 Handoff Architecture & Security Containment

Because Worker 2 operates under a non-authoritative boundary, its output cannot be directly trusted or executed by Worker 1. 

### The 4-Layer Safety Handoff Contract
1. **Cryptographic Sealing**: Worker 2 structures its findings into an `InvestigationHandoffEnvelope` containing project ID, task ID, repo SHA, timestamp, structured findings, and a SHA-256 payload digest.
2. **Repository Consistency Check**: The validator checks that `repo_sha` matches the current canonical git SHA. Stale findings are rejected immediately (`REJECTED_STALE_REPO_SHA`).
3. **External Authority Boundary Scan**: All text is scanned for jailbreaks, prompt injection, tool elevation strings (e.g. `rm -rf`, `sudo`, `subprocess`), or markdown evasion syntax. Malicious content is quarantined (`REJECTED_ADVERSARIAL_PAYLOAD`).
4. **Quarantine Ingestion Barrier**: Worker 1 only consumes findings wrapped in strict non-executable boundary markers:
```markdown
<!-- BEGIN QUARANTINED INVESTIGATION HANDOFF (ID: f5a3b9...) -->
Investigation findings enclosed as pure advisory context.
<!-- END QUARANTINED INVESTIGATION HANDOFF -->
```

---

## 5. Rollback and Fail-Closed Policy

The `RebalancedScheduler` implements strict rollback mechanisms:

1. **Worker 2 Offline / Timeout**: If Worker 2 fails to respond within 180s on Item 01, the pipeline catches the error, logs a degraded state event, and automatically routes Item 01 to Worker 1 as fallback.
2. **Handoff Validation Failure**: If the envelope signature fails or an adversarial pattern is detected, the handoff is rejected, a security alert is triggered, and Worker 1 executes Item 01 directly under the verified control path.
3. **Operational Reversion**: Calling `revert_to_production_default()` immediately re-engages `SchedulingMode.CONFIGURATION_B` and drops all B+ routing rules.
