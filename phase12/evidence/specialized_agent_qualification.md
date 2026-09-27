# Phase 12 Specialized-Agent Qualification Report

## 1. Executive Summary

In accordance with Workstream F and Gate G9, this report evaluates candidate models against the immutable specialized-agent profiles established in Phase 9 and Phase 11.

A fundamental architectural principle of the Autonomous Engineering System is that **no single model is optimal for every engineering specialization**. A smaller, faster model may excel at bounded, high-speed tasks (such as unit test generation and tool calling), while lacking the reasoning capacity required for systems architecture or repository-scale decomposition.

Furthermore, **model capability never expands execution authority**. An agent profile's granted permissions represent an immutable upper bound that cannot be exceeded by model prompt behavior.

---

## 2. Agent Profile Suitability Matrix

| Specialized Agent Profile | Core Competencies | Primary Model Suitability | Secondary Candidate Suitability | Permitted Authority Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Repository Investigator** | AST parsing, dependency graph traversal, call-chain analysis | `engineering/b0` (30B, 64K context) | `cyankiwi/Qwen3.8-27B` (256K context, if kernels supported) | Read-only repo inspection; cannot write files or execute shell. |
| **Systems Architect** | Multi-component planning, API contract design, migration DAGs | `engineering/b0` (30B MoE reasoning) | `casperhansen/llama-3.3-70b` (Requires TP=2) | Proposal generation only; cannot commit or deploy. |
| **Implementation Engineer** | Multi-file defect repair, refactoring, feature synthesis | `engineering/b0` (30B generalist) | None qualified on single GPU | Bounded workspace edits within authorized target directory. |
| **Test Engineer** | Branch-complete unit tests, edge-case generation, mock adapters | `Qwen/Qwen2.5-7B-Instruct-AWQ` (**Optimal Specialist**) | `engineering/b0` | Creation and editing of test files only (`tests/*`). |
| **Security Reviewer** | SAST vulnerability detection, credential scanning, CVE audit | `engineering/b0` / `microsoft/phi-4` | None qualified on host disk | Read-only inspection; generates SARIF security reports. |
| **Integration Reviewer** | End-to-end regression validation, diff verification, PR gates | `engineering/b0` (30B control) | None qualified on host disk | Verification and validation verdict generation. |

---

## 3. Detailed Profile Qualification Analyses

### 3.1 Test Engineer Specialist: `Qwen/Qwen2.5-7B-Instruct-AWQ`
- **Profile Objective**: Synthesizing isolated unit test suites with high branch coverage.
- **Architectural Match**:
  - The 7B AWQ model possesses high token decode throughput (~58 tok/s estimated), enabling rapid generation of parameterized pytest test cases.
  - Test suites do not require deep multi-file reasoning, but demand high adherence to Python test idioms and assert patterns.
- **Suitability Verdict**: **QUALIFIED AS TEST SPECIALIST**. In a heterogeneous multi-worker configuration, offloading test synthesis to the 7B worker frees the 30B worker for core implementation logic.

### 3.2 Implementation Engineer & Architect: `cyankiwi/Qwen3-Coder-30B-AWQ`
- **Profile Objective**: Core application refactoring, cross-module dependency management, and structural defect repair.
- **Architectural Match**:
  - MoE architecture provides 30B parameter capacity with ~3.3B active compute, preserving nuanced contextual reasoning.
  - Successfully handles 65,536 token context windows required for large AST representations.
- **Suitability Verdict**: **QUALIFIED AS GENERAL IMPLEMENTATION & ARCHITECTURE CONTROLLER**.

---

## 4. Permission Boundary and Security Enforcement

1. **Effective Permission Intersection**: An agent instantiated with `Test Engineer` profile and backed by `Qwen2.5-7B` cannot write to `src/` or execute arbitrary system binaries, regardless of model generation outputs.
2. **Authority Revocation**: Any attempt by a specialist model to execute out-of-scope operations (such as modifying system crontabs or git remotes) triggers deterministic fail-closed revocation by the execution fence.
