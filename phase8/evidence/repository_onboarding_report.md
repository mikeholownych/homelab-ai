# Phase 8 Qualification Report: Repository Onboarding and Authority (Workstream A)

## 1. Executive Summary

Workstream A establishes the repository onboarding contract, cryptographic baseline anchoring, and scope boundary enforcement mechanisms of the Phase 8 Autonomous Engineering System.

Key Outcomes:
1. **Explicit Repository Contracts**: Work orders targeting repositories without an active onboarding record fail closed (`RepositoryNotOnboardedError`). Access to credentials or remotes never implies permission to modify code.
2. **Protected Paths Enforcement**: Critical infrastructure paths (e.g. `.github/`, `ci/`, `validators/`, `security/`) are strictly protected. Proposed mutations touching protected paths are blocked immediately (`ProtectedPathViolationError`).
3. **Anti-Traversal & Symlink Defenses**: Path traversal attempts (e.g. `../../etc/shadow`) and root-relative references are caught and rejected (`ScopeBoundaryError`).
4. **Clean Offboarding & Revocation**: Offboarding a repository revokes future admissions and protects historical evidence records.

---

## 2. Repository Contract Specification

Every onboarded repository is governed by an immutable `RepositoryContract`:
- `repository_id`: Canonical alphanumeric identity.
- `remote_url`: Authorized Git remote URL.
- `baseline_commit`: Fixed Git SHA-1/SHA-256 commit hash.
- `permitted_branches`: Explicit list of target integration branches.
- `authorized_mutation_paths`: Allowed subtree scopes.
- `protected_paths`: Prohibited paths that take precedence over authorized subtrees.
- `required_test_commands`: Mandatory automated test suites for validation.
- `resource_budgets`: Max diff size, max duration, max worker concurrency.
- `designated_approver`: Authorized human reviewer identity.

---

## 3. Test Verification & Empirical Results

The onboarding subsystem was qualified across 4 comprehensive tests in `phase8/tests/test_repository_onboarding.py` and demonstrated in `phase8/run_demo.py` section 3:

| Test Case | Scenario / Vector | Observed Control Plane Behavior | Verdict |
|---|---|---|---|
| `test_repository_onboarding_lifecycle` | Onboard, persist in SQLite, retrieve, and offboard repository | Full lifecycle executed; SQLite WAL persistence verified; offboarding revokes lookup | **PASS** |
| `test_contract_validation_rules` | Invalid ID syntax, invalid git commit hash, path traversal in protected paths | `RepositoryValidationError` raised; malformed contracts rejected at onboarding | **PASS** |
| `test_protected_and_authorized_path_enforcement` | Mutation outside authorized scope; mutation touching `.github` or `security/` | `ProtectedPathViolationError` and `ScopeBoundaryError` raised; zero leakage | **PASS** |
| `test_admission_evaluator_integration` | End-to-end admission check with `AdmissionEvaluator` | Un-onboarded repo rejected; protected path rejected; valid repo admitted | **PASS** |

---

## 4. Preregistration Gate G2 Disposition

Gate G2 mandates:
> Repository onboarding, scope enforcement and revocation validated. Access to a repository does not establish permission to modify it.

**Disposition**: **GATE G2: SATISFIED (PROVEN)**.
