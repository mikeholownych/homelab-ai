# Phase 11 Evaluation Corpus Report: Representative Workload Curation and Anti-Contamination Quarantine

## Executive Summary

Phase 11 Workstream A established a versioned, multi-partition engineering evaluation corpus designed to represent realistic engineering workloads encountered by the Autonomous Engineering System. The corpus enforces strict partition boundaries (`DEVELOPMENT`, `CALIBRATION`, and `HELD_OUT`) and guarantees anti-contamination isolation for held-out evaluation fixtures.

---

## 1. Corpus Partitioning & Workload Classification

The standard corpus indexes 12 diverse evaluation tasks across 12 distinct engineering workload classes:

| Task ID | Workload Class | Partition | Complexity | Sandbox Timeout | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `task-bug-fix-001` | `bug_investigation` | `CALIBRATION` | Medium | 120s | Fix concurrency race condition in cache eviction |
| `task-feature-auth-002` | `feature_addition` | `CALIBRATION` | High | 180s | Add HMAC token verification adapter |
| `task-refactor-ast-003` | `refactoring` | `CALIBRATION` | Medium | 120s | Refactor symbol table visitor to AST generator |
| `task-test-gen-004` | `test_generation` | `CALIBRATION` | Low | 60s | Generate regression tests for parser boundary cases |
| `task-doc-sync-005` | `documentation_sync` | `CALIBRATION` | Low | 60s | Sync OpenAPI docstrings with route signatures |
| `task-migr-v2-006` | `api_migration` | `CALIBRATION` | Medium | 120s | Migrate legacy storage calls to repository engine |
| `task-perf-idx-007` | `perf_optimization` | `CALIBRATION` | High | 180s | Optimize memory allocation in streaming pipeline |
| `task-sec-xss-008` | `security_hardening` | `CALIBRATION` | High | 180s | Sanitize unescaped query parameters in router |
| `task-cfg-yaml-009` | `config_migration` | `CALIBRATION` | Low | 60s | Validate YAML schema parser with strict typing |
| `task-dep-up-010` | `dependency_upgrade`| `CALIBRATION` | Medium | 120s | Upgrade cryptography library and fix API deprecation |
| `task-dev-scratch-001`| `bug_investigation` | `DEVELOPMENT` | Low | 60s | Development scratch task for rapid iteration |
| `task-held-out-eval-001`| `feature_addition` | `HELD_OUT` | High | 300s | Quarantined held-out task for tamper validation |

---

## 2. Anti-Contamination Quarantine Enforcement

Held-out evaluation tasks are isolated within a cryptographic and logical quarantine:
1. **Inspection Fencing**: Any call to inspect held-out ground truth fixtures or test solutions requires caller authorization equal to `held_out_auditor`.
2. **Access Rejection**: Unauthorized agents or evaluators attempting to read quarantined files receive an immediate `CorpusContaminationError`.
3. **Partition Integrity**: Tasks marked as `HELD_OUT` can never be selected for calibration runs, prompt tuning, or few-shot exemplar extraction.

---

## 3. Cryptographic Corpus Digest

The corpus manager calculates a canonical SHA-256 digest across all registered task definitions, parameters, and partition assignments:
- Canonical Algorithm: `SHA-256(sorted_json_task_manifest)`
- Tamper Evidence: Any mutation of task parameters, expected changes, or partition assignments immediately alters the corpus digest, invalidating subsequent qualification comparisons.
