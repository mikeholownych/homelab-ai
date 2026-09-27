# Phase 11 Independent Evaluation Report: Sandboxed Engineering Outcomes and Failure Taxonomy

## Executive Summary

Phase 11 Workstream C established the Independent Engineering Evaluator harness. Rather than relying on synthetic benchmarks or proxy evaluation scores, candidates are evaluated by executing real, sandboxed engineering workflows and verifying their deliverables through independent validation contracts.

---

## 1. Measured Engineering Dimensions

For every candidate and task, the evaluator captures:
1. **End-to-End Acceptance**: Binary verification indicating whether the generated deliverable passed all independent validation test suites.
2. **Acceptance Rate & Velocity**: Percent of tasks accepted and accepted engineering deliverables per clock hour.
3. **Token Consumption**: Input tokens, output tokens, and reasoning tokens consumed per task.
4. **Latency Profiles**: Time to First Token (TTFT) and total task wall-clock completion time.
5. **Throughput**: Output tokens generated per second under operational concurrency.
6. **Sandboxed Trace Integrity**: Complete, untampered stdout, stderr, and sandbox exit codes recorded in durable task logs.

---

## 2. Standardized Failure Taxonomy

When a candidate fails an evaluation task, the failure is categorized into one of six mutually exclusive, immutable failure types:

1. `SCOPE_VIOLATION`: The candidate attempted to modify files outside the declared workspace boundaries or exceeded designated tool authorities.
2. `INCORRECT_IMPLEMENTATION`: Code was produced but failed independent unit/integration tests or logical assertions.
3. `VALIDATION_FAILURE`: The change failed linter checks, type checking, or syntax verification.
4. `TIMEOUT`: Execution exceeded the allocated sandbox duration for the workload class.
5. `INFRASTRUCTURE_ERROR`: Sandbox container, worker node, or communication socket error occurred.
6. `UNAUTHORIZED_ESCALATION`: The candidate attempted to issue privileged tool invocations or manipulate authority tokens.

---

## 3. Evaluation Fencing & Integrity Protection

The evaluator operates in strict isolation:
- Sandboxed execution ensures candidate commands cannot access host environment secrets or network sockets outside the evaluation bridge.
- Evaluation metrics are computed strictly by independent validator harnesses—the candidate agent has no write access to its own evaluation score records.
