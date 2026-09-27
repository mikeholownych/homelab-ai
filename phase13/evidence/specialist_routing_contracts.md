# Specialist Routing Contracts & Authority Containment Report

## 1. Executive Summary & Governance Standard

In conformance with Phase 13 Workstream C and Gate G5, this document defines the immutable routing contracts, authority boundaries, context ceilings, and fail-closed escalation rules for specialized agent profiles within the heterogeneous inference architecture.

### Governance Principles:
1. **No Authority Escalation**: The candidate model `Qwen/Qwen2.5-7B-Instruct-AWQ` is strictly restricted to bounded specialist profiles (Unit Test Synthesis, Structured Output, Security Auditing). Under no circumstances may it be assigned repository architecture, cross-module dependency decomposition, or project-level integration tasks.
2. **Context Envelopes Enforced**: The specialist context limit is rigidly clamped to **32,768 tokens**. Any task requiring context exceeding 32,768 tokens must route immediately to the lead model (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) which supports 65,536 tokens.
3. **Advisory Deliverable Status**: All specialist outputs are strictly advisory. Deliverables cannot be committed to repository state or promoted across pipeline stages without explicit acceptance by independent external validators (`pytest`, AST analyzers, schema validators).
4. **Deterministic Fallback**: If a specialist fails independent validation or encounters a runtime error, execution immediately escalates to the lead engineering model, preserving provenance and preventing cyclic retry storms.

---

## 2. Authoritative Specialist Profile Definitions

```
========================================================================================================
CONTRACT DIMENSION         TEST SPECIALIST                 STRUCTURED OUTPUT AGENT        LEAD ENGINEERING MODEL
========================================================================================================
Profile Identifier         specialist-test-engineer-v1    specialist-structured-output-v1 lead-engineering-authority-v1
Target Model               Qwen2.5-7B-Instruct-AWQ        Qwen2.5-7B-Instruct-AWQ         Qwen3-Coder-30B-AWQ
Target Revision            b25037543e9394b818fdfca67...   b25037543e9394b818fdfca67...    4bd30395b72ea6045edd048...
Assigned Hardware          Worker 2 (GPU 1 / B65)         Worker 2 (GPU 1 / B65)          Worker 1 (GPU 0 / B65)
Max Context Length         32,768 tokens                  32,768 tokens                   65,536 tokens
Permitted Task Classes     TEST_GENERATION                STRUCTURED_OUTPUT               ALL ENGINEERING TASKS
Permitted Tools            read_file, run_pytest, ast     validate_json_schema, openapi   ALL AUTHORIZED TOOLS
Expected Output Format     pytest test methods / classes  strict JSON / OpenAPI specs     full python / diffs
Independent Validator      pytest_coverage_validator      json_schema_validator           multi_stage_integration
Retry Budget               2 repair attempts              1 repair attempt                3 repair attempts
Escalation Target          lead-engineering-authority-v1  lead-engineering-authority-v1   HUMAN SUPERVISOR
External Acceptance Req.   YES (Mandatory)                YES (Mandatory)                 YES (Mandatory)
========================================================================================================
```

---

## 3. Fail-Closed Escalation Protocol

When a task is processed by a specialized agent:

1. **Pre-Dispatch Context Inspection**:
   - The scheduler computes `prompt_tokens + context_tokens`.
   - If token count $> 32,768$, the task is diverted to the lead model with provenance log: `DIVERT_SPECIALIST_CONTEXT_OVERFLOW`.
2. **Authority Boundary Enforcement**:
   - Tasks with class `ARCHITECTURAL_PLANNING`, `MULTI_FILE_IMPLEMENTATION`, or `PROJECT_INTEGRATION` are rejected if targeted at a specialist, returning `REJECT_SPECIALIST_AUTHORITY_ESCALATION`.
3. **Execution & Bounded Repair**:
   - If the specialist output fails independent validation, the scheduler allows up to the configured retry budget (e.g. 1 or 2 turns).
   - If errors persist, the specialist yields with disposition `ESCALATE_TO_LEAD`.
4. **Handoff Provenance**:
   - When escalated to the lead model, the lead receives the original prompt, the specialist's draft, the validator failure output, and an explicit handoff marker.
   - The task retains its original work order ID and correlation tokens.

---

## 4. Verification & Testing

Specialist routing contracts are codified in [`specialist_contracts.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/specialist_contracts.py) and validated via unit and adversarial security suites.
