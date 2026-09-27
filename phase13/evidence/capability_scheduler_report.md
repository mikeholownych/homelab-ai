# Capability-Aware Scheduler & Fail-Closed Fallback Report

## 1. Executive Summary

In conformance with Phase 13 Workstream D and Gate G6, this report presents the design, mathematical model, and empirical validation of the Capability-Aware Heterogeneous Scheduler codified in [`capability_scheduler.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/capability_scheduler.py).

The scheduler governs request routing across Worker 1 (GPU 0: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) and Worker 2 (GPU 1: `Qwen/Qwen2.5-7B-Instruct-AWQ`), ensuring that tasks are dispatched according to verified capabilities, context limits, tool privileges, and current health status.

---

## 2. Dispatch Logic & Deterministic Decision Tree

When an engineering task $T = \langle \text{id}, \text{class}, \text{context\_tokens}, \text{tools} \rangle$ arrives at the scheduling boundary:

```
                          [ Incoming Engineering Task ]
                                       |
                   Context Tokens > 32,768 or Task Class
               in {ARCHITECTURAL_PLANNING, MULTI_FILE, INTEGRATION}?
                                    /     \
                                 YES       NO
                                 /           \
               [ Route to Worker 1 ]       Is Specialist Worker 2
              (Lead 30B Authority)         Healthy & Model Match?
                                                 /     \
                                               YES      NO
                                               /          \
                             [ Route to Worker 2 ]     [ Fallback to Worker 1 ]
                            (Specialist 7B Engine)     (Lead 30B Authority)
                                       |                          |
                            [ Independent Validator ]  [ Independent Validator ]
                                     /     \
                                  PASS     FAIL
                                  /           \
                         [ Commit Output ]  [ Escalate to Lead Worker 1 ]
```

---

## 3. Fallback Mechanisms & Provenance Preservation

1. **Context Overflow Fallback**:
   - If an engineering task requires multi-file repository knowledge exceeding 32,768 tokens (e.g. 45,000 tokens), the scheduler bypasses the specialist and assigns Worker 1 directly.
   - Provenance entry: `FALLBACK:Context length 45000 exceeds specialist ceiling 32768`.
2. **Authority Escalation Prevention**:
   - If an agent profile attempts to route an architectural planning task or a multi-file dependency cut to the specialist, the scheduler rejects the admission and routes to the lead.
   - Provenance entry: `SPECIALIST_REJECTED:Task class ARCHITECTURAL_PLANNING is not permitted for specialist`.
3. **Validator Failure Escalation**:
   - When a specialist produces code that fails independent validation after its authorized repair budget (1–2 retries), `handle_specialist_validation_failure` is invoked.
   - The task is dispatched to Worker 1 with full error context and prior attempts attached.
   - Provenance entry: `SPECIALIST_EXECUTION_FAILED:TASK-09:msg=SyntaxError`.
4. **Worker Degradation & Outage Fallback**:
   - If Worker 2 transitions to `UNHEALTHY` or `DEGRADED`, 100% of tasks automatically divert to Worker 1.
   - The system fails closed with zero task drops.

---

## 4. Verification & Testing

The scheduler and fallback mechanisms are validated by test suite `test_capability_scheduler.py` covering:
- Admissible specialist routing
- Context-overflow diversion
- Unhealthy worker failover
- Validation failure escalation
- Authority boundary preservation
- Complete provenance chain auditing
