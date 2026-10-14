# Implementation Plan: PLAN-01 - Repository Hygiene & CI Linter Remediation

- **Plan ID**: `PLAN-01`
- **Specification Ref**: `SPEC-01`
- **Milestone**: `M0`
- **Target Components**: `observability/prometheus/rules/aihost.rules.yml`, `roles/orchestrator_gateway/defaults/main.yml`, `roles/orchestrator_gateway/tasks/main.yml`
- **Estimated Effort**: 1-2 hours (Platform Engineer)

---

## 1. Concrete Tasks & Execution Sequence

### Task 1.1: Remediate `aihost.rules.yml` Formatting
- **File**: `observability/prometheus/rules/aihost.rules.yml`
- **Action**: Delete line 186 (extra blank line between rule definitions).
- **Validation**:
  ```bash
  .venv/bin/yamllint observability/prometheus/rules/aihost.rules.yml
  promtool check rules observability/prometheus/rules/aihost.rules.yml
  ```

### Task 1.2: Remediate `orchestrator_gateway/defaults/main.yml` Line Length
- **File**: `roles/orchestrator_gateway/defaults/main.yml`
- **Action**: Wrap line 89 to ensure character count <= 120 columns.
- **Validation**:
  ```bash
  .venv/bin/yamllint roles/orchestrator_gateway/defaults/main.yml
  ```

### Task 1.3: Remediate Variable Naming in `orchestrator_gateway/tasks/main.yml`
- **File**: `roles/orchestrator_gateway/tasks/main.yml`
- **Action**:
  - Locate task "Discover historical gateway releases for retention pruning" (line ~350).
  - Rename `register: _historical_gateway_releases` to `register: _orchestrator_gateway_historical_releases`.
  - Update dependent variable references in the subsequent pruning task from `_historical_gateway_releases.files` to `_orchestrator_gateway_historical_releases.files`.
- **Validation**:
  ```bash
  .venv/bin/ansible-lint roles/orchestrator_gateway/tasks/main.yml
  ```

### Task 1.4: Repository-Wide Lint Verification
- **Command**:
  ```bash
  make lint
  ```
- **Success Criteria**: Returns 0 fatal errors, 0 warnings.

---

## 2. Rollback & Precautionary Steps
- Changes are purely syntactical and within YAML formatting rules. If a syntax regression occurs, revert via `git checkout -- <file>`.
